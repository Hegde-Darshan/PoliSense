import os
from pathlib import Path
from typing import List, Dict

import yaml
from dotenv import load_dotenv

from langchain_community.vectorstores import Chroma
from langchain.schema import Document


ROOT_PATH = Path(__file__).parent.parent


def load_config() -> Dict:
    with open(ROOT_PATH / "config.yml", "r") as f:
        return yaml.safe_load(f)


def get_chroma_vectorstore() -> Chroma:
    load_dotenv(ROOT_PATH / ".env")
    config = load_config()

    chroma_host = os.getenv("CHROMA_SERVER")
    chroma_port = os.getenv("CHROMA_PORT")

    if not chroma_host or not chroma_port:
        raise EnvironmentError("CHROMA_SERVER and CHROMA_PORT must be set")

    return Chroma(
        collection_name=config["CHROMA_COLLECTION"],
        client_settings={
            "chroma_server_host": chroma_host,
            "chroma_server_http_port": int(chroma_port)
        }
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
