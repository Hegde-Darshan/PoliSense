from typing import List, Dict, Any
import json
from math import sqrt

from langchain.retrievers import BaseRetriever, ParentDocumentRetriever
from langchain_community.vectorstores import Chroma


def get_query():
    return "sample query"


def load_documents(file_path: str) -> List[Dict[str, Any]]:
    """Load documents from a JSON file."""
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)
    

def split_into_chunks(text: str, chunk_size: int = 512, overlap: int = 50) -> List[str]:
    """Split text into overlapping chunks."""
    chunks = []
    for i in range(0, len(text), chunk_size - overlap):
        chunks.append(text[i:i + chunk_size])
    return chunks


def preprocess_text(text: str) -> str:
    """Preprocess text: lowercase, remove extra whitespace."""
    text = text.lower().strip()
    text = ' '.join(text.split())
    return text