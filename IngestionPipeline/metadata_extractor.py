# metadata_extractor.py
import re
from pathlib import Path
import nltk
nltk.download('stopwords')
nltk.download('punkt_tab')
from rake_nltk import Rake

METADATA_SCHEMA = {
    "scheme_name": str,
    "scheme_code": str,
    "category": str,              # Subsidy / Grant / Incentive
    "industry": list,             # ["IPR", "Khadi", "Manufacturing"]
    "business_size": list,        # ["Micro", "Small", "Medium", "MSME"]
    "year": list,                 # ["2019", "2020"]
    "geography": list,            # ["India", "Karnataka"]
    "document_type": str,         # guidelines | policy | internal | application
    "keywords": list,             # flattened union
    "source_path": str,           # full relative path
    "file_name": str
}

BUSINESS_SIZE_KEYWORDS = {
    "MSME": ["msme", "msmes"],
    "Micro": ["micro"],
    "Small": ["small"],
    "Medium": ["medium"],
    "Startup": ["startup", "start-up"]
}

INDUSTRY_KEYWORDS = {
    "IPR": ["ipr", "intellectual property"],
    "Khadi": ["khadi"],
    "Cluster Development": ["cluster"],
    "Finance": ["mudra", "loan", "credit"]
}

DOCUMENT_TYPE_MAP = {
    "guidelines": ["guideline", "guidelines"],
    "policy": ["policy"],
    "internal": ["internal"],
    "application": ["application", "form"]
}

STATE_KEYWORDS = {
    "Karnataka": ["karnataka"],
    "India": ["pradhan mantri", "yojana"]
}

CATEGORY_KEYWORDS = {
    "Subsidy": ["subsidy"],
    "Grant": ["grant", "assistance"],
    "Incentive": ["incentive"],
    "Loan / Credit": ["loan", "credit", "mudra", "finance"],
    "Awareness / Training": ["awareness", "training", "capacity building"],
    "Policy / Regulation": ["policy", "regulation", "act", "rules"]
}

def infer_category(text_blob: str) -> str:
    """
    Infer scheme category based on ranked keyword matching.
    """
    for category, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in text_blob:
                return category
    return "Scheme"

def extract_metadata_from_path(file_path: Path) -> dict:
    parts = [p.lower() for p in file_path.parts]
    file_name = file_path.name.lower()

    metadata = {
        "scheme_name": "",
        "scheme_code": "",
        "category": "",
        "industry": [],
        "business_size": [],
        "year": [],
        "geography": [],
        "document_type": "",
        "keywords": [],
        "source_path": str(file_path),
        "file_name": file_path.name
    }

    # 1️⃣ Scheme code + name from folder like (BAIPR)_Building awareness...
    for part in parts:
        match = re.match(r"\(([^)]+)\)_(.+)", part)
        if match:
            metadata["scheme_code"] = match.group(1).upper()
            metadata["scheme_name"] = match.group(2).title()

    # 2️⃣ Business size
    text_blob = " ".join(parts + [file_name])
    for size, keys in BUSINESS_SIZE_KEYWORDS.items():
        if any(k in text_blob for k in keys):
            metadata["business_size"].append(size)

    # 3️⃣ Industry
    for industry, keys in INDUSTRY_KEYWORDS.items():
        if any(k in text_blob for k in keys):
            metadata["industry"].append(industry)

    # 4️⃣ Geography
    for geo, keys in STATE_KEYWORDS.items():
        if any(k in text_blob for k in keys):
            metadata["geography"].append(geo)

    # 5️⃣ Year extraction (handles ranges)
    years = re.findall(r"(19|20)\d{2}", text_blob)
    metadata["year"] = sorted(set(years))

    # 6️⃣ Document type
    for dtype, keys in DOCUMENT_TYPE_MAP.items():
        if any(k in file_name for k in keys):
            metadata["document_type"] = dtype
            break

    # Extract other keywords that don't match with the above from the file name and folder names
    keywords = []
    r= Rake()
    
    for part in parts:
        part = re.sub(r"[^a-z0-9\s]", " ", part)
        r.extract_keywords_from_text(part)
        keywords.extend(r.get_ranked_phrases())
    
    metadata["keywords"] = keywords
    # Category 
    metadata["category"] = infer_category(text_blob)

    return metadata

if __name__ == "__main__":
    path = Path("Subsidies Schemes Grants and Incentives\(BAIPR)_Building awareness on IPR for msme\IPR-Guidelines-CLCS-TUS-2019-2020.pdf")
    metadata = extract_metadata_from_path(path)
    print(metadata)


