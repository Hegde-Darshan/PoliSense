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

filter1 = {
        "industry": ["Technology","IT"],
        "business_size": ["startup"],
        "year": ["2022"],
        "geography": ["Karnataka","India"],
        "keywords": ["Women-Owned","msme"],
        "special_attribute":["Women","Innovative"]
    }


business2 = """{
  "business_name": "IdeaSpark Innovations Pvt Ltd",
  "legal_entity_type": "Private Limited",
  "industry": "Technology",
  "sub_industry": "AI & Machine Learning",
  "employee_count": 18,
  "turnover_range": "INR 1–2 Cr",
  "year_of_establishment": 2024,
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

filter2 = {
        "industry": ["Technology","IT"],
        "business_size": ["startup"],
        "year": ["2024"],
        "geography": ["Telangana","India"],
        "keywords": ["msme", "AI & Machine Learning"],
        "special_attribute":["youth","Innovative"]
    }

filterw = {
    "special_attribute": "Women",
    "business_size": "Startup",
    "state":"Karnataka",
    "central":"True"
}

filters = {
    "special_attribute": "Entrepreneurship",
    "business_size": "Startup",
    "state":"Karnataka",
    "central":"True"
}


def build_chroma_where_filter(filters: dict) -> dict:
    """
    Convert flat metadata filters into a Chroma-compatible where clause.
    """
    clauses = []

    for key, values in filters.items():
        if not values:
            continue

        # Normalize single value → list
        if not isinstance(values, list):
            values = [values]

        clauses.append({
            key: {"$in": values}
        })

    if not clauses:
        return {}

    if len(clauses) == 1:
        return clauses[0]

    return {"$or": clauses}

where1 = build_chroma_where_filter(filter1)
# where1 = {"$contains":[{
#         "industry": ["Technology","IT"],
#         "business_size": ["startup"],
#         "year": ["2022"],
#         "geography": ["Karnataka","India"],
#         "keywords": ["Women-Owned","msme"],
#         "special_attribute":["Women","Innovative"]
#         }]
#     }
# print("-----",where1)
where2 = build_chroma_where_filter(filter2)
# print("*****",where2)
wherew = build_chroma_where_filter(filterw)
print(wherew)
wheres = build_chroma_where_filter(filters)
print(wheres)
# Test the ChromaDB collection
vectorstore = get_chroma_vectorstore()

collection_count = vectorstore._collection.count()
collection = vectorstore._chroma_collection
embedding_fn = HuggingFaceEmbeddings(
    model_name="BAAI/bge-small-en-v1.5"
)

query_embedding = embedding_fn.embed_query("schemes")

res = collection.query(
    query_embeddings=[query_embedding],
    where={
        "$or": [
            {"business_size": "Startup"},
            {"special_attribute": "Women"},
            {"state":"Karnataka"},
            {"central":"True"}
        ]
    },
    n_results=10
)
rm = res['metadatas'][0]
# print(res['metadatas'][0])
r_schemes = set()
r_documents = set()
r_business_size=set()
for r in rm:
    # print(r[0])
    # break
    if 'scheme_name' in r and r['scheme_name']:
        r_schemes.add(r['scheme_name'])
    # if 'document_type' in r.metad and r.metadata['document_type']:
    #     r_documents.add(r.metadata['document_type'])
    # if 'business_size' in r.metadata and r.metadata['business_size']:
    #     r_business_size.add(r.metadata['business_size'])

print(f"Found {len(r_schemes)} results\n")
for i, r in enumerate(r_schemes, 1):
    print(f"  Metadata: scheme_name={r}, ")

# print(collection.query("startup"))

# res = collection.query(query_texts=[""], n_results=5, 
#     where= {
#         "business_size": "startup"
#     })
# print(res)
print(f"=" * 70)
print(f"Collection: {config['TEST_CHROMA_COLLECTION']}")
print(f"Total vectors in collection: {collection_count}")
print(f"=" * 70)

# if collection_count == 0:
#     print("⚠️  WARNING: Collection is empty! Make sure you've run ingestion_pipeline.py")
#     exit(1)

# # Get a few sample documents to inspect metadata structure
# print("\n" + "=" * 70)
# print("SAMPLE DOCUMENTS (First 3):")
# print("=" * 70)
# sample_docs = vectorstore.similarity_search(query="scheme", k=3)
# for i, doc in enumerate(sample_docs, 1):
#     print(f"\n--- Document {i} ---")
#     print(f"Content preview: {doc.page_content[:1500]}...")
#     print(f"Metadata keys: {list(doc.metadata.keys())}")
#     print(f"Full metadata:")
#     for key, value in doc.metadata.items():
#         print(f"  {key}: {value}")

# Test similarity search with business profiles
print("\n" + "=" * 70)
print("SIMILARITY SEARCH TEST 1: Women-Owned Startup in Karnataka")
print("=" * 70)
all_docs = vectorstore.similarity_search(query="schemes", k=25, filter=wherew)
unique_schemes = set()
unique_documents = set()
unique_business_size=set()
for doc in all_docs:
    if 'scheme_name' in doc.metadata and doc.metadata['scheme_name']:
        unique_schemes.add(doc.metadata['scheme_name'])
    if 'document_type' in doc.metadata and doc.metadata['document_type']:
        unique_documents.add(doc.metadata['document_type'])
    if 'business_size' in doc.metadata and doc.metadata['business_size']:
        unique_business_size.add(doc.metadata['business_size'])

print(f"Found {len(unique_schemes)} results\n")
for i, r in enumerate(unique_schemes, 1):
    print(f"  Metadata: scheme_name={r}, ")

print("\n" + "=" * 70)
print("SIMILARITY SEARCH TEST 2: Tech Startup")
print("=" * 70)
all_docs = vectorstore.similarity_search(query="schemes", k=25, filter=wheres)

# print(f"Found {len(result2)} results\n")
# for i, r in enumerate(result2, 1):
#     print(f"Result {i}:")
#     print(f"  Text: {r.page_content[:500]}...")
#     print(f"  Metadata: scheme_name={r.metadata.get('scheme_name', 'N/A')}, "
#           f"category={r.metadata.get('category', 'N/A')}, "
#           f"geography={r.metadata.get('geography', 'N/A')}")
#     print("-" * 50)
unique_schemes = set()
unique_documents = set()
unique_business_size=set()
for doc in all_docs:
    if 'scheme_name' in doc.metadata and doc.metadata['scheme_name']:
        unique_schemes.add(doc.metadata['scheme_name'])
    if 'document_type' in doc.metadata and doc.metadata['document_type']:
        unique_documents.add(doc.metadata['document_type'])
    if 'business_size' in doc.metadata and doc.metadata['business_size']:
        unique_business_size.add(doc.metadata['business_size'])

print(f"Found {len(unique_schemes)} results\n")
for i, r in enumerate(unique_schemes, 1):
    print(f"  Metadata: scheme_name={r}, ")


# Test metadata filtering (if supported)
# print("\n" + "=" * 70)
# print("METADATA SUMMARY:")
# print("=" * 70)
# all_docs = vectorstore.similarity_search(query="", k=min(100, collection_count))

# unique_schemes = set()
# unique_categories = set()
# unique_geographies = set()
# for doc in all_docs:
#     if 'scheme_name' in doc.metadata and doc.metadata['scheme_name']:
#         unique_schemes.add(doc.metadata['scheme_name'])
#     if 'category' in doc.metadata and doc.metadata['category']:
#         unique_categories.add(doc.metadata['category'])
#     if 'geography' in doc.metadata:
#         geo = doc.metadata['geography']
#         if isinstance(geo, list):
#             unique_geographies.update(geo)
#         elif geo:
#             unique_geographies.add(geo)
# print("MEtaaaaaa",doc.metadata)
# print(f"Unique schemes found: {len(unique_schemes)}")
# print(f"Unique categories: {sorted(unique_categories)}")
# print(f"Unique geographies: {sorted(unique_geographies)}")
# print(f"\n✅ Collection test completed successfully!")