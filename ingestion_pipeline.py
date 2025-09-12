from pathlib import Path
import os
from typing import Callable, Iterator

from langchain_text_splitters import CharacterTextSplitter, RecursiveCharacterTextSplitter
from langchain.schema import Document

from IngestionPipeline.data_loader import ChosenFilesDirectoryLoader, lazy_chunker
from IngestionPipeline.vectorizer import initialize_faiss
from IngestionPipeline.utils import get_new_filenames


import logging
import logging.config
from IngestionPipeline.logger import LOGGING_CONFIG

logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger("ingestion_pipeline")


ROOT_PATH = Path(__file__).parent
print(f"Root path: {ROOT_PATH}")



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
    vectorstore = initialize_faiss(persist_path=str(ROOT_PATH / Path("vectorstore") / Path("faiss_index")))
    logger.debug(f"Initial vectorstore document count: {len(vectorstore.index_to_docstore_id)}")

    #ingest documents in batches, defined by collector function
    doc_iterator = loader.lazy_load()
    #initialize document iterator and collect first batch of documents
    doc_collection = collector(doc_iterator, 4)

    #ingestion loop
    while doc_collection:
        logger.debug(f"number of documents collected: {len(doc_collection)}")
        #initialize chunk iterator and collect first batch of chunks
        chunk_iterator = lazy_chunker(doc_collection)
        chunk_collection = collector(chunk_iterator, 10)

        while chunk_collection:
            logger.debug(f"number of chunks collected: {len(chunk_collection)}")
            vectorstore.add_documents(chunk_collection)
            logger.debug(f"Chunks added to vectorstore. Current total documents: {len(vectorstore.index_to_docstore_id)}")

            #getting the next batch of chunks
            chunk_collection = collector(iterator=chunk_iterator, collect=10)

        #getting the next batch of documents
        doc_collection = collector(iterator=doc_iterator, collect=4)


