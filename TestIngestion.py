from langchain_huggingface import HuggingFaceEmbeddings
from pathlib import Path
from dotenv import load_dotenv
import chromadb
from langchain_chroma import Chroma
import os
import yaml
ROOT_PATH = Path(__file__).parent

# Load config file
with open(ROOT_PATH / "config.yml", 'r') as config_file:
    config = yaml.safe_load(config_file)

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
    collection_name = config['TEST_CHROMA_COLLECTION']
    client = get_chroma_client()
    embedding_fn = HuggingFaceEmbeddings(model_name="BAAI/bge-small-en-v1.5")

    return Chroma(
        client=client,
        collection_name=collection_name,
        embedding_function=embedding_fn
    )

# 

# db = initialize_chromadb(persist_path=str(ROOT_PATH / Path("vectorstore") / Path("chroma_index")))
# count = db._collection.count()
# print(f"Chroma DB has {count} documents")

# business = "Sakhi Handloom Collective,Textiles, Handloom, small, Karnataka,Women-Owned,Rural, SHG-based"
business1 = """{
  "business_name": "InnoHer Solutions Pvt Ltd",
  "legal_entity_type": "Private Limited",
  "industry": "Technology",
  "sub_industry": "HealthTech",
  "employee_count": 15,
  "turnover_range": "INR 1–2 Cr",
  "year_of_establishment": 2022,
  "geography": {
    "country": "India",
    "state": "Karnataka",
    "district": "Bangalore"
  },
  "ownership_type": "Women-Owned",
  "registration": {
    "msme": true,
    "udyam_number": "KA2022HT1234"
  },
  "growth_stage": "Startup",
  "special_attributes": ["Startup", "Women-led", "Innovative"]
}"""

business2 = """{
  "business_name": "IdeaSpark Innovations Pvt Ltd",
  "legal_entity_type": "Private Limited",
  "industry": "Technology",
  "sub_industry": "AI & Machine Learning",
  "employee_count": 18,
  "turnover_range": "INR 1–2 Cr",
  "year_of_establishment": 2022,
  "geography": {
    "country": "India",
    "state": "Telangana",
    "district": "Hyderabad"
  },
  "ownership_type": "Private",
  "registration": {
    "msme": true,
    "udyam_number": "TS2022AI1234"
  },
  "growth_stage": "Early Stage",
  "special_attributes": ["Startup", "Tech-enabled", "Youth-led"]
}"""

# Test the ChromaDB collection
vectorstore = get_chroma_vectorstore()
collection_count = vectorstore._collection.count()
print(f"=" * 70)
print(f"Collection: {config['TEST_CHROMA_COLLECTION']}")
print(f"Total vectors in collection: {collection_count}")
print(f"=" * 70)

if collection_count == 0:
    print("⚠️  WARNING: Collection is empty! Make sure you've run ingestion_pipeline.py")
    exit(1)

# Get a few sample documents to inspect metadata structure
print("\n" + "=" * 70)
print("SAMPLE DOCUMENTS (First 3):")
print("=" * 70)
sample_docs = vectorstore.similarity_search(query="scheme", k=3)
for i, doc in enumerate(sample_docs, 1):
    print(f"\n--- Document {i} ---")
    print(f"Content preview: {doc.page_content[:1500]}...")
    print(f"Metadata keys: {list(doc.metadata.keys())}")
    print(f"Full metadata:")
    for key, value in doc.metadata.items():
        print(f"  {key}: {value}")

# Test similarity search with business profiles
print("\n" + "=" * 70)
print("SIMILARITY SEARCH TEST 1: Women-Owned Startup in Karnataka")
print("=" * 70)
result1 = vectorstore.similarity_search(query="Women-Owned Startup in Karnataka", k=5, filter={"keyword"})
print(f"Found {len(result1)} results\n")
for i, r in enumerate(result1, 1):
    print(f"Result {i}:")
    print(f"  Text: {r.page_content[:500]}...")
    print(f"  Metadata: scheme_name={r.metadata.get('scheme_name', 'N/A')}, "
          f"category={r.metadata.get('category', 'N/A')}, "
          f"geography={r.metadata.get('geography', 'N/A')}")
    print("-" * 50)

print("\n" + "=" * 70)
print("SIMILARITY SEARCH TEST 2: Tech Startup")
print("=" * 70)
result2 = vectorstore.similarity_search(query=business2, k=5)
print(f"Found {len(result2)} results\n")
for i, r in enumerate(result2, 1):
    print(f"Result {i}:")
    print(f"  Text: {r.page_content[:500]}...")
    print(f"  Metadata: scheme_name={r.metadata.get('scheme_name', 'N/A')}, "
          f"category={r.metadata.get('category', 'N/A')}, "
          f"geography={r.metadata.get('geography', 'N/A')}")
    print("-" * 50)

# Test metadata filtering (if supported)
print("\n" + "=" * 70)
print("METADATA SUMMARY:")
print("=" * 70)
all_docs = vectorstore.similarity_search(query="", k=min(100, collection_count))
unique_schemes = set()
unique_categories = set()
unique_geographies = set()
for doc in all_docs:
    if 'scheme_name' in doc.metadata and doc.metadata['scheme_name']:
        unique_schemes.add(doc.metadata['scheme_name'])
    if 'category' in doc.metadata and doc.metadata['category']:
        unique_categories.add(doc.metadata['category'])
    if 'geography' in doc.metadata:
        geo = doc.metadata['geography']
        if isinstance(geo, list):
            unique_geographies.update(geo)
        elif geo:
            unique_geographies.add(geo)

print(f"Unique schemes found: {len(unique_schemes)}")
print(f"Unique categories: {sorted(unique_categories)}")
print(f"Unique geographies: {sorted(unique_geographies)}")
print(f"\n✅ Collection test completed successfully!")