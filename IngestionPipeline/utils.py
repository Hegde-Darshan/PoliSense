import os
import json
from pathlib import Path
from typing import List

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