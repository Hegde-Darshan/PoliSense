# metadata_extractor.py
from fileinput import filename
import re
from pathlib import Path
import nltk
nltk.download('stopwords')
nltk.download('punkt_tab')
from rake_nltk import Rake

# ROOT_PATH = Path(__file__).parent

MIN_YEAR = 1800
MAX_YEAR = 2100

def extract_years(text: str) -> list[str]:
    years = set()

    # 1️⃣ Full ranges: 2019-2021 or 2019–2021
    for start, end in re.findall(r"\b(\d{4})\s*[-–]\s*(\d{4})\b", text):
        for y in range(int(start), int(end) + 1):
            if MIN_YEAR <= y <= MAX_YEAR:
                years.add(str(y))

    # 2️⃣ Short ranges: 2022-27
    for start, end in re.findall(r"\b(\d{4})\s*[-–]\s*(\d{2})\b", text):
        century = (int(start) // 100) * 100
        end_year = century + int(end)
        for y in range(int(start), end_year + 1):
            if MIN_YEAR <= y <= MAX_YEAR:
                years.add(str(y))

    # 3️⃣ Standalone years
    for y in re.findall(r"\b\d{4}\b", text):
        if MIN_YEAR <= int(y) <= MAX_YEAR:
            years.add(y)

    return " ".join(sorted(years)) # type: ignore

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
    "file_name": str,
    "special_attribute": list
}

BUSINESS_SIZE_KEYWORDS = {
    "MSME": ["msme", "msmes"],
    "Micro": ["micro"],
    "Small": ["small"],
    "Medium": ["medium"],
    "Startup": ["startup", "start-up"]
}

INDUSTRY_KEYWORDS = {
    "Technology": ["tech", "health technology", "it", "technology"],
    "Finance": ["finance", "mudra", "credit"],
    "Textile":["textile","khadi", "cotton", "silk", "coir"],
    "Agricultural":["agri", "krushi", "agricultural", "raita"],
    "Entertainment":["entertainment"],
    "Travel":["travel", "tourism"],
    "Trade":["trade"]
}

SUB_INDUSTRY_KEYWORDS = ["health technology","biotech", "fintech", "agritech", "khadi","silk", "coir","cotton","rice","wheat", "ragi","it","information technology","ai/machine learning", "ai"]

DOCUMENT_TYPE_MAP = {
    "guidelines": ["guideline", "guidelines"],
    "policy": ["policy"],
    "internal": ["internal"],
    "application": ["application", "form"]
}

STATE_KEYWORDS = {
    "Karnataka": ["karnataka", "KA"]    
}

CENTRAL_KEYWORDS=["pradhan mantri", "india","central"]


SCHEME_CATEGORY_KEYWORDS = {
    "Subsidy": ["subsidy"],
    "Grant": ["grant", "assistance"],
    "Incentive": ["incentive"],
    "Loan / Credit": ["loan", "credit", "mudra", "finance"],
    "Awareness / Training": ["awareness", "training", "capacity building"],
    "Policy / Regulation": ["policy", "regulation", "act", "rules", "yojana"]
}

SPECIAL_KEYWORDS = {
    "IPR": ["ipr", "intellectual property"],
    "Women": ["women","mahila"],
    "Youth":["youth","young"],
    "Entrepreneurship": ["entrepreneurship","entrpreneur"],
    "Rural": ["rural"],
    "Urban":["urban","metropolitan","city"]
    }

def infer_category(text_blob: str) -> str:
    """
    Infer scheme category based on ranked keyword matching.
    """
    for category, keywords in SCHEME_CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in text_blob:
                return category
    return "Scheme"

