import os
from langchain_community.document_loaders import PyPDFLoader
from langchain.text_splitter import CharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS

from pathlib import Path
from dotenv import load_dotenv


ROOT_PATH = Path(__file__).parent.parent
print(f"Root path: {ROOT_PATH}")

try:
    load_dotenv(ROOT_PATH / Path('.env'))
except FileNotFoundError:
    print("No .env file found. Proceeding without loading environment variables.")


# Step 1: Load all PDF documents from a given folder
def load_pdfs_from_folder(folder_path: Path):
    documents = []
    for file_name in os.listdir(folder_path):
        if file_name.endswith(".pdf"):
            file_path = os.path.join(folder_path, file_name)
            loader = PyPDFLoader(file_path)
            docs = loader.load()

            # Add file name to metadata
            for d in docs:
                d.metadata["source"] = file_name
            documents.extend(docs)
    return documents


# Step 2: Chunk the text with metadata
def chunk_documents(document):
    text_splitter = CharacterTextSplitter(
        separator="\n",
        chunk_size=1000,
        chunk_overlap=200,
        length_function=len
    )

    chunks = text_splitter.split_documents(document)

    # Add chunk_id for traceability
    for i, chunk in enumerate(chunks):
        chunk.metadata["chunk_id"] = i

    return chunks

# initialize FAISS vector store
def initialize_faiss(persist_path: str = str(ROOT_PATH / Path("vectorstore") / Path("faiss_index"))):
    """
    Initialize or load FAISS vector store from the given path.
    args:
        persist_path: Path to the directory where FAISS index is stored."""
    
    if os.path.exists(persist_path):
        print(f"Loading existing FAISS index from '{persist_path}'")
        db = FAISS.load_local(persist_path, HuggingFaceEmbeddings(model_name="BAAI/bge-small-en-v1.5"), allow_dangerous_deserialization=True)
    else:
        print(f"No existing FAISS index found at '{persist_path}'. A new index will be created after ingestion.")
        db = None
    return db

# Step 3: Create FAISS vector store
def create_vectorstore(chunks, persist_path="faiss_index"):
    embeddings = HuggingFaceEmbeddings(
        model_name="BAAI/bge-small-en-v1.5"
    )
    vectorstore = FAISS.from_documents(documents=chunks, embedding=embeddings)

    # save FAISS index
    vectorstore.save_local(persist_path)
    return vectorstore


# Step 4: Full ingestion pipeline
def ingest_pdfs(folder_path: Path, persist_path="faiss_index"):
    documents = load_pdfs_from_folder(folder_path)
    chunks = chunk_documents(documents)
    vectorstore = create_vectorstore(chunks, persist_path)
    print(f"Ingestion complete. FAISS index saved at '{persist_path}'")
    return vectorstore


# Example usage:
if __name__ == "__main__":
    pdf_folder = ROOT_PATH/Path("IngestionPipeline.py")/Path("Data") # your folder with PDFs
    ingest_pdfs(pdf_folder, persist_path="vectorstore/faiss_index")
