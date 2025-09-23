import os
from pathlib import Path

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_chroma import Chroma
from langchain_community.docstore.in_memory import InMemoryDocstore
from langchain.schema import Document

import logging
import logging.config
from IngestionPipeline.logger import LOGGING_CONFIG

logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger("vectorizer")



def initialize_embeddings(model_name, **kwargs) -> HuggingFaceEmbeddings:
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

# Initialize chroma vectorstore
def initialize_chromadb(persist_path: str) -> Chroma:
    """
    Initialize or load ChromaDB vector store from the given path.
    args:
        persist_path: Path to the directory where ChromaDB index is stored."""
    embedding_model = HuggingFaceEmbeddings(model_name="BAAI/bge-small-en-v1.5")
    try:
        # Load existing Chroma index
        vector_index = Chroma(
            collection_name="Polisense",
            persist_directory=persist_path,
            embedding_function=embedding_model
        )
        print(f"Loading existing Chroma index from '{persist_path}'")
    except FileNotFoundError:
        # Create empty Chroma index (will be populated during ingestion)
        print(f"No existing Chroma index found at '{persist_path}'. "
              f"A new index will be created after ingestion.")
        vector_index = Chroma(
            collection_name="Polisense",
            persist_directory=persist_path,
            embedding_function=embedding_model
        )
    return vector_index


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

# save Chroma vector store
def save_vectorstore(vectorstore: Chroma, persist_path: str):
    """
    Save Chroma vector store to the given path.
    args:
        vectorstore: Chroma vector store to save.
        persist_path: Path to the directory where Chroma index will be stored."""

    vectorstore.persist()
    print(f"Chroma index saved at '{persist_path}'")

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