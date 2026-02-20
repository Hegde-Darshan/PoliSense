from langgraph.graph import StateGraph, START, END
from langsmith import traceable, Client as SmithClient

from pathlib import Path
from dotenv import load_dotenv
from IngestionPipeline.logger import LOGGING_CONFIG
from typing import Literal
#import functions - 
#import IngestionPipeline.data_loader as loader
import IngestionPipeline.utils as utils
#import IngestionPipeline.vectorizer as vectorizer
import IngestionPipeline.prompts as prompts
import IngestionPipeline.llm_extractor as llm_extractor
from IngestionPipeline.utils import IngestionWorkflowState

from langchain_google_genai import ChatGoogleGenerativeAI

# Configure loggers
import logging.config
logging.config.dictConfig(LOGGING_CONFIG)
root_logger = logging.getLogger()
logger = root_logger.getChild("graph")

# Suppress unnecessary logs
logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

# Configure global and environment variables
ROOT_PATH = Path(__file__).parent
try:
    load_dotenv(ROOT_PATH / ".env")
    load_dotenv(ROOT_PATH / ".env.secrets")
except Exception as e:
    logger.error(f"Error loading .env file: {e}")

#load config file
import yaml
try:
    with open(ROOT_PATH / "config.yml", 'r') as config_file:
        config = yaml.safe_load(config_file)
except FileNotFoundError:
    logger.error("config.yml file not found.")
    raise

#Get langsmith client (to trace some specific variables in the workflow)

"""
Steps - 
1. Get files to query on -
2. LLM inference to extract relevant information from the files -
3.1. Vectorize the extracted information and store in vector database -
3.2. HITL to verify the extracted information and vectorization -
"""

@traceable
def is_next_iteration(state: IngestionWorkflowState) -> bool:
    if state.policy_current_idx == -1: return False
    else: return True

@traceable
def get_next_policy_idx(state: IngestionWorkflowState) -> IngestionWorkflowState:
    state.policy_current_idx += 1 #type: ignore
    state.policy_current = state.policy_to_query[state.policy_current_idx] #type: ignore
    if state.policy_current_idx >= len(state.policy_to_query): #type: ignore
        state.policy_current_idx = -1
        state.policy_current = None
    return state


@traceable
def get_relavent_files(state: IngestionWorkflowState) -> IngestionWorkflowState:
    list_of_files = utils.get_new_filenames_for_llm(state.file_directory, state.processed_directories)  # type: ignore
    state.file_paths = list_of_files
    state.policy_to_query = list(list_of_files.keys()) # type: ignore
    state.policy_current_idx = 0
    state.policy_current = state.policy_to_query[state.policy_current_idx] # type: ignore
    return state


@traceable
def extract_information(state: IngestionWorkflowState) -> IngestionWorkflowState:
    #evaluate one policy at a time
    #get the current policy to query on
    prompt_manager = prompts.PoliSensePrompts(pdf_paths=state.file_paths[state.policy_to_query[state.policy_current_idx]],  #type: ignore
                            policy_name=state.policy_to_query[state.policy_current_idx])  #type: ignore
    llm_client = llm_extractor.initialize_llm_with_config(is_structured_model=True)
    state.llm_config = dict(llm_client.__dict__)
    #print(f"Invoking LLM with prompt: {prompt_manager.get_prompt()}")
    #struct_response = llm_client.invoke(prompt_manager.get_prompt())
    struct_response = llm_client.invoke("This is a test invocation. Return response in the same format but tailor it with empty or test string values")
    summary = llm_extractor.PDFSummary.model_validate(struct_response)
    state.llm_response = summary.model_dump()
    return state


@traceable
def db_ingestion(state: IngestionWorkflowState) -> IngestionWorkflowState:
    #ingest into postgres database, with approved flag as False
    #table schema yet to be defined
    return state


@traceable
def HITL_verification(state: IngestionWorkflowState) -> IngestionWorkflowState:
    #ingest into the same postgres database under the table review_queue.
    #the HITL team can review the extracted information, and either approve or reject it.
    #after approval, main table changes the flag approved to True
    return state


if __name__ == "__main__":
    graph = StateGraph(state_schema=IngestionWorkflowState)
    graph.add_node("get_relavent_files", get_relavent_files)
    graph.add_node("extract_information", extract_information)
    graph.add_node("next_policy", get_next_policy_idx)
    #graph.add_node("db_ingestion", db_ingestion)
    #graph.add_node("HITL_verification", HITL_verification)

    # Define transitions between states
    graph.add_edge(START, "get_relavent_files")
    graph.add_edge("get_relavent_files", "extract_information")
    graph.add_edge("extract_information", "next_policy")
    graph.add_conditional_edges("next_policy", is_next_iteration, {True: "extract_information", False: END})

    # Compile and execute the graph
    compiled_graph = graph.compile()
    #compiled_graph.get_graph().draw_mermaid_png(output_file_path=r"untracked/graph_visualization.png")

    #initial state - 
    graph_state = IngestionWorkflowState()
    graph_state.file_directory = str(ROOT_PATH/Path(config['DATA_PATH']))
    graph_state.processed_directories = str(ROOT_PATH/Path(config['READ_PATH']))
    print(f"Starting graph execution with initial state: {graph_state}\n\n")

    compiled_graph.invoke(graph_state)
    print(f"Graph execution completed with final state: {graph_state}")
