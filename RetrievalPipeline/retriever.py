from typing import List, Dict, Any
import json
from math import sqrt

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

def retrieve_by_keyword(documents: List[Dict], query: str, top_k: int = 5) -> List[Dict]:
    """Retrieve documents matching query keywords."""
    query_terms = set(query.lower().split())
    scored_docs = []
    
    for doc in documents:
        content = doc.get('content', '').lower()
        score = sum(1 for term in query_terms if term in content)
        if score > 0:
            scored_docs.append((doc, score))
    
    return [doc for doc, _ in sorted(scored_docs, key=lambda x: x[1], reverse=True)][:top_k]

def retrieve_by_semantic_similarity(embeddings: List[List[float]], query_embedding: List[float], top_k: int = 5) -> List[int]:
    """Retrieve documents by cosine similarity."""
    
    def cosine_similarity(a, b):
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sqrt(sum(x**2 for x in a))
        norm_b = sqrt(sum(x**2 for x in b))
        return dot / (norm_a * norm_b) if norm_a and norm_b else 0
    
    scores = [(i, cosine_similarity(query_embedding, emb)) for i, emb in enumerate(embeddings)]
    return [i for i, _ in sorted(scores, key=lambda x: x[1], reverse=True)][:top_k]

def rerank_results(documents: List[Dict], query: str) -> List[Dict]:
    """Rerank retrieval results by relevance score."""
    for doc in documents:
        doc['relevance_score'] = len([w for w in query.split() if w.lower() in doc.get('content', '').lower()])
    return sorted(documents, key=lambda x: x.get('relevance_score', 0), reverse=True)