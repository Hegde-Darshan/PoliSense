from typing import List, Dict, Any

from polisense_core.RetrievalPipeline.preprocessor import preprocess_query, build_metadata_filter, build_chroma_where_filter
from polisense_core.RetrievalPipeline.retriever import retrieve_documents


def retrieval_pipeline(
    query: str,
    client_profile: Dict | None = None,
    top_k: int = 5
) -> List[Dict[str, Any]]:

    clean_query = preprocess_query(query)
    # metadata_filter = build_metadata_filter(client_profile)
    metadata_filter = build_chroma_where_filter(client_profile)

    docs = retrieve_documents(
        query=clean_query,
        k=top_k,
        metadata_filter=metadata_filter,
        use_mmr=False
    )

    return [
        {
            "content": doc.page_content,
            "metadata": doc.metadata
        }
        for doc in docs
    ]




if __name__ == "__main__":

    query = "government schemes for women startups"

    client_profile_1 = {
    "special_attribute": "Women",
    "business_size": "Startup",
    "state":"Karnataka",
    "central":"True"
}

    client_profile_2 = {
        "special_attribute": "Entrepreneurship",
        "business_size": "Startup",
        "state":"Karnataka",
        "central":"True"
    }

    results = retrieval_pipeline(
        query=query,
        client_profile=client_profile_1,
        top_k=5
    )

    for i, r in enumerate(results, 1):
        print(f"\nResult {i}")
        print("-" * 40)
        print(r["content"][:500])
        print("Metadata:", r["metadata"])
