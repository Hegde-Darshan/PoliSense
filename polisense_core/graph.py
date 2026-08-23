import os

from langgraph.graph import StateGraph, START, END
from langsmith import traceable
from langchain_core.tracers.langchain import wait_for_all_tracers
from functools import partial

from pathlib import Path
from dotenv import load_dotenv
from polisense_core.IngestionPipeline.logger import LOGGING_CONFIG
import psycopg2
import json
import yaml

#import functions - 
import polisense_core.IngestionPipeline.utils as utils
import polisense_core.IngestionPipeline.prompts as prompts
import polisense_core.IngestionPipeline.llm_extractor as llm_extractor
from polisense_core.IngestionPipeline.utils import IngestionWorkflowState
import polisense_core.IngestionPipeline.postgres_utils as db_utils

# Configure loggers
import logging.config
logging.config.dictConfig(LOGGING_CONFIG)
root_logger = logging.getLogger()
logger = root_logger.getChild("graph")

# Suppress unnecessary logs
logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("httpcore.connection").setLevel(logging.WARNING)
logging.getLogger("httpcore.http11").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("langsmith.client").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

# Configure global and environment variables
ROOT_PATH = Path(__file__).parent
try:
    load_dotenv(ROOT_PATH / ".env")
    load_dotenv(ROOT_PATH / ".env.secrets")
except Exception as e:
    logger.error(f"Error loading .env files: {e}")

#load config file
try:
    with open(ROOT_PATH / "config.yml", 'r') as config_file:
        config = yaml.safe_load(config_file)
except FileNotFoundError:
    logger.error("config.yml file not found.")
    raise

#Get langsmith client (to trace some specific variables in the workflow)


@traceable
def is_next_iteration(state: IngestionWorkflowState) -> bool:
    if state.policy_current_idx == -1: return False
    else: return True

@traceable
def get_next_policy_idx(state: IngestionWorkflowState) -> IngestionWorkflowState:
    state.policy_current_idx += 1 #type: ignore
    if state.policy_current_idx >= len(state.policy_to_query): #type: ignore
        state.policy_current_idx = -1
        state.policy_current = None
    else:
        state.policy_current = state.policy_to_query[state.policy_current_idx] #type: ignore
    return state


@traceable
def get_relavent_files(state: IngestionWorkflowState) -> IngestionWorkflowState:
    list_of_files = utils.get_new_filenames_for_llm(state.file_directory, state.processed_directories)  # type: ignore
    state.file_paths = list_of_files
    state.policy_to_query = list(list_of_files.keys()) # type: ignore
    state.policy_current_idx = -1 #initialize to -1 so that the first call to get_next_policy_idx will set it to 0
    state.policy_current = None
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
    struct_response = llm_client.invoke(prompt_manager.get_prompt())
    # struct_response = llm_client.invoke("This is a test invocation. Return response in the same format but tailor it with empty or test string values")
    summary = llm_extractor.PDFSummary.model_validate(struct_response)
    state.llm_response = summary.model_dump()
    return state


@traceable
def db_ingestion(state: IngestionWorkflowState, db_conn: psycopg2.extensions.connection) -> IngestionWorkflowState:
    """
    Ingest the extracted information into the Postgres database, master data table. 
    The ingestion function also generates a unique UUID for each policy which is stored in the database and can be used for future reference.
    """
    try:
        if state.llm_response:
            summary_dict = state.llm_response
            summary_dict['PolicyGroup'] = state.policy_current
            inserted_ids = db_utils.ingest_policy(summary_dict, db_conn)
            state.uuid_ingested.extend(inserted_ids)
            logger.info(f"Ingested policy '{state.policy_current}' -> {len(inserted_ids)} row(s) inserted, IDs: {inserted_ids}")
            #append to policy_queried list
            state.policy_queried.append(state.policy_current) #type: ignore
        else:
            logger.warning(f"No LLM response to ingest for policy '{state.policy_current}'")
            #append to policy_failed list
            state.policy_failed.append(state.policy_current) #type: ignore
    except Exception as e:
        #append to policy_failed list
        state.policy_failed.append(state.policy_current) #type: ignore
        logger.error(f"Error during database ingestion: {e}")
        db_conn.rollback()
    return state


@traceable
def HITL_verification(state: IngestionWorkflowState, db_conn: psycopg2.extensions.connection) -> IngestionWorkflowState:
    """
    Ingest the LLM response into a review queue for HITL verification. 
    The HITL team can review the extracted information and either approve or reject it. 
    After approval, the main table changes the flag approved to True.
    """
    try:
        if state.llm_response:
            review_id = db_utils.ingest_into_review_queue(state.llm_response, db_conn)
            logger.info(f"Added policy '{state.policy_current}' to review queue with ID: {review_id}")
    except Exception as e:
        logger.error(f"Error during HITL verification: {e}")
        db_conn.rollback()
    return state

@traceable
def update_status_files(state: IngestionWorkflowState) -> IngestionWorkflowState:
    #update the processed files record to avoid re-processing in the future iterations
    curr_files = json.load(open(ROOT_PATH/Path(config['READ_PATH']), 'r')) if os.path.exists(Path(config['READ_PATH'])) else []
    if state.policy_queried is not None:
        list_of_files = state.policy_queried + curr_files
    logger.debug(f"Files processed so far: {list_of_files}") # type: ignore
    json.dump(list_of_files, open(ROOT_PATH/Path(config['READ_PATH']), 'w')) # type: ignore

    #also update the skipped files record with the policies that failed processing
    json.dump(state.policy_failed, open(ROOT_PATH/Path(config['SKIPPED_PATH']), 'w'))
    return state


if __name__ == "__main__":
    db_conn = db_utils.get_connection()

    graph = StateGraph(state_schema=IngestionWorkflowState)

    graph.add_node("get_relavent_files", get_relavent_files)
    graph.add_node("first_policy", get_next_policy_idx)
    graph.add_node("extract_information", extract_information)
    graph.add_node("next_policy", get_next_policy_idx)
    graph.add_node("db_ingestion", partial(db_ingestion, db_conn=db_conn))
    graph.add_node("update_status_files", update_status_files)

    # Define transitions between states
    graph.add_edge(START, "get_relavent_files")
    graph.add_edge("get_relavent_files", "first_policy")
    graph.add_conditional_edges("first_policy", is_next_iteration, {True: "extract_information", False: "update_status_files"})
    graph.add_edge("extract_information", "db_ingestion")
    graph.add_edge("db_ingestion", "next_policy")
    graph.add_conditional_edges("next_policy", is_next_iteration, {True: "extract_information", False: "update_status_files"})
    graph.add_edge("update_status_files", END)

    # Compile and execute the graph
    compiled_graph = graph.compile()
    compiled_graph.get_graph().draw_mermaid_png(output_file_path=r"untracked/graph_visualization.png")

    #initial state - 
    graph_state = IngestionWorkflowState()
    graph_state.file_directory = str(ROOT_PATH/Path(config['DATA_PATH']))
    graph_state.processed_directories = str(ROOT_PATH/Path(config['READ_PATH']))

    print(f"Starting graph execution with initial state: {graph_state}\n\n")
    
    try:
        compiled_graph.invoke(graph_state)
        print(f"Graph execution completed with final state: {graph_state}")
    finally:
        wait_for_all_tracers()