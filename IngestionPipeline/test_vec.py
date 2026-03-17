# test_vector_diff.py — run standalone
from sentence_transformers import SentenceTransformer
import numpy as np

model = SentenceTransformer("BAAI/bge-small-en-v1.5")

# Use the actual documents from your debug output
doc1 = """Summary: The Karnataka Electric Vehicle & Energy Storage Policy 2017 aims to establish Karnataka as a premier destination for the manufacturing of Electric Vehicles (EVs) and their components.
Incentive: Incentives for EV Battery Manufacturing/Assembly Enterprises - Specific incentives for enterprises manufacturing or assembling EV batteries
Benefits: {"Investment Promotion Subsidy for MSMEs": "Micro: 25% of VFA (max Rs. 15 lakh)"}"""

doc2 = """Summary: The Karnataka Electric Vehicle & Energy Storage Policy 2017 aims to establish Karnataka as a premier destination for the manufacturing of Electric Vehicles (EVs) and their components.
Incentive: Incentives for EV Charging/Swapping Infrastructure Equipment Manufacturing - Incentives for enterprises manufacturing equipment for EV charging
Benefits: {"Capital Subsidy": "25% on equipment for charging stations"}"""

v1 = model.encode(doc1, normalize_embeddings=True)
v2 = model.encode(doc2, normalize_embeddings=True)

print(f"First 5 dims v1: {v1[:5]}")
print(f"First 5 dims v2: {v2[:5]}")
print(f"Last  5 dims v1: {v1[-5:]}")
print(f"Last  5 dims v2: {v2[-5:]}")
print(f"Vectors identical: {np.allclose(v1, v2)}")
print(f"Cosine similarity: {np.dot(v1, v2):.6f}")
print(f"Max diff at dim:   {np.argmax(np.abs(v1 - v2))}")
print(f"Max diff value:    {np.max(np.abs(v1 - v2)):.8f}")