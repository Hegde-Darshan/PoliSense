# # sample_profiles.py
# # ─────────────────────────────────────────────────────────────────────────────
# # Sample business profiles covering all meaningful filter combinations
# # from the current DB (3 industries × 1 geography × 9 size tiers).
# # Use these for testing retrieve_policies() end-to-end.
# # ─────────────────────────────────────────────────────────────────────────────

# SAMPLE_PROFILES = [

#     # ── EV / Automotive ───────────────────────────────────────────────────────

#     {
#         "business_name": "VoltEdge Battery Pvt Ltd",
#         "legal_entity_type": "Private Limited",
#         "industry": "Automotive",
#         "sub_industry": "EV Battery Manufacturing",
#         "employee_count": 8,
#         "turnover_range": "INR 1–2 Cr",
#         "year_of_establishment": 2023,
#         "geography": {"country": "India", "state": "Karnataka", "district": "Bangalore"},
#         "ownership_type": "Private",
#         "registration": {"msme": True, "udyam_number": "KA2023EV0001"},
#         "growth_stage": "Startup",
#         "special_attributes": ["Startup", "Deep Tech"],
#         # Expected filters: industry=Automotive/Energy Storage, geography=Karnataka, size=Startup
#     },

#     {
#         "business_name": "Prakash Auto Components",
#         "legal_entity_type": "Proprietorship",
#         "industry": "Automotive",
#         "sub_industry": "EV Components",
#         "employee_count": 9,
#         "turnover_range": "INR 50L–1 Cr",
#         "year_of_establishment": 2020,
#         "geography": {"country": "India", "state": "Karnataka", "district": "Mysuru"},
#         "ownership_type": "Private",
#         "registration": {"msme": True},
#         "growth_stage": "Early Stage",
#         # Expected filters: industry=Automotive/Energy Storage, geography=Karnataka, size=Micro Enterprise
#     },

#     {
#         "business_name": "ChargeFast Solutions Pvt Ltd",
#         "legal_entity_type": "Private Limited",
#         "industry": "Automotive",
#         "sub_industry": "Charging Infrastructure",
#         "employee_count": 35,
#         "turnover_range": "INR 5–10 Cr",
#         "year_of_establishment": 2021,
#         "geography": {"country": "India", "state": "Karnataka", "district": "Bangalore"},
#         "ownership_type": "Private",
#         "registration": {"msme": True},
#         "growth_stage": "Growth",
#         # Expected filters: industry=Automotive/Energy Storage, geography=Karnataka, size=Small Enterprise
#     },

#     {
#         "business_name": "IndraEV Manufacturing Ltd",
#         "legal_entity_type": "Private Limited",
#         "industry": "Automotive",
#         "sub_industry": "Electric Vehicles",
#         "employee_count": 180,
#         "turnover_range": "INR 100–250 Cr",
#         "year_of_establishment": 2018,
#         "geography": {"country": "India", "state": "Karnataka", "district": "Tumkur"},
#         "ownership_type": "Private",
#         "registration": {"msme": False},
#         "growth_stage": "Expansion",
#         # Expected filters: industry=Automotive/Energy Storage, geography=Karnataka, size=Medium Enterprise
#     },

#     {
#         "business_name": "KarnatakaEV Industries Ltd",
#         "legal_entity_type": "Public Limited",
#         "industry": "Automotive",
#         "sub_industry": "Electric Vehicles",
#         "employee_count": 420,
#         "turnover_range": "INR 500–750 Cr",
#         "year_of_establishment": 2015,
#         "geography": {"country": "India", "state": "Karnataka", "district": "Belgaum"},
#         "ownership_type": "Private",
#         "registration": {"msme": False},
#         "growth_stage": "Mature",
#         # Expected filters: industry=Automotive/Energy Storage, geography=Karnataka, size=Large Enterprise
#     },

#     {
#         "business_name": "HydroPower Mobility Corp",
#         "legal_entity_type": "Public Limited",
#         "industry": "Automotive",
#         "sub_industry": "Hydrogen Based Vehicles",
#         "employee_count": 900,
#         "turnover_range": "INR 750–1000 Cr",
#         "year_of_establishment": 2012,
#         "geography": {"country": "India", "state": "Karnataka"},
#         "ownership_type": "Private",
#         "registration": {"msme": False},
#         "growth_stage": "Mature",
#         # Expected filters: industry=Automotive/Energy Storage, geography=Karnataka, size=Mega Enterprise
#     },

