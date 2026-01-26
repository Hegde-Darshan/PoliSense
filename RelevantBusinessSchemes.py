"""
RelevantBusinessSchemes.py

Retrieves relevant government schemes for business profiles from ChromaDB
using metadata filters and returns unique schemes/files for each business.
"""

from langchain_huggingface import HuggingFaceEmbeddings
from pathlib import Path
from dotenv import load_dotenv
import chromadb
from langchain_chroma import Chroma
import os
import yaml
import json
from typing import Dict, List, Set, Any

ROOT_PATH = Path(__file__).parent

# Load config file
with open(ROOT_PATH / "config.yml", 'r') as config_file:
    config = yaml.safe_load(config_file)


def get_chroma_client():
    """
    Connect to running Chroma server (Docker).
    """
    load_dotenv(ROOT_PATH / ".env")

    chroma_host = os.getenv("CHROMA_SERVER")
    chroma_port = os.getenv("CHROMA_PORT")

    if not chroma_host or not chroma_port:
        raise EnvironmentError("CHROMA_SERVER and CHROMA_PORT must be set")

    return chromadb.HttpClient(
        host=chroma_host,
        port=int(chroma_port)
    )


def get_chroma_vectorstore() -> Chroma:
    """Get ChromaDB vectorstore for test collection."""
    collection_name = config['TEST_CHROMA_COLLECTION']
    client = get_chroma_client()
    embedding_fn = HuggingFaceEmbeddings(model_name="BAAI/bge-small-en-v1.5")

    return Chroma(
        client=client,
        collection_name=collection_name,
        embedding_function=embedding_fn
    )


def determine_business_size(employee_count: int, turnover_range: str = None) -> List[str]:
    """
    Determine business size categories based on employee count and turnover.
    Returns list of applicable sizes: Micro, Small, Medium, MSME, Startup
    """
    sizes = []
    
    # MSME classification based on employee count
    if employee_count <= 10:
        sizes.append("Micro")
    elif employee_count <= 50:
        sizes.append("Small")
    elif employee_count <= 250:
        sizes.append("Medium")
    
    # Always include MSME if within limits
    if employee_count <= 250:
        sizes.append("MSME")
    
    # Startup classification (typically < 50 employees and recent)
    if employee_count < 50:
        sizes.append("Startup")
    
    return sizes


def map_industry_to_scheme_industry(business_industry: str) -> str:
    """
    Map business industry to scheme industry keywords.
    Returns the most relevant scheme industry category.
    """
    industry_mapping = {
        "Technology": "IPR",
        "IT Services": "IPR",
        "Manufacturing": "Manufacturing",
        "Textiles": "Khadi",
        "Handloom": "Khadi",
        "Food Processing": "Cluster Development",
        "Agri Processing": "Cluster Development",
        "Heavy Manufacturing": "Manufacturing",
        "Auto Components": "Manufacturing"
    }
    
    return industry_mapping.get(business_industry, "")


