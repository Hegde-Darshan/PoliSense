# import os
# from langchain_community.document_loaders import PyPDFLoader, DirectoryLoader
# from langchain.text_splitter import CharacterTextSplitter
# from langchain_huggingface import HuggingFaceEmbeddings
# from langchain_community.vectorstores import Chroma
# from langchain.schema import Document
#
# from pathlib import Path
# from dotenv import load_dotenv
# from IngestionPipeline.utils import get_new_filenames
#
# import logging
# import logging.config
# from logger import LOGGING_CONFIG
#
# logging.config.dictConfig(LOGGING_CONFIG)
# logger = logging.getLogger("ingestion_pipeline")
#
#
# ROOT_PATH = Path(__file__).parent.parent
# print(f"Root path: {ROOT_PATH}")
#
#
# # Load environment variables from .env file
# try:
#     load_dotenv(ROOT_PATH / Path('.env'), verbose=True)
# except FileNotFoundError:
#     print("No .env file found. Proceeding without loading environment variables.")
#
#
# # Step 1: Load all PDF documents from a given folder
# def load_pdfs_from_folder(folder_path: Path, file_to_read: list) -> list[Document]:
#     documents = []
#     for file_name in os.listdir(folder_path):
#         if file_name.endswith(".pdf"):
#             file_path = os.path.join(folder_path, file_name)
#             loader = PyPDFLoader(file_path)
#
#             loaders = DirectoryLoader(file_path, )
#             docs = loader.load()
#
#             # Add file name to metadata
#             for d in docs:
#                 d.metadata["source"] = file_name
#             documents.extend(docs)
#     return documents
#
#
# # Step 2: Chunk the text with metadata
# def chunk_documents(document):
#     text_splitter = CharacterTextSplitter(
#         separator="\n",
#         chunk_size=1000,
#         chunk_overlap=200,
#         length_function=len
#     )
#
#     chunks = text_splitter.split_documents(document)
#
#     # Add chunk_id for traceability
#     for i, chunk in enumerate(chunks):
#         chunk.metadata["chunk_id"] = i
#
#     return chunks
#
# # Initialize chroma db vector store
# def initialize_chroma(persist_path: str = str(ROOT_PATH / "vectorstore" / "chroma_index")):
#     """
#     Initialize or load Chroma vector store from the given path.
#
#     Args:
#         persist_path: Path to the directory where Chroma index is stored.
#     """
#     embedding_model = HuggingFaceEmbeddings(model_name="BAAI/bge-small-en-v1.5")
#
#     if os.path.exists(persist_path) and os.listdir(persist_path):
#         print(f"Loading existing Chroma index from '{persist_path}'")
#         db = Chroma(
#             persist_directory=persist_path,
#             embedding_function=embedding_model
#         )
#     else:
#         print(f"No existing Chroma index found at '{persist_path}'. "
#               f"A new index will be created after ingestion.")
#         db = None
#
#     return db
#
#
# # Step 3: Create Chroma DB vector store
# def create_vectorstore(chunks, persist_path="chroma_index"):
#     """
#     Create a Chroma vector store from document chunks and persist it.
#
#     Args:
#         chunks: List of Document objects (from LangChain text splitter, etc.)
#         persist_path: Directory where the Chroma DB will be stored.
#     """
#     embeddings = HuggingFaceEmbeddings(model_name="BAAI/bge-small-en-v1.5")
#
#     # Create Chroma vector store
#     vectorstore = Chroma.from_documents(
#         documents=chunks,
#         embedding=embeddings,
#         persist_directory=persist_path
#     )
#
#     # Persist the Chroma index to disk
#     vectorstore.persist()
#
#     return vectorstore
#
#
#
# # Step 4: Full ingestion pipeline
# def ingest_pdfs(folder_path: Path, persist_path="chroma_index"):
#     documents = load_pdfs_from_folder(folder_path, [])
#     chunks = chunk_documents(documents)
#     vectorstore = create_vectorstore(chunks, persist_path)
#     print(f"Ingestion complete. ChromaDB index saved at '{persist_path}'")
#     return vectorstore
#
#
# # Example usage:
# if __name__ == "__main__":
#     pdf_folder = ROOT_PATH / Path("Data") # your folder with PDFs
#
#     #get new files to ingest
#
#     # prepare document generator and chunking pipeline
#     processed_files = ROOT_PATH / Path("processed_files.json")
#     new_files = get_new_filenames(pdf_folder, processed_files)
#     print(f"New files to ingest: {new_files}")
#
#     if new_files:
#         print("Starting ingestion of new PDF files...")
#
#         for file_name in new_files:
#             file_path = pdf_folder / Path(file_name)
#             ingest_pdfs(file_path, persist_path="vectorstore/chroma_index")
#
#     ingest_pdfs(pdf_folder, persist_path="vectorstore/chroma_index")
