# PoliSense — Zoho Form Design

Use this document to configure the Zoho Forms / Zoho Sheet columns for the PoliSense policy recommendation intake form. Every question maps directly to a retrieval filter or the semantic search query — the wording matters.

---

## Q1 — What is the name of your business?

**Response type:** Short text (single line)

**Why ask:** Used to label your recommendation report. No effect on which policies are found.

---

## Q2 — Which of the following best describes your industry?

**Response type:** Dropdown (single select)

**Options:**
1. Manufacturing
2. Information Technology (IT / Software)
3. Electronics and Hardware
4. Agriculture / Agro-Processing
5. Textiles and Apparel
6. Food Processing
7. Pharmaceuticals and Biotechnology
8. Automotive and Electric Vehicles
9. Renewable Energy and Clean Technology
10. Tourism and Hospitality
11. Healthcare and Medical Devices
12. Education and Skill Development
13. Logistics and Warehousing
14. Financial Services and Fintech
15. Defence and Aerospace
16. Construction and Real Estate
17. Retail and E-commerce
18. Chemicals and Petrochemicals
19. Mining and Minerals
20. Media and Entertainment
21. My industry is not listed here

**Why ask:** Industry is the strongest filter — it immediately excludes the vast majority of irrelevant schemes. Selecting the closest match ensures you only see policies targeted at your sector. "My industry is not listed here" returns pan-sector policies that apply to all businesses.

---

## Q3 — Tell us about your business and what you are hoping to achieve

**Response type:** Long text / paragraph (3–5 sentences recommended)

**Placeholder text to show in form:**
> *e.g., "We manufacture solar panels in Gujarat and are looking to expand our production facility. We want to understand what government support is available for capital investment and green energy manufacturing projects."*

**Why ask:** This is the most important question. Your answer is used to find policies that are semantically similar to your situation — the more specific you are, the better the recommendations. Mention your product/service, your current stage, and what you are trying to do next.

---

## Q4 — In which state are your business operations primarily located?

**Response type:** Dropdown (single select)

**Options (alphabetical):**
Andaman and Nicobar Islands, Andhra Pradesh, Arunachal Pradesh, Assam, Bihar, Chandigarh, Chhattisgarh, Dadra and Nagar Haveli and Daman and Diu, Delhi, Goa, Gujarat, Haryana, Himachal Pradesh, Jammu and Kashmir, Jharkhand, Karnataka, Kerala, Ladakh, Lakshadweep, Madhya Pradesh, Maharashtra, Manipur, Meghalaya, Mizoram, Nagaland, Odisha, Puducherry, Punjab, Rajasthan, Sikkim, Tamil Nadu, Telangana, Tripura, Uttar Pradesh, Uttarakhand, West Bengal, **We operate across multiple states / all of India**

**Why ask:** Most government incentive schemes are state-specific. Selecting your state ensures you see both state-level schemes (e.g., Karnataka Industrial Policy) and central/national schemes. "We operate across multiple states / all of India" returns only national-level policies.

---

## Q5 — What is your approximate annual turnover?

**Response type:** Dropdown (single select)

**Options:**
1. Less than ₹1 Crore
2. ₹1 Crore to ₹10 Crore
3. ₹10 Crore to ₹50 Crore
4. ₹50 Crore to ₹250 Crore
5. More than ₹250 Crore
6. I'd prefer not to say / Not sure

**Why ask:** Many schemes have eligibility caps based on turnover — MSME schemes, for example, are only available below ₹50 Crore. Your turnover determines which size tier of policies you qualify for. "Not sure" returns policies that apply to all business sizes.

---

## Q6 — Is your business registered under the Government of India's Startup India programme?

**Response type:** Single select (radio button)

**Options:** Yes / No

**Why ask:** If your business is DPIIT-recognised under Startup India, there is a distinct set of startup-specific schemes (from MeitY, state startup cells, etc.) that you may be eligible for, regardless of your turnover. This question overrides Q5 when "Yes" is selected.

---

## Q7 — What kind of support are you mainly looking for?

**Response type:** Dropdown (single select)

