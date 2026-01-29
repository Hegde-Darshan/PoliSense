from langchain.retrievers.self_query.base import SelfQueryRetriever
from langchain.chains.query_constructor.schema import AttributeInfo
from langchain_openai import ChatOpenAI
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
import chromadb
import os
from pathlib import Path
from typing import List, Dict

import yaml
from dotenv import load_dotenv
ROOT_PATH = Path(__file__).parent
load_dotenv(ROOT_PATH / ".env", override=True)

EMBEDDING_MODEL_NAME = "BAAI/bge-small-en-v1.5"


def load_config() -> Dict:
    with open(ROOT_PATH / "config.yml", "r") as f:
        return yaml.safe_load(f)

def get_embedding_function():
    """
    Embedding function shared between ingestion & retrieval.
    """
    return HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL_NAME,
        encode_kwargs={"normalize_embeddings": True}
    )

def get_chroma_client() -> chromadb.Client:
    """
    Connect to running Chroma server (Docker).
    """
    

    chroma_host = os.getenv("CHROMA_SERVER")
    chroma_port = os.getenv("CHROMA_PORT")

    if not chroma_host or not chroma_port:
        raise EnvironmentError("CHROMA_SERVER and CHROMA_PORT must be set")

    return chromadb.HttpClient(
        host=chroma_host,
        port=int(chroma_port)
    )

def get_chroma_vectorstore() -> Chroma:
    config = load_config()
    client = get_chroma_client()
    embedding_fn = get_embedding_function()

    return Chroma(
        client=client,
        collection_name=config["TEST_CHROMA_COLLECTION"],
        embedding_function=embedding_fn  # 🔥 REQUIRED FOR MMR
    )

metadata_field_info = [
    AttributeInfo(
        name="scheme_name",
        description="Name of the government scheme",
        type="string",
    ),
    AttributeInfo(
        name="category",
        description="Category of the scheme such as subsidy, grant, loan, tax benefit",
        type="string",
    ),
    AttributeInfo(
        name="industry",
        description="Industries eligible for the scheme",
        type="string",
    ),
    AttributeInfo(
        name="business_size",
        description="Business size such as startup, MSME, small, medium, large",
        type="string",
    ),
    AttributeInfo(
        name="year",
        description="Applicable years or year of launch",
        type="integer",
    ),
    AttributeInfo(
        name="geography",
        description="Geographic eligibility such as country, state, or district",
        type="string",
    ),
    AttributeInfo(
        name="document_type",
        description="Type of document like policy, notification, guideline",
        type="string",
    ),
    AttributeInfo(
        name="keywords",
        description="Keywords related to scheme eligibility or benefits",
        type="string",
    ),
    AttributeInfo(
        name="special_attribute",
        description="Special eligibility such as women-led, startup, SC/ST, minority",
        type="string",
    ),
]
openai_api_key = os.getenv("OPENAI_API_KEY")
# print(openai_api_key)
llm = ChatOpenAI(
    model="gpt-4o-mini",  # or gpt-4.1 / gpt-4o
    temperature=0,
    api_key = openai_api_key
)

# vectorstore = Chroma(
#     collection_name="schemes",
#     persist_directory="./chroma_data",
#     embedding_function=get_embedding_function(),
# )

retriever = SelfQueryRetriever.from_llm(
    llm=llm,
    vectorstore=get_chroma_vectorstore(),
    document_contents="""
    Government schemes with eligibility rules. 
    Metadata fields may contain multiple values and partial matches.
    """,
    metadata_field_info=metadata_field_info,
    # search_type="mmr",   # 👈 MMR enabled
    # search_kwargs={
    #     "k": 10,
    #     "fetch_k": 50,
    #     "lambda_mult": 0.7
    # },
    verbose=True,  # 🔥 shows generated filters
)

business_profile_query = """
Find government schemes suitable for:
- A women-owned startup
- IT industry
- 15 employees
- MSME registered
- Located in Karnataka, India
- Established in 2022
- Startup stage
"""

results = retriever.get_relevant_documents(business_profile_query)


print(results)