def build_metadata_filters(business_profile: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build ChromaDB metadata filters from business profile.
    Since metadata is stored as comma-separated strings, we need to filter carefully.
    ChromaDB where clause supports exact matches, so we'll use post-filtering for contains.
    Returns a dict suitable for ChromaDB where clause (for exact matches) and a list
    of contains conditions for post-filtering.
    """
    where_filters = {}
    contains_conditions = {}  # For post-filtering since metadata is comma-separated
    
    # Geography filter (state) - stored as comma-separated string
    if "geography" in business_profile and "state" in business_profile["geography"]:
        state = business_profile["geography"]["state"]
        # Store for post-filtering since we can't do contains in where clause easily
        contains_conditions["geography"] = state
    
    # Business size filter - stored as comma-separated string
    employee_count = business_profile.get("employee_count", 0)
    turnover_range = business_profile.get("turnover_range", "")
    business_sizes = determine_business_size(employee_count, turnover_range)
    
    if business_sizes:
        # Store sizes for post-filtering
        contains_conditions["business_size"] = business_sizes
    
    # Industry filter - stored as comma-separated string
    business_industry = business_profile.get("industry", "")
    scheme_industry = map_industry_to_scheme_industry(business_industry)
    if scheme_industry:
        contains_conditions["industry"] = scheme_industry
    
    return {
        "where": where_filters,  # Exact match filters (if any)
        "contains": contains_conditions  # Contains conditions for post-filtering
    }


def create_query_text(business_profile: Dict[str, Any]) -> str:
    """
    Create a semantic search query from business profile attributes.
    Focus on key attributes that are most likely to match scheme content.
    """
    query_parts = []
    
    # Add industry (most important for matching)
    if "industry" in business_profile:
        query_parts.append(business_profile["industry"])
    
    # Add sub-industry
    if "sub_industry" in business_profile:
        query_parts.append(business_profile["sub_industry"])
    
    # Add growth stage (important for startup schemes)
    if "growth_stage" in business_profile:
        query_parts.append(business_profile["growth_stage"])
    
    # Add ownership type (important for women-owned schemes)
    if "ownership_type" in business_profile:
        query_parts.append(business_profile["ownership_type"])
    
    # Add geography (state is important)
    if "geography" in business_profile:
        geo = business_profile["geography"]
        if "state" in geo:
            query_parts.append(geo["state"])
    
    # Add special attributes
    if "special_attributes" in business_profile:
        query_parts.extend(business_profile["special_attributes"])
    
    # Add scheme-related keywords (most important for matching)
    query_parts.append("government scheme")
    query_parts.append("subsidy")
    query_parts.append("grant")
    query_parts.append("incentive")
    
    # Add business size keywords if applicable
    employee_count = business_profile.get("employee_count", 0)
    if employee_count < 50:
        query_parts.append("startup")
        query_parts.append("MSME")
    elif employee_count <= 250:
        query_parts.append("MSME")
    
    return " ".join(str(part) for part in query_parts if part)


def filter_by_contains(docs: List, contains_conditions: Dict[str, Any]) -> List:
    """
    Post-filter documents based on contains conditions for comma-separated metadata fields.
    """
    if not contains_conditions:
        return docs
    
    filtered_docs = []
    for doc in docs:
        matches = True
        
        # Check geography contains condition
        if "geography" in contains_conditions:
            geography_value = doc.metadata.get("geography", "")
            if isinstance(geography_value, str):
                if contains_conditions["geography"].lower() not in geography_value.lower():
                    matches = False
        
        # Check business_size contains condition
        if "business_size" in contains_conditions and matches:
            business_size_value = doc.metadata.get("business_size", "")
            if isinstance(business_size_value, str):
                sizes_to_check = contains_conditions["business_size"]
                if isinstance(sizes_to_check, list):
                    # Check if any of the sizes is in the comma-separated string
                    size_match = any(
                        size.lower() in business_size_value.lower() 
                        for size in sizes_to_check
                    )
                    if not size_match:
                        matches = False
                else:
                    if sizes_to_check.lower() not in business_size_value.lower():
                        matches = False
        
        # Check industry contains condition
        if "industry" in contains_conditions and matches:
            industry_value = doc.metadata.get("industry", "")
            if isinstance(industry_value, str):
                if contains_conditions["industry"].lower() not in industry_value.lower():
                    matches = False
        
        if matches:
            filtered_docs.append(doc)
    
    return filtered_docs


def get_relevant_schemes(business_profile: Dict[str, Any], vectorstore: Chroma, k: int = 10, debug: bool = False) -> List[Dict[str, Any]]:
    """
    Retrieve relevant schemes for a business profile using semantic search with metadata filters.
    """
    # Build query text
    query = create_query_text(business_profile)
    
    if debug:
        print(f"  Query: {query}")
    
    # Build metadata filters
    filter_dict = build_metadata_filters(business_profile)
    where_filters = filter_dict.get("where", {})
    contains_conditions = filter_dict.get("contains", {})
    
    if debug:
        print(f"  Contains conditions: {contains_conditions}")
    
    # Perform similarity search - get more results for post-filtering
    # Increase search_k significantly to ensure we have enough results after filtering
    search_k = k * 5 if contains_conditions else k  # Get many more if we need to post-filter
    
    try:
        if where_filters:
            # Use where clause for exact match metadata filtering
            results = vectorstore.similarity_search(
                query=query,
                k=search_k,
                where=where_filters
            )
        else:
            # No exact filters, just semantic search
            results = vectorstore.similarity_search(query=query, k=search_k)
    except Exception as e:
        # If filter fails, fall back to search without filters
        if debug:
            print(f"  Warning: Metadata filter failed, using search without filters: {e}")
        results = vectorstore.similarity_search(query=query, k=search_k)
    
    if debug:
        print(f"  Results before filtering: {len(results)}")
        if results:
            print(f"  Sample metadata: geography={results[0].metadata.get('geography', 'N/A')}, "
                  f"business_size={results[0].metadata.get('business_size', 'N/A')}, "
                  f"industry={results[0].metadata.get('industry', 'N/A')}")
    
    # Apply post-filtering for contains conditions - but make it more lenient
    if contains_conditions and results:
        filtered_results = filter_by_contains(results, contains_conditions)
        
        if debug:
            print(f"  Results after strict filtering: {len(filtered_results)}")
        
        # If filtering removed all results, use lenient filtering (OR logic)
        if len(filtered_results) == 0 and len(results) > 0:
            if debug:
                print(f"  Warning: Strict filtering removed all results. Using lenient filtering (OR logic).")
            # Try lenient filtering - at least one condition should match
            filtered_results = filter_by_contains_lenient(results, contains_conditions)
            if debug:
                print(f"  Results after lenient filtering: {len(filtered_results)}")
            
            # If lenient filtering also removes all, use original results
            if len(filtered_results) == 0:
                if debug:
                    print(f"  Warning: Lenient filtering also removed all results. Using unfiltered results.")
                filtered_results = results
        
        results = filtered_results
        # Limit to k results after filtering
        results = results[:k]
    elif not results:
        if debug:
            print(f"  Warning: No results found for query. Try a broader search.")
        # Try a simpler query without filters
        simple_query = "government scheme startup MSME"
        results = vectorstore.similarity_search(query=simple_query, k=k)
        if debug:
            print(f"  Fallback search results: {len(results)}")
    
    return results


def filter_by_contains_lenient(docs: List, contains_conditions: Dict[str, Any]) -> List:
    """
    Lenient post-filtering: at least ONE condition should match (OR logic instead of AND).
    This is a fallback when strict filtering removes all results.
    """
    if not contains_conditions:
        return docs
    
    filtered_docs = []
    for doc in docs:
        matches_any = False
        
        # Check geography contains condition
        if "geography" in contains_conditions:
            geography_value = doc.metadata.get("geography", "")
            if isinstance(geography_value, str):
                if contains_conditions["geography"].lower() in geography_value.lower():
                    matches_any = True
        
        # Check business_size contains condition
        if "business_size" in contains_conditions and not matches_any:
            business_size_value = doc.metadata.get("business_size", "")
            if isinstance(business_size_value, str):
                sizes_to_check = contains_conditions["business_size"]
                if isinstance(sizes_to_check, list):
                    # Check if any of the sizes is in the comma-separated string
                    if any(size.lower() in business_size_value.lower() for size in sizes_to_check):
                        matches_any = True
                else:
                    if sizes_to_check.lower() in business_size_value.lower():
                        matches_any = True
        
        # Check industry contains condition
        if "industry" in contains_conditions and not matches_any:
            industry_value = doc.metadata.get("industry", "")
            if isinstance(industry_value, str):
                if contains_conditions["industry"].lower() in industry_value.lower():
                    matches_any = True
        
        # If no conditions specified or at least one matches, include the doc
        if matches_any or not contains_conditions:
            filtered_docs.append(doc)
    
    return filtered_docs


def extract_unique_schemes(results: List) -> Dict[str, Set[str]]:
    """
    Extract unique scheme names and file names from search results.
    Returns dict with 'schemes' and 'files' sets.
    """
    unique_schemes = set()
    unique_files = set()
    
    for doc in results:
        # Extract scheme name
        scheme_name = doc.metadata.get("scheme_name", "").strip()
        if scheme_name:
            unique_schemes.add(scheme_name)
        
        # Extract scheme code
        scheme_code = doc.metadata.get("scheme_code", "").strip()
        if scheme_code:
            unique_schemes.add(f"{scheme_code} - {scheme_name}" if scheme_name else scheme_code)
        
        # Extract file name
        file_name = doc.metadata.get("file_name", "").strip()
        if file_name:
            unique_files.add(file_name)
        
        # Also extract from source_path
        source_path = doc.metadata.get("source_path", "").strip()
        if source_path:
            # Extract just the filename from path
            file_from_path = os.path.basename(source_path)
            if file_from_path:
                unique_files.add(file_from_path)
    
    return {
        "schemes": unique_schemes,
        "files": unique_files
    }


def load_business_profiles(file_path: Path) -> List[Dict[str, Any]]:
    """
    Load business profiles from text file.
    Each profile is a JSON object separated by blank lines.
    """
    profiles = []
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Split by double newlines (blank lines)
    profile_blocks = content.strip().split('\n\n')
    
    for block in profile_blocks:
        block = block.strip()
        if block:
            try:
                profile = json.loads(block)
                profiles.append(profile)
            except json.JSONDecodeError as e:
                print(f"Warning: Failed to parse business profile: {e}")
                print(f"Block content: {block[:100]}...")
                continue
    
    return profiles


def format_business_profile(profile: Dict[str, Any]) -> str:
    """
    Format business profile as a readable string.
    """
    lines = []
    lines.append(f"Business Name: {profile.get('business_name', 'N/A')}")
    
    if "legal_entity_type" in profile:
        lines.append(f"Legal Entity Type: {profile['legal_entity_type']}")
    
    if "industry" in profile:
        lines.append(f"Industry: {profile['industry']}")
        if "sub_industry" in profile:
            lines.append(f"Sub-Industry: {profile['sub_industry']}")
    
    if "employee_count" in profile:
        lines.append(f"Employee Count: {profile['employee_count']}")
    
    if "turnover_range" in profile:
        lines.append(f"Turnover Range: {profile['turnover_range']}")
    
    if "year_of_establishment" in profile:
        lines.append(f"Year of Establishment: {profile['year_of_establishment']}")
    
    if "geography" in profile:
        geo = profile["geography"]
        geo_parts = []
        if "country" in geo:
            geo_parts.append(f"Country: {geo['country']}")
        if "state" in geo:
            geo_parts.append(f"State: {geo['state']}")
        if "district" in geo:
            geo_parts.append(f"District: {geo['district']}")
        if geo_parts:
            lines.append("Geography: " + ", ".join(geo_parts))
    
    if "ownership_type" in profile:
        lines.append(f"Ownership Type: {profile['ownership_type']}")
    
    if "growth_stage" in profile:
        lines.append(f"Growth Stage: {profile['growth_stage']}")
    
    if "registration" in profile:
        reg = profile["registration"]
        reg_parts = []
        if reg.get("msme"):
            reg_parts.append("MSME Registered")
        if "udyam_number" in reg:
            reg_parts.append(f"Udyam Number: {reg['udyam_number']}")
        if reg_parts:
            lines.append("Registration: " + ", ".join(reg_parts))
    
    if "special_attributes" in profile:
        lines.append(f"Special Attributes: {', '.join(profile['special_attributes'])}")
    
    return "\n".join(lines)


def write_results_to_file(all_results: Dict[str, Any], output_file: Path):
    """
    Write all results to a formatted text file.
    """
    with open(output_file, 'w', encoding='utf-8') as f:
        # Header
        f.write("=" * 80 + "\n")
        f.write("RELEVANT BUSINESS SCHEMES - EXTRACTION RESULTS\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"Generated from ChromaDB Collection: {config['TEST_CHROMA_COLLECTION']}\n")
        f.write(f"Total Business Profiles Processed: {len(all_results)}\n")
        f.write("=" * 80 + "\n\n")
        
        # Process each business
        for idx, (business_name, data) in enumerate(all_results.items(), 1):
            f.write("=" * 80 + "\n")
            f.write(f"BUSINESS {idx}: {business_name}\n")
            f.write("=" * 80 + "\n\n")
            
            # Business Profile Details
            f.write("BUSINESS PROFILE:\n")
            f.write("-" * 80 + "\n")
            profile_str = format_business_profile(data["profile"])
            f.write(profile_str + "\n")
            f.write("-" * 80 + "\n\n")
            
            # Search Results Summary
            f.write("SEARCH RESULTS SUMMARY:\n")
            f.write("-" * 80 + "\n")
            f.write(f"Total Matching Document Chunks: {data['total_matches']}\n")
            f.write(f"Unique Schemes Found: {len(data['schemes'])}\n")
            f.write(f"Unique Files Found: {len(data['files'])}\n")
            f.write("-" * 80 + "\n\n")
            
            # Relevant Schemes
            if data["schemes"]:
                f.write("RELEVANT SCHEMES:\n")
                f.write("-" * 80 + "\n")
                for scheme in data["schemes"]:
                    f.write(f"  • {scheme}\n")
                f.write("\n")
            else:
                f.write("RELEVANT SCHEMES:\n")
                f.write("-" * 80 + "\n")
                f.write("  No schemes found.\n\n")
            
            # Relevant Files
            if data["files"]:
                f.write("RELEVANT FILES:\n")
                f.write("-" * 80 + "\n")
                for file in data["files"]:
                    f.write(f"  • {file}\n")
                f.write("\n")
            else:
                f.write("RELEVANT FILES:\n")
                f.write("-" * 80 + "\n")
                f.write("  No files found.\n\n")
            
            f.write("\n")
        
        # Overall Summary
        f.write("=" * 80 + "\n")
        f.write("OVERALL SUMMARY\n")
        f.write("=" * 80 + "\n\n")
        
        total_schemes = sum(len(data['schemes']) for data in all_results.values())
        total_files = sum(len(data['files']) for data in all_results.values())
        total_matches = sum(data['total_matches'] for data in all_results.values())
        
        f.write(f"Total Business Profiles: {len(all_results)}\n")
        f.write(f"Total Unique Schemes Found: {total_schemes}\n")
        f.write(f"Total Unique Files Found: {total_files}\n")
        f.write(f"Total Document Chunks Matched: {total_matches}\n\n")
        
        f.write("Per-Business Breakdown:\n")
        f.write("-" * 80 + "\n")
        for business_name, data in all_results.items():
            f.write(f"{business_name}:\n")
            f.write(f"  Schemes: {len(data['schemes'])}\n")
            f.write(f"  Files: {len(data['files'])}\n")
            f.write(f"  Total matches: {data['total_matches']}\n\n")
        
        f.write("=" * 80 + "\n")
        f.write("END OF REPORT\n")
        f.write("=" * 80 + "\n")


def main():
    """
    Main function to process business profiles and retrieve relevant schemes.
    """
    # Initialize vectorstore
    print("=" * 80)
    print("Initializing ChromaDB connection...")
    vectorstore = get_chroma_vectorstore()
    collection_count = vectorstore._collection.count()
    print(f"Connected to collection: {config['TEST_CHROMA_COLLECTION']}")
    print(f"Total vectors in collection: {collection_count}")
    print("=" * 80)
    
    if collection_count == 0:
        error_msg = "⚠️  ERROR: Collection is empty! Please run ingestion_pipeline.py first."
        print(error_msg)
        return
    
    # Load business profiles
    profiles_file = ROOT_PATH / "Sample_Business_Profiles.txt"
    print(f"\nLoading business profiles from: {profiles_file}")
    business_profiles = load_business_profiles(profiles_file)
    print(f"Loaded {len(business_profiles)} business profiles\n")
    
    # Process each business profile
    all_results = {}
    
    for idx, profile in enumerate(business_profiles, 1):
        business_name = profile.get("business_name", f"Business {idx}")
        print("=" * 80)
        print(f"Processing Business {idx}: {business_name}")
        print("=" * 80)
        
        # Get relevant schemes (with debug for first business)
        debug_mode = (idx == 1)  # Debug first business only
        results = get_relevant_schemes(profile, vectorstore, k=15, debug=debug_mode)
        
        # Extract unique schemes and files
        unique_data = extract_unique_schemes(results)
        
        # Store results
        all_results[business_name] = {
            "profile": profile,
            "schemes": sorted(unique_data["schemes"]),
            "files": sorted(unique_data["files"]),
            "total_matches": len(results)
        }
        
        # Print results
        print(f"\nFound {len(results)} matching document chunks")
        print(f"Unique Schemes: {len(unique_data['schemes'])}")
        print(f"Unique Files: {len(unique_data['files'])}")
        
        if unique_data["schemes"]:
            print("\n📋 Relevant Schemes:")
            for scheme in sorted(unique_data["schemes"]):
                print(f"  • {scheme}")
        
        if unique_data["files"]:
            print("\n📄 Relevant Files:")
            for file in sorted(unique_data["files"]):
                print(f"  • {file}")
        
        print()
    
    # Summary
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    for business_name, data in all_results.items():
        print(f"\n{business_name}:")
        print(f"  Schemes: {len(data['schemes'])}")
        print(f"  Files: {len(data['files'])}")
        print(f"  Total matches: {data['total_matches']}")
    
    # Save results to file
    output_file = ROOT_PATH / "RelevantBusinessSchemes_Results.txt"
    print("\n" + "=" * 80)
    print(f"Saving results to: {output_file}")
    print("=" * 80)
    write_results_to_file(all_results, output_file)
    print(f"✅ Results successfully saved to {output_file}")
    
    return all_results


if __name__ == "__main__":
    results = main()
