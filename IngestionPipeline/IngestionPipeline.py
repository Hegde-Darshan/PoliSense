import os
from langchain_community.document_loaders import PyPDFLoader
from langchain.text_splitter import CharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS


# Step 1: Load all PDF documents from a given folder
def load_pdfs_from_folder(folder_path: str):
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
def chunk_documents(documents):
    text_splitter = CharacterTextSplitter(
        separator="\n",
        chunk_size=1000,
        chunk_overlap=200,
        length_function=len
    )

    chunks = text_splitter.split_documents(documents)

    # Add chunk_id for traceability
    for i, chunk in enumerate(chunks):
        chunk.metadata["chunk_id"] = i

    return chunks


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
def ingest_pdfs(folder_path: str, persist_path="faiss_index"):
    documents = load_pdfs_from_folder(folder_path)
    chunks = chunk_documents(documents)
    vectorstore = create_vectorstore(chunks, persist_path)
    print(f"Ingestion complete. FAISS index saved at '{persist_path}'")
    return vectorstore


# Example usage:
if __name__ == "__main__":
    pdf_folder = "data"  # your folder with PDFs
    ingest_pdfs(pdf_folder, persist_path="vectorstore/faiss_index")
