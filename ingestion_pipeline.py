from pathlib import Path
import os
import json
from dotenv import load_dotenv
from typing import Callable, Iterator
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma

from langchain_text_splitters import CharacterTextSplitter, RecursiveCharacterTextSplitter
from langchain.schema import Document

from IngestionPipeline.data_loader import ChosenFilesDirectoryLoader, lazy_chunker
from IngestionPipeline.vectorizer import initialize_chromadb, save_vectorstore
from IngestionPipeline.utils import get_new_filenames


import logging
import logging.config
from IngestionPipeline.logger import LOGGING_CONFIG

logging.config.dictConfig(LOGGING_CONFIG)
root_logger = logging.getLogger()
logger = root_logger.getChild("ingestion_pipeline")

print(f"Logger name: {logger.name}\nLogger level: {logger.level}\nHandlers: {logger.handlers}\nlogger propagate: {logger.propagate}")


ROOT_PATH = Path(__file__).parent
print(f"Root path: {ROOT_PATH}")

try:
    load_dotenv(ROOT_PATH / ".env")
except Exception as e:
    logger.error(f"Error loading .env file: {e}")
    

def collector(iterator: Iterator, collect: int) -> list[Document] | None:
    """
    Collect a specified number of items from a generator function.
    Args:
        func: A generator function to collect items from.
        collect: The number of items to collect"""
    logger.debug(f"Collecting {collect} items from {iterator}")
    collection = []
    for _ in range(collect):
        try:
            collection.append(next(iterator))
        except StopIteration:
            break
    return collection if collection else None


if __name__ == "__main__":
    
    #get list of new files to ingest
    list_of_files = get_new_filenames(ROOT_PATH/Path("Data"), 
                        ROOT_PATH/Path("documents")/Path("files_read.json")
                    )
    logger.debug(f"List of new files to ingest: {list_of_files}")

    #initialize loader and vectorstore
    loader = ChosenFilesDirectoryLoader(ROOT_PATH/Path("Data"), list_of_files)
    vectorstore = initialize_chromadb(persist_path=str(ROOT_PATH / Path("vectorstore") / Path("chroma_index")))
    print("Vectorstore initialized")

    #ingest documents in batches, defined by collector function
    doc_iterator = loader.lazy_load()

    #initialize document iterator and collect first batch of documents
    doc_collection = collector(doc_iterator, 2)

    #ingestion loop
    while doc_collection:
        logger.debug(f"number of documents collected: {len(doc_collection)}")
        # print(f"number of documents collected: {len(doc_collection)}")
        #initialize chunk iterator and collect first batch of chunks
        chunk_iterator = lazy_chunker(doc_collection)
        chunk_collection = collector(chunk_iterator, 2)

        while chunk_collection:
            logger.debug(f"number of chunks collected: {len(chunk_collection)}")
            # print(chunk_collection)
            try:
                vectorstore.add_documents(chunk_collection)
                logger.debug(f"Chunks added to vectorstore")
            except Exception as e:
                logger.error(f"Error adding documents to vectorstore: {e}")

            #getting the next batch of chunks
            chunk_collection = collector(iterator=chunk_iterator, collect=10)

        #getting the next batch of documents
        doc_collection = collector(iterator=doc_iterator, collect=4)

    vectorstore.persist()

    #save files read
    curr_files = json.load(open(Path("documents")/Path("files_read.json"), 'r')) if os.path.exists(Path("documents")/Path("files_read.json")) else []
    list_of_files = list_of_files + curr_files
    logger.debug(f"Files processed so far: {list_of_files}")
    json.dump(list_of_files, open(Path("documents")/Path("files_read.json"), 'a'))
    

    db = Chroma(
        persist_directory="vectorstore/chroma_index",
        embedding_function=HuggingFaceEmbeddings(model_name="BAAI/bge-small-en-v1.5")
    )
    count = db._collection.count()