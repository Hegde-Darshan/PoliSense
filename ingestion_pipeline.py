# import general modules
from pathlib import Path
import os
import json
from typing import Iterator
from langchain.schema import Document
from dotenv import load_dotenv
from IngestionPipeline.logger import LOGGING_CONFIG

# Import packages with environment variable dependencies
import IngestionPipeline.data_loader as loader
import IngestionPipeline.utils as utils
import IngestionPipeline.vectorizer as vectorizer
from IngestionPipeline.metadata_extractor import extract_metadata_from_path
import faulthandler; faulthandler.enable() #optional: imported to debug system level errors

# Configure loggers
import logging.config
logging.config.dictConfig(LOGGING_CONFIG)
root_logger = logging.getLogger()
logger = root_logger.getChild("ingestion_pipeline")

# Suppress unnecessary logs
logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

# Configure global and environment variables
ROOT_PATH = Path(__file__).parent
try:
    load_dotenv(ROOT_PATH / ".env")
except Exception as e:
    logger.error(f"Error loading .env file: {e}")

#load config file
import yaml
try:
    with open(ROOT_PATH / "config.yml", 'r') as config_file:
        config = yaml.safe_load(config_file)
except FileNotFoundError:
    logger.error("config.yml file not found.")
    raise


def collector(iterator: Iterator, collect: int) -> list[Document] | None:
    """
    Collect a specified number of items from a generator function.
    Args:
        iterator: a python iterator object
        collect: The number of items to collect
    """
    logger.debug(f"Collecting {collect} items from {iterator}")
    collection = []
    for _ in range(collect):
        try:
            collection.append(next(iterator))
        except StopIteration:
            break
    logger.debug(f"Returning {len(collection)} items from {iterator}")
    return collection if collection else None


def convert_metadata_for_chromadb(metadata: dict) -> dict:
    """
    Convert metadata to ChromaDB-compatible format.
    ChromaDB only accepts str, int, float, bool, or None - not lists or dicts.
    Converts lists to comma-separated strings and removes dicts.
    """
    chromadb_metadata = {}
    for key, value in metadata.items():
        if value is None:
            chromadb_metadata[key] = None
        elif isinstance(value, bool):
            chromadb_metadata[key] = value
        elif isinstance(value, (int, float)):
            chromadb_metadata[key] = value
        elif isinstance(value, str):
            chromadb_metadata[key] = value
        elif isinstance(value, list):
            # Convert list to comma-separated string, or empty string if list is empty
            if value:
                chromadb_metadata[key] = ", ".join(str(item) for item in value)
            else:
                chromadb_metadata[key] = ""  # Empty string for empty lists
        elif isinstance(value, dict):
            # Convert dict to JSON string
            chromadb_metadata[key] = json.dumps(value)
        else:
            # Convert any other type to string
            chromadb_metadata[key] = str(value)
    return chromadb_metadata


if __name__ == "__main__":
      
    #get list of new files to ingest
    list_of_files = utils.get_new_filenames(ROOT_PATH/Path(config['TEST_DATA_PATH']), 
                        ROOT_PATH/Path(config['READ_PATH']))
    logger.debug(f"List of new files to ingest: {list_of_files}")

    #local chromadb server run by docker
    #check connection to chroma_server
    chroma_host = os.getenv("CHROMA_SERVER")
    chroma_port_str = os.getenv("CHROMA_PORT") 
    if chroma_host is None or chroma_port_str is None:
        raise EnvironmentError("CHROMA_SERVER and CHROMA_PORT environment variables must be set")
    try:
        chroma_port = int(chroma_port_str)
    except ValueError:
        raise ValueError("CHROMA_PORT environment variable must be an integer")
    
    chroma_client = vectorizer.chroma_server_connect(host=chroma_host, port=int(chroma_port))
    print(chroma_client)
    print(type(chroma_client))
    if not chroma_client:
        raise Exception("Chroma server not available. Cannot ingest data")

    #initialize loader and vectorstore
    file_loader = loader.ChosenFilesDirectoryLoader(ROOT_PATH/Path(config['TEST_DATA_PATH']), list_of_files)
    vectorstore = vectorizer.load_chromadb_collection(client=chroma_client, collection=config['TEST_CHROMA_COLLECTION']) #persist path declared in docker file
    print(f"Vectorstore initialized as follows:\n{vectorstore}\n{type(vectorstore)}")

    if vectorstore is None:
        raise Exception("Vectorstore could not be initialized. Cannot ingest data")

    #ingest documents in batches, defined by collector function
    #initialize document iterator and collect first batch of documents
    doc_iterator = file_loader.lazy_load()
    doc_collection = collector(doc_iterator, 4)

    #ingestion loop
    while doc_collection:
        logger.debug(f"number of documents collected: {len(doc_collection)}")
        enriched_docs = []

        for doc in doc_collection:
            # Get the full relative path from metadata, or construct it from source
            source_path_str = doc.metadata.get("source_path", "")
            if not source_path_str:
                # Fallback: construct path from source and filename if source_path not available
                source_dir = doc.metadata.get("source", "")
                filename = doc.metadata.get("filename", "")
                if source_dir and filename:
                    source_path_str = str(Path(source_dir) / filename)
            
            if source_path_str:
                # Construct full path relative to DATA_PATH
                full_path = ROOT_PATH / Path(config['TEST_DATA_PATH']) / source_path_str
                extracted_meta = extract_metadata_from_path(full_path)
                logger.debug(f"Extracted metadata for {source_path_str}: {extracted_meta}")
                
                # merge metadata (never overwrite existing loader metadata)
                doc.metadata = {**extracted_meta, **doc.metadata}
            
            enriched_docs.append(doc)
        
        #initialize chunk iterator and collect first batch of chunks
        chunk_iterator = loader.lazy_chunker(enriched_docs)
        chunk_collection = collector(chunk_iterator, 10)

        while chunk_collection: 
            logger.debug(f"number of chunks collected: {len(chunk_collection)}")
            # Convert metadata to ChromaDB-compatible format (no lists/dicts)
            for chunk in chunk_collection:
                chunk.metadata = convert_metadata_for_chromadb(chunk.metadata)
            
            try:
                vectorstore.add_documents(chunk_collection)
            except Exception as e:
                logger.error(f"Error adding documents to vectorstore: {e}")

            #getting the next batch of chunks
            chunk_collection = collector(iterator=chunk_iterator, collect=10)

        logger.debug(f" {vectorstore._collection.count()}  vectors indexed")
        #getting the next batch of documents
        doc_collection = collector(iterator=doc_iterator, collect=4)
        

    #save files read
    curr_files = json.load(open(Path(config['READ_PATH']), 'r')) if os.path.exists(Path(config['READ_PATH'])) else []
    list_of_files = list_of_files + curr_files
    logger.debug(f"Files processed so far: {list_of_files}")
    json.dump(list_of_files, open(ROOT_PATH/Path(config['READ_PATH']), 'w'))

    skipped_files = file_loader.skipped
    json.dump(skipped_files, open(ROOT_PATH/Path(config['SKIPPED_PATH']), 'w'))
    
    logger.info("Ingestion process completed.")