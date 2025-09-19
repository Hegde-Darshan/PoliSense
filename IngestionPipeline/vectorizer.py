import os
from pathlib import Path

import chromadb
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma

import logging.config
from IngestionPipeline.logger import LOGGING_CONFIG

logging.config.dictConfig(LOGGING_CONFIG)
root_logger = logging.getLogger("ingestion_pipeline")
logger = root_logger.getChild("vectorizer")


def init_embeddings(model_name, **kwargs) -> HuggingFaceEmbeddings:
    """
    Initialize HuggingFaceEmbeddings with the specified model.
    Returns:
        An instance of HuggingFaceEmbeddings.
    """
    embeddings = HuggingFaceEmbeddings(
        model_name=model_name, 
        kwargs= kwargs
    )
    return embeddings


# Initialize chroma vector database locally
def init_chromadb(persist_path: str | None, collection: str = "PolisenseTest",
                  embedding_model_name:str = "BAAI/bge-small-en-v1.5") -> Chroma:
    """
    Initialize or load ChromaDB vector store from the given path.
    args:
        persist_path: Path to the directory where ChromaDB index is stored."""
    embedding_model = HuggingFaceEmbeddings(model_name=embedding_model_name)
    try:
        # Load existing Chroma index
        vector_index = Chroma(
            collection_name=collection,
            persist_directory=persist_path,
            embedding_function=embedding_model
        )
        logger.warning(f"Loading existing Chroma index from '{persist_path}'")
    except FileNotFoundError:
        # Create empty Chroma index (will be populated during ingestion)
        logger.warning(f"No existing Chroma index found at '{persist_path}'. "
              f"A new index will be created after ingestion.")
        vector_index = Chroma(
            collection_name='Polisense',
            persist_directory=persist_path,
            embedding_function=embedding_model
        )
    return vector_index


# load a chromadb collection given a chromadb client
def load_chromadb_collection(client:chromadb.ClientAPI, collection: str = "PolisenseTest",
                             embedding_model_name:str = "BAAI/bge-small-en-v1.5") -> Chroma | None:
    """
    Initialize or load ChromaDB vector store from the given path.
    args:
        persist_path: Path to the directory where ChromaDB index is stored."""
    embedding_model = HuggingFaceEmbeddings(model_name=embedding_model_name)
    try:
        # Load existing Chroma index
        vector_index = Chroma(
            client=client,
            collection_name=collection,
            embedding_function=embedding_model)
        logger.warning(f"returning collection '{collection}' if exists, else creating new one.")
        return vector_index
    except Exception as e:
        logger.error("could not return a collection. Problem with the client connection.")


# establish a https connection to the server
def chroma_server_connect(host:str= "localhost", port:int=8000) -> chromadb.ClientAPI | None:
    """
    Initialize a HTTP connection to the ChromaDB server

    Returns: None
    Runs a local chromadb server instead
    """
    try:
        client = chromadb.HttpClient(host=host, port=port)
        return client
    except Exception as e:
        logger.error(f"Failed to connect to ChromaDB server: {e}")


# # initialize FAISS vector store
# def initialize_faiss(persist_path: str) -> Chroma:
#     """
#     Initialize or load FAISS vector store from the given path.
#     args:
#         persist_path: Path to the directory where FAISS index is stored."""
#
#     try:
#         vector_index = FAISS.load_local(persist_path,
#                             HuggingFaceEmbeddings(model_name="BAAI/bge-small-en-v1.5"),
#                             allow_dangerous_deserialization=True)
#         print(f"Loading existing FAISS index from '{persist_path}'")
#     except FileNotFoundError:
#         print(f"No existing FAISS index found at '{persist_path}'. A new index will be created after ingestion.")
#         vector_index = FAISS(embedding_function=HuggingFaceEmbeddings(model_name="BAAI/bge-small-en-v1.5"),
#                             index=None,
#                             docstore=InMemoryDocstore(),
#                             index_to_docstore_id={})
#     return vector_index


# save FAISS vector store
# def save_vectorstore(vectorstore: FAISS, persist_path: str):
#     """
#     Save FAISS vector store to the given path.
#     args:
#         vectorstore: FAISS vector store to save.
#         persist_path: Path to the directory where FAISS index will be stored."""
#
#     vectorstore.save_local(persist_path)
#     print(f"FAISS index saved at '{persist_path}'")