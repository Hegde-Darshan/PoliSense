from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from pathlib import Path

ROOT_PATH = Path(__file__).resolve().parent.parent
VECTOR_DB_DIR = ROOT_PATH / "vectorstore/faiss_index"

db = FAISS.load_local(str(VECTOR_DB_DIR), HuggingFaceEmbeddings(model_name="BAAI/bge-small-en-v1.5"), allow_dangerous_deserialization=True)

retriever = db.as_retriever(
    search_type="similarity",
    search_kwargs={"k": 10, "filter": {"source": "MLOPS Interview Questions.pdf"}}
)

# Retrieve
results = retriever.get_relevant_documents("Kubernetes for containarization")
# print(results)
for r in results:
    print("Retrieved Text:", r.page_content[:200], "...")
    print("Metadata:", r.metadata)