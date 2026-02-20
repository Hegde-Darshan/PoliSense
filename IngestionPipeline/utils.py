import os
import json
from pathlib import Path
from typing import Dict, List

import logging

root_logger = logging.getLogger("ingestion_pipeline")
logger = root_logger.getChild("utils")


def get_new_filenames(folder_path: Path, processed_files:Path) -> List[str]:
    """
    Get new PDF filenames from the folder that have not been processed yet.
    
    Args:
        folder_path: Path object of the folder containing PDF files.
        processed_files (optional): Path object of the JSON file tracking processed files. if not provided, assumes no files are read in the folder"""
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
    
    Args:
        folder_path: Path object of the folder containing PDF files.
        processed_files (optional): Path object of the JSON file tracking processed files. if not provided, assumes no files are read in the folder"""
    try:
        files_read = list(json.load(open(processed_files, 'r')))
        print(f"Files already processed: {files_read}")
        files_to_read = {}
    except FileNotFoundError:
        print(f"No processed files record found at '{processed_files}'. Assuming no files have been read yet.")
        return None

    for root, dirs, files in os.walk(folder_path):
        for file_name in files:
            if file_name.endswith(".pdf") and file_name not in files_read:
                relative_path = os.path.relpath(os.path.join(root, file_name), folder_path)
                #add the path to the dictionary
                files_to_read.setdefault(root, []).append(relative_path)
                files_read.append(relative_path)
    
    json.dump(files_read, open(processed_files, 'w'))
    return files_to_read


def build_embedding_document(summary_dict: dict) -> str:
    pi = summary_dict.get("PolicyInformation") or {}
    incentives = pi.get("IncentivesAndBenefits") or []

    parts = [
        f"Policy: {pi.get('PolicyName', '')}",
        f"Category: {pi.get('Category', '')}",
        f"Industry: {pi.get('Industry', '')} - {pi.get('SubIndustry', '')}",
        f"Summary: {pi.get('PolicySummary', '')}",
        f"Eligibility: {pi.get('EligibilityCriteria', '')}",
        f"Keywords: {', '.join(pi.get('Keywords') or [])}",
        f"SpecialAttributes: {', '.join(pi.get('SpecialAttributes') or [])}",
        f"Goals: {', '.join(summary_dict.get('PolicyGoals') or [])}",
    ]
    for inc in incentives:
        parts.append(
            f"Incentive: {inc.get('IncentiveName', '')} - {inc.get('Description', '')}"
        )

    return "\n".join(p for p in parts if p.split(": ", 1)[-1].strip())