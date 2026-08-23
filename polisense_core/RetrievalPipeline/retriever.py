import os
from pathlib import Path
from typing import List, Dict

import yaml
from dotenv import load_dotenv

import chromadb
from langchain_chroma import Chroma
from langchain.schema import Document
from langchain_huggingface import HuggingFaceEmbeddings


ROOT_PATH = Path(__file__).parent.parent
EMBEDDING_MODEL_NAME = "BAAI/bge-small-en-v1.5"

def load_config() -> Dict:
    with open(ROOT_PATH / "config.yml", "r") as f:
        return yaml.safe_load(f)
    
def get_embedding_function():
    """
    Embedding function shared between ingestion & retrieval.
    """
    return HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL_NAME,
        encode_kwargs={"normalize_embeddings": True}
    )


def get_chroma_client() -> chromadb.Client:
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
    config = load_config()
    client = get_chroma_client()
    embedding_fn = get_embedding_function()

    return Chroma(
        client=client,
        collection_name=config["CHROMA_COLLECTION"],
        embedding_function=embedding_fn  # 🔥 REQUIRED FOR MMR
    )


def retrieve_documents(
    query: str,
    k: int = 5,
    metadata_filter: Dict | None = None,
    use_mmr: bool = False
) -> List[Document]:

    vectorstore = get_chroma_vectorstore()

    if use_mmr:
        return vectorstore.max_marginal_relevance_search(
            query=query,
            k=k,
            fetch_k=20,
            filter=metadata_filter
        )

    return vectorstore.similarity_search(
        query=query,
        k=k,
        filter=metadata_filter
    )