#     # ── Clean Mobility ────────────────────────────────────────────────────────

#     {
#         "business_name": "GreenFleet Mobility Pvt Ltd",
#         "legal_entity_type": "Private Limited",
#         "industry": "Clean Mobility",
#         "sub_industry": "Electric Mobility",
#         "employee_count": 22,
#         "turnover_range": "INR 2–5 Cr",
#         "year_of_establishment": 2023,
#         "geography": {"country": "India", "state": "Karnataka", "district": "Bangalore"},
#         "ownership_type": "Women-Owned",
#         "registration": {"msme": True},
#         "growth_stage": "Startup",
#         "special_attributes": ["Startup", "Women-led", "Sustainable"],
#         # Expected filters: industry=Clean Mobility, geography=Karnataka, size=Startup
#         # Special signals: women_owned
#     },

#     {
#         "business_name": "Navya Clean Transport LLP",
#         "legal_entity_type": "LLP",
#         "industry": "Clean Mobility",
#         "sub_industry": "Zero Emission Transport",
#         "employee_count": 65,
#         "turnover_range": "INR 10–25 Cr",
#         "year_of_establishment": 2019,
#         "geography": {"country": "India", "state": "Karnataka", "district": "Hubli"},
#         "ownership_type": "Private",
#         "registration": {"msme": True},
#         "growth_stage": "Growth",
#         # Expected filters: industry=Clean Mobility, geography=Karnataka, size=Small Enterprise
#     },

#     {
#         "business_name": "BharatMobility Solutions Ltd",
#         "legal_entity_type": "Public Limited",
#         "industry": "Clean Mobility",
#         "sub_industry": "Green Transport",
#         "employee_count": 350,
#         "turnover_range": "INR 300–500 Cr",
#         "year_of_establishment": 2016,
#         "geography": {"country": "India", "state": "Karnataka"},
#         "ownership_type": "Private",
#         "registration": {"msme": False},
#         "growth_stage": "Expansion",
#         # Expected filters: industry=Clean Mobility, geography=Karnataka, size=Medium Enterprise
#     },

#     # ── ESDM / Electronics ────────────────────────────────────────────────────

#     {
#         "business_name": "NeuralChip Technologies Pvt Ltd",
#         "legal_entity_type": "Private Limited",
#         "industry": "Electronics",
#         "sub_industry": "Semiconductors",
#         "employee_count": 12,
#         "turnover_range": "INR 1–2 Cr",
#         "year_of_establishment": 2022,
#         "geography": {"country": "India", "state": "Karnataka", "district": "Bangalore"},
#         "ownership_type": "Private",
#         "registration": {"msme": True},
#         "growth_stage": "Startup",
#         "special_attributes": ["Startup", "Deep Tech", "IP-driven"],
#         # Expected filters: industry=ESDM, geography=Karnataka, size=Startup
#     },

#     {
#         "business_name": "MedSense Electronics Pvt Ltd",
#         "legal_entity_type": "Private Limited",
#         "industry": "Electronics",
#         "sub_industry": "Medical Electronics",
#         "employee_count": 18,
#         "turnover_range": "INR 2–5 Cr",
#         "year_of_establishment": 2021,
#         "geography": {"country": "India", "state": "Karnataka", "district": "Bangalore"},
#         "ownership_type": "Women-Owned",
#         "registration": {"msme": True},
#         "growth_stage": "Early Stage",
#         "special_attributes": ["Women-led", "Innovative", "Export-oriented"],
#         # Expected filters: industry=ESDM, geography=Karnataka, size=Micro Enterprise
#         # Special signals: women_owned, export_oriented
#     },

#     {
#         "business_name": "Viveka PCB Solutions",
#         "legal_entity_type": "Proprietorship",
#         "industry": "Electronics",
#         "sub_industry": "PCBs",
#         "employee_count": 38,
#         "turnover_range": "INR 5–10 Cr",
#         "year_of_establishment": 2017,
#         "geography": {"country": "India", "state": "Karnataka", "district": "Mysuru"},
#         "ownership_type": "Private",
#         "registration": {"msme": True},
#         "growth_stage": "Stable",
#         # Expected filters: industry=ESDM, geography=Karnataka, size=Small Enterprise
#     },

