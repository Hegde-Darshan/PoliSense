from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from pathlib import Path

ROOT_PATH = Path(__file__).parent
db = Chroma(
    persist_directory=str(ROOT_PATH / Path("vectorstore") / Path("chroma_index")),
    embedding_function=HuggingFaceEmbeddings(model_name="BAAI/bge-small-en-v1.5")
)
# db = initialize_chromadb(persist_path=str(ROOT_PATH / Path("vectorstore") / Path("chroma_index")))
count = db._collection.count()
print(f"Chroma DB has {count} documents")
results = db.similarity_search("what is markov chains", k=5)
print(results)
for r in results:
    print("Retrieved Text:", r.page_content[:200], "...")
    print("Metadata:", r.metadata)
    print("-" * 50)