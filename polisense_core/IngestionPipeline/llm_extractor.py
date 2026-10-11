from pathlib import Path
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field
from typing import Optional, List


class IncentiveSummary(BaseModel):
    IncentiveName: str = Field(description="Name of the incentive")
    Description:str = Field(description="Description of the incentive")
    Benefits: Optional[dict[str, str]] = Field(description="Detailed write-up on the benefits provided by the incentive, such as financial support, tax breaks, subsidies, or any other advantages offered to eligible applicants.")


class PolicySummary(BaseModel):
    """ Structured output format for sub - policy document information extraction."""
    PolicyName: str = Field(description="Name of the policy")
    Category:str = Field(description="Category type of the policy")
    Industry:str = Field(description="Industry/sector the policy is applicable to, such as Manufacturing, IT, Finance and so on")
    SubIndustry:str = Field(description="Sub-Industry/sector the policy is applicable to, such as Software, Hardware, Khadi, Food Processing and so on")
    BusinessSize:str = Field(description="Size of the business the policy is applicable to, such as Startup, MSME, Large Enterprise, Mega Enterprise")
    Geography:str = Field(description="Geographical applicability of the policy, such as National, State-specific, or Regional")
    Year:list[str] = Field(description="Year or range of years the policy is applicable to")
    SpecialAttributes: Optional[List[str]] = Field(description="Any special attributes or focus areas of the policy")
    Keywords: Optional[List[str]] = Field(description="List of important keywords or phrases associated with the policy")
    PolicySummary: str = Field(description="A concise summary of the policy, highlighting its main objectives, benefits, and any unique features")
    EligibilityCriteria: Optional[str] = Field(description="Detailed write-up on the eligibility criteria for the policy, including any specific requirements or conditions that applicants must meet to qualify for the policy benefits.")
    IncentivesAndBenefits: Optional[List[IncentiveSummary]] = Field(description="Detailed write-up on the incentives and benefits provided by the policy, such as financial support, tax breaks, subsidies, or any other advantages offered to eligible applicants.")


class PDFSummary(BaseModel):
    """Consolidated structured output format for PDF document summarization and metadata extraction."""
    ParentPolicyName: Optional[str] = Field(description="Name of the parent policy, if the document is a sub-policy or related to a larger policy framework")
    PolicyInformation: Optional[List[PolicySummary]] = Field(description="Structured summary of the policy/sub-policy level information extracted from the document")
    PolicyGoals: Optional[List[str]] = Field(description="List of the main goals or objectives of the policy as extracted from the document")

class PolicyQuestionnaire(BaseModel):
    """Structured output format for policy questionnaire extraction."""
    ParentPolicyName: str = Field(description="Name of the parent policy, if the document is a sub-policy or related to a larger policy framework")
    Questions: List[str] = Field(description="List of questions on the policy such that the answers to these will help determine the policy's scope, applicability and quantitative details of available incentives, extracted from the document")

def initialize_llm_with_config(
        model_name: str = "gemini-2.5-pro",
        temperature: float = 1,
        max_tokens: int | None = None,
        timeout: float | None = None,
        max_retries: int = 2,
        is_structured_model: bool = True
):
    model = ChatGoogleGenerativeAI(model=model_name, 
                temperature=temperature, 
                max_tokens=max_tokens,
                timeout=timeout,
                max_retries=max_retries)
    
    if is_structured_model:
        structured_model = model.with_structured_output(schema =PDFSummary.model_json_schema(),
                                method= "json_schema")
        return structured_model
    else:
        return model

def cache_content(self, content: str, ttl_seconds: int = 600):
    """Caches the given content with Gemini content cache """
    from langchain_google_genai import create_context_cache
    from langchain_core.messages import HumanMessage, SystemMessage
    model = ChatGoogleGenerativeAI(model="gemini-2.5-pro")
    cache = create_context_cache(
        model=model,
        ttl=f"{ttl_seconds}s",
        messages=[
                SystemMessage(content="You are a content caching service. Store the following content and return a unique cache key."),
                HumanMessage(content=content)
                ]
            )
    return cache # cache.name -> "cachedContents/xxxxx"


if __name__ == "__main__":
    from dotenv import load_dotenv
    # env_vars = Path(r"C:\Users\lenovo\OneDrive\Desktop\Projects\PoliSense")
    env_vars = Path("C:\\Users\\gowri\\Documents\\Projects\\PoliSense\\PoliSense")
    try:
        load_dotenv(env_vars / ".env")
        load_dotenv(env_vars / ".env.secrets")
    except Exception as e:
        print(f"Error loading .env file: {e}")
    #print(PDFSummary.schema_json(indent=2))
    model = initialize_llm_with_config()
    
    