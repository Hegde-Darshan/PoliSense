from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import SystemMessage, HumanMessage, FileContentBlock, TextContentBlock
from pathlib import Path
import base64

import logging
root_logger = logging.getLogger("ingestion_pipeline")
logger = root_logger.getChild("prompts")

from dotenv import load_dotenv

class PoliSensePrompts:
    """Class to encapsulate prompt templates for the PoliSense project."""
    def __init__(self, pdf_paths: list = [], policy_name:str="") -> None:
        self.pdf_paths = pdf_paths
        self.policy_name = policy_name
        self.prompt = self._get_pdf_extract_prompt()
    
    def get_prompt(self):
        """Returns the appropriate prompt template based on the input parameters."""
        return self.prompt.format_messages()
    
    @staticmethod
    def _get_pdf_bytes(pdf_paths: list[str]) -> list[FileContentBlock]:
        """Utility function to read a list of PDF files and return their content as bytes."""
        pdf_blocks = [FileContentBlock(type = "file", 
                                mime_type="application/pdf", 
                                base64 = base64.b64encode(open(pdf_path, "rb").read()).decode('utf-8'))  
                        for pdf_path in pdf_paths]
        return pdf_blocks

    
    def _get_pdf_extract_prompt(self) -> ChatPromptTemplate:
        """Returns a ChatPromptTemplate for PDF document extraction."""
        system_message = SystemMessage("You are an expert in summarization and details extraction of relevant information from any text PDF files")

        #create content blocks for human message
        pdf_blocks = [FileContentBlock(type = "file", 
                                mime_type="application/pdf", 
                                base64 = base64.b64encode(open(pdf_path, "rb").read()).decode('utf-8'))  
                        for pdf_path in self.pdf_paths]
        if pdf_blocks is None or len(pdf_blocks) == 0:
            logger.warning("No PDF files were read. Check the paths and files provided.")

        text_block = TextContentBlock(type="text", 
                        text = """The documents outlines one main policy, its details and guideline, and it may or may not contain sub policies. 
                        Summarize the document while following the given output schema. It is crucial to extract every detail available in the document. 
                        Some pointers to performing the task is below -\n
                        1) The first task is to classify the document type. The document can be of type Policy Operational Guidelines, Policy Details or Policy related Text Dump. This information will be apparent in the first two pages if not in the document title itself.\n
                        2) Summarization should be exhaustive, and include every detail from the document\n
                        3) This document is heavy on tables and cross-references to different sections within the document, upon encountering them, handle as follows:\n 
                            (a) Tables - extract relavent information by staying true to the structure. Wherever possible, interpret the table into plain text without compromising the semantics between rows and columns before summarizing\n 
                            (b) Cross reference - At each occurance of a cross reference, resolve it before summarizing. For example, if it says refer Section-A, include the necessary Section-A information inline.""")
        human_message = HumanMessage(content_blocks = [*pdf_blocks, text_block])
        logger.info(f"Text block of the prompt is as follows:\n {text_block}")

        return ChatPromptTemplate.from_messages([system_message, human_message])


    def get_form_extract_prompt(self):
        pass


if __name__ == "__main__":

    env_vars = Path(r"C:\Users\lenovo\OneDrive\Desktop\Projects\PoliSense")
    try:
        load_dotenv(env_vars / ".env")
        load_dotenv(env_vars / ".env.secrets")
    except Exception as e:
        print(f"Error loading .env file: {e}")
    # Example usage
    pdfs = [r"C:\Users\lenovo\OneDrive\Desktop\Projects\PoliSense\Data\LLM Notes.pdf"]
    prompt_manager = PoliSensePrompts(pdf_paths=pdfs)
    if prompt_manager.prompt:
        print(prompt_manager.prompt.messages)
        print(type(prompt_manager.prompt))

