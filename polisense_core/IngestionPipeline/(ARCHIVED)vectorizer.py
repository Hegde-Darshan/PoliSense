# import os
# from pathlib import Path

# import chromadb
# from chromadb.api import ClientAPI
# from langchain_huggingface import HuggingFaceEmbeddings
# from langchain_community.vectorstores import Chroma

# import logging.config
# from IngestionPipeline.logger import LOGGING_CONFIG

# logging.config.dictConfig(LOGGING_CONFIG)
# root_logger = logging.getLogger("ingestion_pipeline")
# logger = root_logger.getChild("vectorizer")


# def init_embeddings(model_name, **kwargs) -> HuggingFaceEmbeddings:
#     """
#     Initialize HuggingFaceEmbeddings with the specified model.
#     Returns:
#         An instance of HuggingFaceEmbeddings.
#     """
#     embeddings = HuggingFaceEmbeddings(
#         model_name=model_name, 
#         kwargs= kwargs
#     )
#     return embeddings


# # Initialize chroma vector database locally
# def init_chromadb(persist_path: str | None, collection: str = "PolisenseTest",
#                   embedding_model_name: str = "BAAI/bge-small-en-v1.5") -> Chroma:
#     """
#     Initialize or load ChromaDB vector store from the given path.
#     args:
#         persist_path: Path to the directory where ChromaDB index is stored.
#     """
#     if persist_path and Path(persist_path).exists():
#         logger.info(f"Loading existing Chroma index from '{persist_path}'")
#     else:
#         logger.info(f"Creating new Chroma index at '{persist_path}'")
        
#     embedding_model = HuggingFaceEmbeddings(model_name=embedding_model_name)
#     vector_index = Chroma(
#         collection_name=collection,
#         embedding_function=embedding_model)
#     logger.info(f"Chroma index initialized with collection '{collection}'")
#     logger.info(vector_index)
    
#     return vector_index


# # load a chromadb collection given a chromadb client
# def load_chromadb_collection(client, collection: str = "PolisenseTest",
#                              embedding_model_name:str = "BAAI/bge-small-en-v1.5") -> Chroma | None:
#     """
#     Initialize or load ChromaDB vector store from the given path.
#     args:
#         persist_path: Path to the directory where ChromaDB index is stored."""
#     embedding_model = HuggingFaceEmbeddings(model_name=embedding_model_name)
 
#     vector_index = Chroma(
#         client=client,
#         collection_name=collection,
#         embedding_function=embedding_model)
#     logger.warning(f"returning collection '{collection}' if exists, else creating new one.")
#     _ = vector_index._collection.count()  # Force initialization to check if collection exists
#     return vector_index


# # establish a https connection to the server
# def chroma_server_connect(host:str= "localhost", port:int=8000) -> ClientAPI:
#     """
#     Initialize a HTTP connection to the ChromaDB server

#     Returns: None
#     Runs a local chromadb server instead
#     """
#     client = chromadb.HttpClient(host=host, port=port)
#     client.heartbeat()
#     return client

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