import os
from pathlib import Path

from langchain.text_splitter import CharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain.schema import Document

import logging
import logging.config
from logger import LOGGING_CONFIG

logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger("vectorizer")



# initialize FAISS vector store
def initialize_faiss(persist_path: str ) -> FAISS:
    """
    Initialize or load FAISS vector store from the given path.
    args:
        persist_path: Path to the directory where FAISS index is stored."""
    
    if os.path.exists(persist_path):
        print(f"Loading existing FAISS index from '{persist_path}'")
        vector_index = FAISS.load_local(persist_path, HuggingFaceEmbeddings(model_name="BAAI/bge-small-en-v1.5"), allow_dangerous_deserialization=True)
    else:
        raise FileNotFoundError(f"FAISS index not found at '{persist_path}'. Please create the index before loading.")
    return vector_index


# Step 3: Create FAISS vector store
def create_vectorstore(chunks, persist_path="faiss_index"):
    embeddings = HuggingFaceEmbeddings(
        model_name="BAAI/bge-small-en-v1.5"
    )
    vectorstore = FAISS.from_documents(documents=chunks, embedding=embeddings)

    # save FAISS index
    vectorstore.save_local(persist_path)
    return vectorstore