**Options:**
1. Funding to buy machinery, equipment, or expand my facility
2. Lower interest rates on business loans
3. Tax exemptions or tax rebates
4. Support with infrastructure — roads, power connection, water supply
5. Funding for research, innovation, or developing new products
6. Training and skill development programmes for my employees
7. Help with exporting my products to other countries
8. Access to new markets or marketing support
9. Subsidised land or help with building costs
10. Reduced electricity tariffs or utility cost support
11. Support for hiring new employees
12. Working capital or short-term credit support
13. Collateral-free loan guarantees
14. I'm not sure — just show me what's available

**Why ask:** Different schemes serve different purposes. Selecting the type of support you need narrows the results to the most relevant policies. "I'm not sure" removes this filter entirely and shows a broader set of results.

---

## Q8 — Is there anything else that would help us find the right schemes for you? (Optional)

**Response type:** Long text / paragraph (optional)

**Placeholder text to show in form:**
> *e.g., "We already have land but need power infrastructure support. We have an export obligation under our industrial licence. We are located in a Special Economic Zone."*

**Why ask:** Optional — only fill this if you have specific details that don't fit the questions above. This information is added to the search and can improve the relevance of results.

---

## Internal Mapping Reference (for the development team)

The table below shows how each form option maps to the internal retrieval filter value. **Do not show this to end users.**

### Q2 → industry filter

| Form Option | Internal Tag |
|---|---|
| Manufacturing | `Manufacturing` |
| Information Technology (IT / Software) | `Information Technology` |
| Electronics and Hardware | `Electronics and Hardware` |
| Agriculture / Agro-Processing | `Agriculture and Agro-Processing` |
| Textiles and Apparel | `Textile and Apparel` |
| Food Processing | `Food Processing` |
| Pharmaceuticals and Biotechnology | `Pharmaceuticals and Biotech` |
| Automotive and Electric Vehicles | `Automotive and EV` |
| Renewable Energy and Clean Technology | `Renewable Energy and Clean Tech` |
| Tourism and Hospitality | `Tourism and Hospitality` |
| Healthcare and Medical Devices | `Healthcare and Medical Devices` |
| Education and Skill Development | `Education and Skill Development` |
| Logistics and Warehousing | `Logistics and Warehousing` |
| Financial Services and Fintech | `Financial Services and Fintech` |
| Defence and Aerospace | `Defense and Aerospace` |
| Construction and Real Estate | `Construction and Real Estate` |
| Retail and E-commerce | `Retail and E-commerce` |
| Chemicals and Petrochemicals | `Chemical and Petrochemical` |
| Mining and Minerals | `Mining and Minerals` |
| Media and Entertainment | `Media and Entertainment` |
| My industry is not listed here | *(no filter applied)* |

### Q5 → business_size filter (base value, overridden by Q6)

| Form Option | Internal Tag |
|---|---|
| Less than ₹1 Crore | `Micro` |
| ₹1 Crore to ₹10 Crore | `Small` |
| ₹10 Crore to ₹50 Crore | `Medium` |
| ₹50 Crore to ₹250 Crore | `Large` |
| More than ₹250 Crore | `Mega` |
| I'd prefer not to say / Not sure | *(no filter applied)* |

**Q6 override:** If Q6 = "Yes" → `business_size = "Startup"` (Q5 value is discarded).

### Q7 → category filter

| Form Option | Internal Tag |
|---|---|
| Funding to buy machinery, equipment, or expand my facility | `Capital Subsidy` |
| Lower interest rates on business loans | `Interest Subvention` |
| Tax exemptions or tax rebates | `Tax Incentive` |
| Support with infrastructure — roads, power connection, water supply | `Infrastructure Support` |
| Funding for research, innovation, or developing new products | `R&D and Innovation Grant` |
| Training and skill development programmes for my employees | `Skill Development` |
| Help with exporting my products to other countries | `Export Promotion` |
| Access to new markets or marketing support | `Market Access and Marketing Support` |
| Subsidised land or help with building costs | `Land and Building Concession` |
| Reduced electricity tariffs or utility cost support | `Power and Utility Concession` |
| Support for hiring new employees | `Employment Generation` |
| Working capital or short-term credit support | `Working Capital Assistance` |
| Collateral-free loan guarantees | `Credit Guarantee` |
| I'm not sure — just show me what's available | *(no filter applied)* |

### Q4 geography note

The exact state name from the dropdown is passed directly to the retriever (ILIKE substring match). "We operate across multiple states / all of India" → `"National"` (matches the `'National'` fallback tag in the DB, returning all pan-India policies).
