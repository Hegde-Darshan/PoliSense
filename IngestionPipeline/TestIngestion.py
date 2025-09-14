from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS

db = FAISS.load_local("vectorstore/faiss_index", HuggingFaceEmbeddings(model_name="BAAI/bge-small-en-v1.5"), allow_dangerous_deserialization=True)

results = db.similarity_search("What is a markov chain", k=5)
# print(results)
for r in results:
    print("Retrieved Text:", r.page_content[:200], "...")
    print("Metadata:", r.metadata)
    print("-" * 50)