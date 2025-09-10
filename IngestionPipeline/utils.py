import os
import json

from pathlib import Path

def get_new_filenames(folder_path: Path, processed_files:Path):
    """
    Get new PDF filenames from the folder that have not been processed yet.
    
    Args:
        folder_path: Path object of the folder containing PDF files.
        processed_files (optional): Path object of the JSON file tracking processed files. if not provided, assumes no files are read in the folder"""
    try:
        files_read = json.load(open(processed_files, 'r'))
        files_to_read = []
    except FileNotFoundError:
        files_read, files_to_read = [], []

    for file_name in os.listdir(folder_path):
        if file_name.endswith(".pdf") and file_name not in files_read:
            files_to_read.append(file_name)
            files_read.append(file_name)
        
    json.dump(files_read, open(processed_files, 'w'))
    return files_to_read


