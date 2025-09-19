# import general modules
from pathlib import Path
import os
import json
from typing import Iterator
from langchain.schema import Document
from dotenv import load_dotenv
from IngestionPipeline.logger import LOGGING_CONFIG

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

# Import packages with environment variable dependencies
from IngestionPipeline.data_loader import ChosenFilesDirectoryLoader, lazy_chunker
from IngestionPipeline.utils import get_new_filenames
from IngestionPipeline.vectorizer import chroma_server_connect, load_chromadb_collection

import faulthandler; faulthandler.enable() #optional: imported to debug system level errors


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


if __name__ == "__main__":
    
    #get list of new files to ingest
    list_of_files = get_new_filenames(ROOT_PATH/Path("Data"), 
                        ROOT_PATH/Path("documents")/Path("files_read.json")
                    )
    logger.debug(f"List of new files to ingest: {list_of_files}")

    #local chromadb server run by docker
    #check connection to chroma_server
    chroma_client = chroma_server_connect(host=os.getenv("CHROMA_SERVER"), port=int(os.getenv("CHROMA_PORT")))
    if not chroma_client:
        raise Exception("Chroma server not available. Cannot ingest data")

    #initialize loader and vectorstore
    loader = ChosenFilesDirectoryLoader(ROOT_PATH/Path("Data"), list_of_files)
    vectorstore = load_chromadb_collection(client=chroma_client) #persist path declared in docker file
    print(f"Vectorstore initialized as follows:\n{vectorstore}\n{type(vectorstore)}")

    #ingest documents in batches, defined by collector function
    #initialize document iterator and collect first batch of documents
    doc_iterator = loader.lazy_load()
    doc_collection = collector(doc_iterator, 4)

    #ingestion loop
    while doc_collection:
        logger.debug(f"number of documents collected: {len(doc_collection)}")
        #initialize chunk iterator and collect first batch of chunks
        chunk_iterator = lazy_chunker(doc_collection)
        chunk_collection = collector(chunk_iterator, 10)

        while chunk_collection:
            logger.debug(f"number of chunks collected: {len(chunk_collection)}")
            # print(chunk_collection)
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
    curr_files = json.load(open(Path("documents")/Path("files_read.json"), 'r')) if os.path.exists(Path("documents")/Path("files_read.json")) else []
    list_of_files = list_of_files + curr_files
    logger.debug(f"Files processed so far: {list_of_files}")
    json.dump(list_of_files, open(Path("documents")/Path("files_read.json"), 'w'))