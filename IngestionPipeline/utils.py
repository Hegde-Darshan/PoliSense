import os
import json
from pathlib import Path
from typing import Dict, List, Any

import logging
from dataclasses import dataclass, field
from typing import Optional, Literal
from sentence_transformers import SentenceTransformer

_model_cache: dict[str, SentenceTransformer] = {}

root_logger = logging.getLogger("ingestion_pipeline")
logger = root_logger.getChild("utils")
ROOT_PATH = Path(__file__).parent.parent


def get_new_filenames(folder_path: Path, processed_files:Path) -> List[str]:
    """
    Get new PDF filenames from the folder that have not been processed yet.
    
    Args:
        folder_path: Path object of the folder containing PDF files.
        processed_files (optional): Path object of the JSON file tracking processed files. if not provided, assumes no files are read in the folder
    """
    try:
        files_read = list(json.load(open(processed_files, 'r')))
        print(f"Files already processed: {files_read}")
        files_to_read = []
    except FileNotFoundError:
        print(f"No processed files record found at '{processed_files}'. Assuming no files have been read yet.")
        return []

    for root, dirs, files in os.walk(folder_path):
        for file_name in files:
            if file_name.endswith(".pdf") and file_name not in files_read:
                relative_path = os.path.relpath(os.path.join(root, file_name), folder_path)
                files_to_read.append(relative_path)
                files_read.append(relative_path)
        
    #json.dump(files_read, open(processed_files, 'w'))
    return files_to_read


def get_new_filenames_for_llm(folder_path: Path, processed_files:Path) -> Dict[str, List[str]] | None:
    """
    Get new PDF filenames from the folder that have not been processed yet.
    From Data Directory, get all directory names (assumes each corresponds to a policy name)
    Look-up in processed policy file, if the policy is not processed, get all PDF files in the policy folder and add to the list of files to be processed by LLM.

    Args:
        folder_path: Path object of the folder containing PDF files.
        processed_files (optional): Path object of the JSON file tracking processed files. if not provided, assumes no files are read in the folder
    """
    try:
        policy_processed = list(json.load(open(processed_files, 'r')))
        print(f"Files already processed: {policy_processed}")
        files_to_read = {}
    except FileNotFoundError:
        print(f"No processed files record found at '{processed_files}'. Assuming no files have been read yet.")
        return None
    
    policy_folders = os.listdir(folder_path)
    policy_to_process = [folder for folder in policy_folders if folder not in policy_processed]
    
    for policy in policy_to_process:
        policy_path = os.path.join(folder_path, policy)
        for root, _, files in os.walk(policy_path):
            for file in files:
                if file.endswith(".pdf"):
                    #add the path to the dictionary
                    file_path = os.path.join(root, file)
                    files_to_read.setdefault(policy, []).append(file_path)
        policy_processed.append(policy)
    
    json.dump(policy_processed, open(processed_files, 'w'))
    return files_to_read


# def embed_documents(text: str) -> list[float]:
#     """
#     Generate embedding using sentence-transformers directly.
#     embedding_model param kept for backward compatibility but ignored.
#     """
#     # model_name = "BAAI/bge-small-en-v1.5"
    
#     # # Cache the model so it's not reloaded on every call
#     # if model_name not in _model_cache:
#     #     _model_cache[model_name] = SentenceTransformer(model_name)
    
#     # model = _model_cache[model_name]
#     # vector = model.encode(text, normalize_embeddings=True)
#     # return vector.tolist()

#     model = SentenceTransformer("BAAI/bge-small-en-v1.5")  # fresh every time, no cache
#     result = model.encode(text, normalize_embeddings=True).tolist()
#     print(f"Input len: {len(text)}, vec[:3]: {result[:3]}")
#     return result

# def get_embedding(text: str, embedding_model) -> list[float]:
#     """Generate embedding vector for the given text using the provided embedding model."""
#     return embedding_model.embed_query(text)


@dataclass
class IngestionWorkflowState: #Schema for langgraph workflow state for ingestion pipeline
    """Schema for langgraph workflow state"""
    file_directory: Optional[str] = None
    processed_directories: Optional[str] = None
    file_paths: Optional[Dict[str, List]] = None
    policy_to_query: Optional[List[str]] = None
    policy_current: Optional[str] = None
    policy_current_idx: Optional[int] = None
    policy_queried: List[str] = field(default_factory=list)
    policy_failed: List[str] = field(default_factory=list)
    uuid_ingested: List[Any] = field(default_factory=list)
    llm_config: Optional[Dict[str, Any]] = None
    llm_query: Optional[str] = None
    llm_response: Optional[Dict] = None
    


def load_policy_data() -> list[dict]:
    folder_path = Path(ROOT_PATH, "LLM_Summaries")
    # print(folder_path)
    policies = []
    for policy in os.listdir(folder_path):
        output = None
        with open(folder_path / policy, 'r') as p:
            data = json.load(p)
            output = data.get("outputs")
            # print(data.get("outputs"))
        if output:
            policies.append(output)
    # print(policies)
    return policies


# if __name__ == "__main__":
#     load_policy_data()