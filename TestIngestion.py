from langchain_huggingface import HuggingFaceEmbeddings
from pathlib import Path
from dotenv import load_dotenv
import chromadb
from langchain_chroma import Chroma
import os
ROOT_PATH = Path(__file__).parent

def get_chroma_client():
    """
    Connect to running Chroma server (Docker).
    """
    load_dotenv(ROOT_PATH / ".env")

    chroma_host = os.getenv("CHROMA_SERVER")
    chroma_port = os.getenv("CHROMA_PORT")

    if not chroma_host or not chroma_port:
        raise EnvironmentError("CHROMA_SERVER and CHROMA_PORT must be set")

    return chromadb.HttpClient(
        host=chroma_host,
        port=int(chroma_port)
    )

def get_chroma_vectorstore() -> Chroma:
    config = "PoliSenseDev_v2"
    client = get_chroma_client()
    embedding_fn = HuggingFaceEmbeddings(model_name="BAAI/bge-small-en-v1.5")

    return Chroma(
        client=client,
        collection_name=config,
        embedding_function=embedding_fn
    )

# 

# db = initialize_chromadb(persist_path=str(ROOT_PATH / Path("vectorstore") / Path("chroma_index")))
# count = db._collection.count()
# print(f"Chroma DB has {count} documents")

business = "Sakhi Handloom Collective,Textiles, Handloom, small, Karnataka,Women-Owned,Rural, SHG-based"

vectorstore = get_chroma_vectorstore()
print(f"Vectorstore has {vectorstore._collection.count()} vectors")

result = vectorstore.similarity_search(
        query=business,
        k=10
)

# results = db.similarity_search(business, k=5)
print(result)
for r in result:
    print("Retrieved Text:", r.page_content[:200], "...")
    print("Metadata:", r.metadata)
    print("-" * 50)