def extract_metadata_from_path(file_path: Path) -> dict:
    # full_file_path = ROOT_PATH / file_path
    parts = [p.lower() for p in file_path.parts]
    file_name = file_path.name.lower()
    print("File name",file_name)
    print("partsss",str(parts))

    # metadata = {
    #     "scheme_name": "",
    #     "scheme_code": "",
    #     "category": "",
    #     "industry": [],
    #     "business_size": [],
    #     "year": [],
    #     "geography": [],
    #     "document_type": "",
    #     "keywords": [],
    #     "special_attribute":[],
    #     "source_path": str(file_path),
    #     "file_name": file_path.name
    # }

    metadata = {
        "scheme_name": "",
        "scheme_code": "",
        "scheme_category": "", # Policy/ Regulation, Grant, Scheme
        "document_type": "", # Guidelines, Application / Form
        "industry": "", # Technology, Agriculture, Textile, Machinery, Manufacturing, Entertainment, Travel
        "sub_industry": "", # Health Technology, Information Technology, Bio Technology, Agriculture Technology, linen textile, silk, khadi, coir
        "business_size": "", # small, msme, startup, medium, large
        "year": "",
        "state": "",
        "central": "", #True or false
        # "keywords": [],
        "special_attribute":"", #Women, Youth, SC/ST, General, Poor, 
        "source_path": str(file_path),
        "file_name": file_path.name
    }

    # 1️⃣ Scheme code + name from folder like (BAIPR)_Building awareness...
    for part in parts:
    # Look for scheme code anywhere in parentheses
        code_match = re.search(r"\(([^)]+)\)", part)
        if code_match:
            code = code_match.group(1).upper()

            # Ignore numeric-only brackets like (2022)
            if not code.isdigit():
                metadata["scheme_code"] = code
                metadata["scheme_name"] = re.sub(r"\([^)]+\)", "", part)

                break  # stop after first valid match

    # Fallback: no scheme code found
    if not metadata["scheme_name"]:
        
        for part in parts:
            # print("parttttt ",part)
            # skip obvious non-scheme folders
            if part.lower().strip() in {"subsidies schemes grants and incentives", "documents", "testdocuments"}:
                continue

            metadata["scheme_name"] = part
            break

    # Normalize scheme name
    metadata["scheme_name"] = (
        metadata["scheme_name"]
        .replace("_", " ")
        .strip()
        .title()
    )

    # 2️⃣ Business size
    text_blob = " ".join(parts + [file_name])
    for size, keys in BUSINESS_SIZE_KEYWORDS.items():
        if any(k in text_blob for k in keys):
            # metadata["business_size"].append(size)
            metadata["business_size"] = size
            break

    # 3️⃣ Industry
    for industry, keys in INDUSTRY_KEYWORDS.items():
        if any(k in text_blob for k in keys):
            # metadata["industry"].append(industry)
            metadata["industry"] = industry
            break

    for v in SUB_INDUSTRY_KEYWORDS:
        if v in text_blob:
            metadata["sub_industry"] = v
            break

    # 4️⃣ Geography
    for geo, keys in STATE_KEYWORDS.items():
        if any(k in text_blob for k in keys):
            # metadata["geography"].append(geo)
            metadata["state"] = geo
            break
    
    metadata["central"] = bool(0) # type: ignore
    if any(v in text_blob for v in CENTRAL_KEYWORDS):
        metadata["central"] = bool(1) # type: ignore

    # 5️⃣ Year extraction (handles ranges)
    metadata["year"] = extract_years(text_blob) # type: ignore

    # 6️⃣ Document type
    for dtype, keys in DOCUMENT_TYPE_MAP.items():
        if any(k in file_name for k in keys):
            metadata["document_type"] = dtype
            break

    # Extract other keywords that don't match with the above from the file name and folder names
    # keywords = []
    # r = Rake()
    
    # for part in parts:
    #     part = re.sub(r"[^a-z0-9\s]", " ", part)
    #     r.extract_keywords_from_text(part)
    #     keywords.extend(r.get_ranked_phrases())
    
    # metadata["keywords"] = keywords
    # Category 
    metadata["scheme_category"] = infer_category(text_blob)

    for dtype, keys in SPECIAL_KEYWORDS.items():
        print(keys)
        if any(k in text_blob for k in keys):
            # metadata["special_attribute"].append(dtype)
            metadata["special_attribute"] = dtype
            break

    return metadata

if __name__ == "__main__":
    # path = Path("Subsidies Schemes Grants and Incentives\(BAIPR)_Building awareness on IPR for msme\IPR-Guidelines-CLCS-TUS-2019-2020.pdf")
    # path = Path("TestDocuments\(TREAD)_trade related entreprenuership assistance and development scheme for women\TREAD Guidelines.pdf")
    # path = Path(r"TestDocuments\2022 Credit Guarantee Scheme for Startups\credit-guarantee-scheme-for-startup.pdf")
    # source_path_str = "2022-27 Credit Guarantee Scheme for Startups\credit-guarantee-scheme-for-startup.pdf"
    source_path_str = r"(TREAD)_trade related entreprenuership assistance and development scheme for women\TREAD Guidelines.pdf"
    # source_path_str = "Startup India Seed Fund Scheme (SISFS)\credit-guarantee-scheme-for-startup.pdf"
    test_path = "TestDocuments"
    full_path = Path(fr"{test_path} / {source_path_str}")
    metadata = extract_metadata_from_path(full_path)
    print(metadata)


