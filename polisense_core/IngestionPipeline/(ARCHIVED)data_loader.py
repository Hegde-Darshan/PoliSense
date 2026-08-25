import os
from pathlib import Path
import glob

from langchain_core.documents import Document
from langchain_community.document_loaders import DirectoryLoader, PyPDFLoader, PDFPlumberLoader, UnstructuredPDFLoader
from langchain.text_splitter import CharacterTextSplitter, RecursiveCharacterTextSplitter
from typing import Iterator, List

import logging

import pytesseract
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
print(pytesseract.get_tesseract_version())

root_logger = logging.getLogger("ingestion_pipeline")
logger = root_logger.getChild("data_loader")


# Step 2: Chunk the text with metadata
def lazy_chunker(documents: list[Document]) -> Iterator[Document]:
    """
    Chunk a document into smaller pieces using RecursiveCharacterTextSplitter.
    Args:
        document: The langchain Document object to be chunked
    Yields: Chunks of the document as langchain Document objects
    """
    text_chunker = RecursiveCharacterTextSplitter(
        chunk_size=2000,
        chunk_overlap=500,
        length_function=len,
    )
    yield from text_chunker.split_documents(documents)


class ChosenFilesDirectoryLoader(DirectoryLoader):
    """
    Custom DirectoryLoader class to load only specified files from a directory
    """

    def __init__(self, directory, list_of_files):
        """
        Initialize with a path to directory and list of files to load.
        Args:
            directory: Path to directory
            list_of_files: List of filenames to load from the directory
        """
        self.path = directory
        self.list_of_files = list_of_files
        self.skipped = list()
        

    def load(self) -> List[Document]:
        """
        Greedy loader wrapper around lazy load
        """
        return list(self.lazy_load())
    

    def lazy_load(self) -> Iterator[Document]:
        """
        Lazy load function overloader to load only specified files
        """
        p = Path(self.path)
        if not p.exists():
            raise FileNotFoundError(f"Directory not found: '{self.path}'")
        if not p.is_dir():
            raise ValueError(f"Expected directory, got file: '{self.path}'")
        
        if self.list_of_files is None or len(self.list_of_files) == 0:
            raise ValueError("No filenames specified for loading.")
        
        for files in self.list_of_files:
            file_path = p / Path(files)
            file_name = Path(files).name
            parent_dir = Path(files).parent.name

            if os.path.isfile(file_path) and file_path.suffix == ".pdf":
                logger.debug(f"Loading file: {file_path}")
                #loader = PyPDFLoader(str(file_path))
                #loader = PDFPlumberLoader(str(file_path))
                loader = UnstructuredPDFLoader(str(file_path), mode="single", languages=['eng'])
                for doc in loader.lazy_load():
                    #need to add other metadata here if required
                    doc.metadata["filename"] = str(file_name)
                    doc.metadata["source"] = str(parent_dir)
                    doc.metadata["source_path"] = str(files)  # Full relative path for metadata extraction
                    yield doc
            else:
                self.skipped.append(file_path)
                logger.debug(f"Skipping unsupported file or not a file: {file_path}")