#     {
#         "business_name": "Drona Defence Systems Pvt Ltd",
#         "legal_entity_type": "Private Limited",
#         "industry": "Electronics",
#         "sub_industry": "Defence & Strategic Electronics",
#         "employee_count": 160,
#         "turnover_range": "INR 100–250 Cr",
#         "year_of_establishment": 2014,
#         "geography": {"country": "India", "state": "Karnataka", "district": "Bangalore"},
#         "ownership_type": "Private",
#         "registration": {"msme": False},
#         "growth_stage": "Growth",
#         # Expected filters: industry=ESDM, geography=Karnataka, size=Medium Enterprise
#     },

#     {
#         "business_name": "TeleMatrix Networks Ltd",
#         "legal_entity_type": "Public Limited",
#         "industry": "Electronics",
#         "sub_industry": "Telecom Systems",
#         "employee_count": 480,
#         "turnover_range": "INR 500–750 Cr",
#         "year_of_establishment": 2010,
#         "geography": {"country": "India", "state": "Karnataka"},
#         "ownership_type": "Private",
#         "registration": {"msme": False},
#         "growth_stage": "Mature",
#         # Expected filters: industry=ESDM, geography=Karnataka, size=Large Enterprise
#     },

#     # ── Out-of-DB profiles (filters should be partially/fully skipped) ─────────

#     {
#         "business_name": "IdeaSpark Innovations Pvt Ltd",
#         "legal_entity_type": "Private Limited",
#         "industry": "Technology",
#         "sub_industry": "AI & Machine Learning",
#         "employee_count": 18,
#         "turnover_range": "INR 1–2 Cr",
#         "year_of_establishment": 2022,
#         "geography": {"country": "India", "state": "Telangana", "district": "Hyderabad"},
#         "ownership_type": "Private",
#         "registration": {"msme": True},
#         "growth_stage": "Early Stage",
#         "special_attributes": ["Startup", "Youth-led"],
#         # Expected filters: {} — industry=None (AI not in DB), geography=None (Telangana not in DB)
#         # size=Startup but no industry/geography to filter on
#     },

#     {
#         "business_name": "GreenHarvest Foods LLP",
#         "legal_entity_type": "LLP",
#         "industry": "Food Processing",
#         "sub_industry": "Agri Processing",
#         "employee_count": 120,
#         "turnover_range": "INR 50–100 Cr",
#         "year_of_establishment": 2014,
#         "geography": {"country": "India", "state": "Punjab", "district": "Ludhiana"},
#         "ownership_type": "Private",
#         "registration": {"msme": True},
#         "growth_stage": "Expansion",
#         # Expected filters: {business_size: Medium Enterprise} only
#         # industry=None (food not in DB), geography=None (Punjab not in DB)
#     },

#     {
#         "business_name": "Sakhi Handloom Collective",
#         "industry": "Textiles",
#         "sub_industry": "Handloom",
#         "employee_count": 25,
#         "geography": {"state": "Odisha", "district": "Mayurbhanj"},
#         "ownership_type": "Women-Owned",
#         "special_attributes": ["Rural", "SHG-based"],
#         # Expected filters: {business_size: Small Enterprise}
#         # Special signals: women_owned, rural, shg
#     },
# ]


# if __name__ == "__main__":
#     import sys
#     from pathlib import Path
#     sys.path.insert(0, str(Path(__file__).parent.parent))

#     from RetrievalPipeline.profile_mappings import extract_filters

#     print(f"{'─'*65}")
#     print(f"  Testing {len(SAMPLE_PROFILES)} profiles against rule-based extractor")
#     print(f"{'─'*65}")

#     for p in SAMPLE_PROFILES:
#         filters = extract_filters(p)
#         signals = filters.pop("_special_signals", [])
#         print(f"\n  {p['business_name']}")
#         print(f"    industry input : {p.get('industry')} / {p.get('sub_industry')}")
#         print(f"    state input    : {p.get('geography', {}).get('state')}")
#         print(f"    employees      : {p.get('employee_count')}")
#         print(f"    → filters      : {filters}")
#         if signals:
#             print(f"    → signals      : {signals}")