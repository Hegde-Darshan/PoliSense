# import general modules
from pathlib import Path
import os
import json
from dotenv import load_dotenv
from polisense_core.IngestionPipeline.logger import LOGGING_CONFIG

import polisense_core.IngestionPipeline.utils as utils
import polisense_core.IngestionPipeline.postgres_utils as db_utils
import polisense_core.IngestionPipeline.prompts as prompts
import polisense_core.IngestionPipeline.llm_extractor as llm_extractor

from langchain_huggingface import HuggingFaceEmbeddings

import faulthandler; faulthandler.enable() #optional: imported to debug system level errors

# Configure loggers
import logging.config
logging.config.dictConfig(LOGGING_CONFIG)
root_logger = logging.getLogger()
logger = root_logger.getChild("ingestion_pipeline")



# Suppress unnecessary logs
logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

# Configure global and environment variables
ROOT_PATH = Path(__file__).parent

# Initialize once outside the loop
conn = db_utils.get_connection()
embedding_model = HuggingFaceEmbeddings(model_name="BAAI/bge-small-en-v1.5")
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


if __name__ == "__main__":
      
    #get list of new files to ingest
    list_of_files = utils.get_new_filenames_for_llm(ROOT_PATH/Path(config['DATA_PATH']), 
                        ROOT_PATH/Path(config['READ_PATH']))
    logger.debug(f"List of new files to ingest: {list_of_files}")

    if list_of_files is None:
        logger.info("No new files to ingest. Exiting.")
        exit(0)

############################################################################################################################################################################################################################################
    #prepare for ingestion - 
    #Get prompt template, initialize LLM ,invoke LLM to extract summarizaition and metadata for each policy, and enrich metadata with extracted information before indexing in vectorstore
    #ingest each key in structuredOutput with the same metadata
    llm_client = llm_extractor.initialize_llm_with_config()
    llm_config = llm_client.__dict__
    logger.info(f"LLM client parameters: {json.dumps(llm_config, indent=2, default=str)}")
    ingested_files, skipped_files = {}, {}

    for policy in list_of_files.keys():
        prompt_manager = prompts.PoliSensePrompts(pdf_paths=list_of_files[policy], policy_name=policy)
        logger.info(f"Prompt manager created for policy: {policy}")
        
        struct_response = llm_client.invoke(prompt_manager.get_prompt())
        summary = llm_extractor.PDFSummary.model_validate(struct_response)
        summary_dict = summary.model_dump()
        logger.debug(f"Structured output from LLM for policy {policy}:\n {json.dumps(summary_dict, indent=2)}")

        #append policy group key to the output - policy group is the directory name under which the policy documents are stored. May or may not be the same as the name returned in policy_name key of LLM response                   
        summary_dict['PolicyGroup'] = policy

        """
        INGESTION LOGIC HERE
        - [DONE] INGEST METADATA AND OTHER DETERMINISTIC FIELDS TO POSTGRESQL (OR ANY OTHER DATABASE) FOR QUERYING PURPOSES
        - [DONE] INGEST FULL SUMMARY AND OTHER TEXT FIELDS TO POSTGRES PGVECTOR
        - [DONE] GENERATE AND STORE EMBEDDINGS FOR CERTAIN SEMANTIC FIELDS IN THE STRUCTURED OUTPUT
        - [DONE] EACH KEY IN THE STRUCTURED OUTPUT CAN BE A FIELD IN THE DATABASE, AND THE FULL SUMMARY CAN BE A DOCUMENT IN THE VECTORSTORE WITH ALL THE FIELDS IN METADATA
        - [DONE] THIS WAY, WE CAN LEVERAGE THE STRUCTURED OUTPUT FOR PRECISE FILTERING AND QUERYING, AND THE VECTORSTORE FOR SEMANTIC SEARCH AND RETRIEVAL OF RELEVANT POLICIES
        """ 

        try:
            inserted_ids = db_utils.ingest_policy(summary_dict, conn)
            logger.info(f"Ingested policy '{policy}' → {len(inserted_ids)} row(s) inserted, IDs: {inserted_ids}")
            ingested_files[policy] = list_of_files[policy]
        except Exception as e:
            logger.error(f"Failed to ingest policy '{policy}': {e}")
            conn.rollback()
            skipped_files[policy] = list_of_files[policy]

    #save files read
    #logic not included here to exclude keys that failed ingestion
    curr_files = json.load(open(Path(config['READ_PATH']), 'r')) if os.path.exists(Path(config['READ_PATH'])) else []
    if ingested_files is not None:
        list_of_files = list(ingested_files.values()) + curr_files
    logger.debug(f"Files processed so far: {list_of_files}")
    json.dump(list_of_files, open(ROOT_PATH/Path(config['READ_PATH']), 'w'))

    all_skipped_files = json.load(open(Path(config['SKIPPED_PATH']), 'r')) if os.path.exists(Path(config['SKIPPED_PATH'])) else []
    if skipped_files is not None:
        skipped_files = list(skipped_files.values()) + all_skipped_files
    logger.warning(f"Files skipped so far: {skipped_files}")
    json.dump(skipped_files, open(ROOT_PATH/Path(config['SKIPPED_PATH']), 'w'))
    
    logger.info("Ingestion process completed.")