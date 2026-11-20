"""Build G2 v2 (relevance labels) for the Supabase corpus.

Profiles are reused unchanged from ../g1_profiles.jsonl. Labels reference row indices in
corpus.json (this folder; a read-only dump of the Supabase `policies` table, ordered by
parent_policy_name, policy_name, incentive_name) and are converted here to exact
(parent_policy_name, incentive_name) keys. When several rows share a key, the highest grade wins.

Usage: python evals/datasets/v2/build_g2_v2.py
"""
import json
import os
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
corpus = json.load(open(os.path.join(HERE, "corpus.json"), encoding="utf-8"))
g1 = [json.loads(l) for l in open(os.path.join(HERE, "..", "g1_profiles.jsonl"), encoding="utf-8") if l.strip()]

# profile_id -> [(row_index, grade, rationale)]
L = {
    # ---------------------------------------------------------------- non-Karnataka: only the 2 National MSE-CDP rows can match
    "P001": [(302, 1, "MSE-CDP common facility grant needs a cluster of 10+ MSEs; firm wants own machinery.")],
    "P002": [
        (154, 3, "KESDM R&D grant 25% for ESDM startups under 7 years; fabless chip design fits."),
        (151, 3, "KESDM patent filing reimbursement; matches patent need."),
        (156, 3, "KESDM prototyping cost reimbursement 50% for startups; chip prototypes."),
        (228, 2, "IT policy R&D reimbursement 40%; needs IT/ITeS unit status."),
        (232, 2, "IT policy patent reimbursement; applies to IT/ITeS units."),
        (157, 1, "KESDM quality certification reimbursement; not stated need."),
        (148, 1, "KESDM interest subsidy for startups; debt not grant."),
        (152, 1, "KESDM PF/ESI for companies under 2 years; age unclear, not stated need."),
        (149, 1, "KESDM international marketing; not stated need."),
        (7, 1, "Social-impact tech pilot grant open to KA startups; different need."),
        (22, 1, "A&D/ER&D conditional R&D grant; aimed at large ER&D entities."),
        (193, 1, "Reimburses startups using GCC labs; indirect R&D support."),
    ],
    "P003": [
        (196, 2, "Capital subsidy for small industries; modernisation may not count as new/expansion."),
        (329, 2, "RAMP technology upgradation support for MSMEs; vague scheme details."),
        (199, 2, "Export certification refund 50% for MSMEs with IEC; export need."),
        (325, 2, "RAMP marketing assistance for trade fairs; export push."),
        (324, 2, "RAMP export awareness and training programmes."),
        (326, 2, "Certification charge reimbursement for exporters."),
        (327, 1, "Export awards; recognition only."),
        (205, 1, "Industry 5.0 subsidy; tangential to machine upgrade."),
        (202, 1, "Quality certification reimbursement; not stated need."),
        (200, 1, "Power subsidy for micro/small in zones 1-2; not stated need."),
        (197, 1, "Electricity tax exemption; minor."),
        (328, 1, "Credit guarantee for MSEs; financing, not stated need."),
        (302, 1, "Cluster CFC grant needs 10+ units; coir cluster possible."),
    ],
    "P004": [
        (204, 2, "SC/ST MSME package (land, loan subsidy, seed capital); not yarn or marketing."),
        (325, 2, "RAMP marketing assistance for fairs; market linkage need."),
        (201, 2, "Public procurement preference for MSEs; a market access route."),
        (324, 1, "Export awareness training; weak fit."),
        (328, 1, "Credit guarantee for women-owned MSEs; not stated need."),
        (302, 1, "Cluster CFC grant; weaver group could form a cluster."),
        (195, 1, "Micro capital subsidy; not stated need."),
    ],
    "P005": [
        (196, 3, "Capital subsidy for small food/manufacturing units, higher for women; expansion need."),
        (57, 2, "Agri-business 2015 investment subsidy 35% VFA for MSMEs; older policy."),
        (328, 2, "Credit guarantee enhancement for women-owned MSEs; cheaper credit."),
        (56, 1, "6% interest subsidy only for micro units; company is small."),
        (54, 1, "Stamp duty exemption on loan documents; minor."),
        (55, 1, "Electricity tax exemption; minor."),
        (197, 1, "Electricity tax exemption for MSMEs; minor."),
        (198, 1, "Stamp duty exemption for MSMEs; minor."),
        (200, 1, "Power subsidy for micro/small; minor."),
        (203, 1, "Land conversion reimbursement; minor."),
        (202, 1, "FSSAI/quality certification reimbursement; not stated need."),
        (199, 1, "Export certification refund; not stated need."),
        (306, 1, "Food lab analysis subsidy; tangential."),
        (308, 1, "Food technology licence fee subsidy; tangential."),
        (305, 1, "Buyer-seller meets; marketing, not stated need."),
        (311, 1, "Free trade fair stall; marketing, not stated need."),
        (307, 1, "Food quality/organic certification support; tangential."),
        (322, 1, "Export incentives for millets; not stated need."),
    ],
    "P006": [
        (110, 3, "Clean Mobility capital subsidy for MSMEs, up to Rs 10 crore for medium; new EV line."),
        (124, 2, "EV policy 2017 investment subsidy for MSMEs; superseded by 2025-30 policy."),
        (123, 2, "EV policy 2017 in-plant training stipend; training need, older policy."),
        (194, 2, "Industrial policy base subsidy for medium units; sector policy may apply instead."),
        (165, 2, "ESDM scheme 20% subsidy on plant and machinery; BMS is electronics."),
        (162, 1, "ESDM 1% PLI; not stated need."),
        (111, 1, "Concessional registration for MSMEs; minor."),
        (112, 1, "Stamp duty exemption for MSMEs; minor."),
        (113, 1, "Electricity tax exemption for MSMEs; minor."),
        (114, 1, "Land conversion reimbursement; minor."),
    ],
    "P007": [],
    "P008": [  # geo null: Karnataka allowed, never 3
        (213, 2, "Industrial policy PLI option for large pharma units; geography open."),
        (207, 2, "Booster for co-locating R&D with manufacturing; R&D interest."),
        (208, 1, "Capital expenditure subsidy; not stated need."),
        (84, 1, "Biotech policy PLI; API chemistry is not biotech."),
        (81, 1, "Biotech international marketing reimbursement; weak fit."),
        (82, 1, "Biotech patent reimbursement; biotech products only."),
        (325, 1, "RAMP trade fair assistance; export promotion, KA only."),
        (326, 1, "Certification reimbursement for exporters; KA only."),
    ],
    "P009": [
        (167, 2, "FPO growth-phase working capital and infra support; producer company may qualify as FPO."),
        (169, 2, "FPO expansion phase interest subvention and credit guarantee."),
        (57, 2, "Agri/food processing investment subsidy; cold storage capex."),
        (56, 2, "6% interest subsidy for micro food units."),
        (195, 2, "Micro capital subsidy covers food processing."),
        (328, 2, "Credit guarantee for women-owned MSEs; working capital."),
        (168, 1, "FPO formation grant; may be past formation stage."),
        (170, 1, "FPO market access and branding parity; not stated need."),
        (58, 1, "Market fee exemption and cold storage site rebate; partial fit."),
        (310, 1, "Free agri-export training; members training, export focus."),
        (319, 1, "Subsidised cold storage space; organic produce only."),
        (302, 1, "Cluster CFC grant; possible shared cold storage."),
    ],
    "P010": [
        (302, 3, "MSE-CDP common facility grant 60-80% for clusters; silk cluster facility need."),
        (196, 2, "Capital subsidy for small units; loom modernisation may not qualify."),
        (329, 2, "RAMP technology upgradation support."),
        (199, 2, "Export certification refund; export need."),
        (325, 2, "RAMP trade fair assistance; export need."),
        (326, 2, "Certification reimbursement for exporters."),
        (324, 1, "Export awareness training; minor."),
        (303, 1, "Infrastructure development grant for industrial areas; government-led."),
        (205, 1, "Industry 5.0 subsidy; tangential."),
        (202, 1, "Quality certification reimbursement; minor."),
    ],
    "P011": [
        (328, 2, "Credit guarantee for women-owned micro units; small loan need."),
        (195, 1, "Micro capital subsidy; needs plant investment, home unit."),
        (325, 1, "RAMP trade fair assistance; marketing but small scale."),
        (201, 1, "Public procurement preference; unlikely route for cosmetics."),
        (202, 1, "Quality certification reimbursement; minor."),
        (329, 1, "RAMP competitiveness support; vague."),
        (304, 1, "Nipuna PPP training co-funding; aimed at training partners."),
    ],
    "P012": [  # geo null
        (213, 2, "Industrial policy PLI for large manufacturers; geography open."),
        (208, 2, "Capital expenditure subsidy for new large plant; geography open."),
        (211, 1, "Employment booster; needs 3x minimum employment."),
        (212, 1, "Stamp duty exemption; minor."),
        (214, 1, "Land conversion reimbursement; minor."),
        (32, 1, "A&D capital subsidy; tooling supplier, not A&D manufacturer."),
        (38, 1, "A&D turnover-based investment subsidy; sector mismatch."),
        (304, 1, "Nipuna PPP skill training co-funding."),
        (47, 1, "A&D in-plant training stipend; sector mismatch."),
    ],
    "P013": [
        (325, 2, "RAMP trade fair assistance; export promotion."),
        (324, 2, "RAMP export training programmes."),
        (326, 2, "Certification reimbursement for exporters."),
        (199, 2, "Export certification refund for MSMEs with IEC."),
        (329, 2, "RAMP technology upgradation support."),
        (327, 1, "Export awards; recognition only."),
        (196, 1, "Small capital subsidy; not stated need."),
        (311, 1, "KAPPEC free fair stall for agri exporters; coir pith borderline."),
        (310, 1, "Free agri-export training."),
        (309, 1, "APEDA pack-house charge subsidy; not applicable to coir."),
    ],
    "P014": [
        (57, 2, "Agri/food processing investment subsidy; chiller and plant capex."),
        (196, 2, "Small capital subsidy covers food processing; coop status unclear."),
        (328, 2, "Credit guarantee for women-owned units; cheaper credit."),
        (56, 1, "Interest subsidy only for micro units."),
        (169, 1, "FPO expansion finance; dairy coop not an FPO."),
        (167, 1, "FPO growth-phase working capital; dairy coop not an FPO."),
        (58, 1, "Market fee exemption and cold storage rebate; partial fit."),
    ],
    "P015": [  # geo null
        (249, 1, "Grid support charge exemption for off-grid premises solar; partial fit."),
        (246, 1, "MNRE CFA extension for RE projects; aimed at developers."),
        (253, 1, "Tariff rebate for solar-powered EV charging; adjacent."),
        (328, 1, "Credit guarantee for green investments; KA only, green finance."),
    ],
    "P016": [
        (95, 1, "Biotech incubation centre capital grant; outside Bengaluru, biotech only."),
        (78, 1, "AVGC TBI funding for academic institutions in emerging clusters."),
        (31, 1, "A&D TBIC support; sector mismatch."),
        (193, 1, "GCC lab utilisation for startups; indirect."),
    ],
    "P017": [], "P018": [], "P019": [],
    "P020": [(302, 1, "MSE-CDP CFC grant allows FPOs but needs 10+ units; single FPO.")],
    "P021": [(302, 1, "MSE-CDP CFC grant for artisan clusters; firm needs export help.")],
    "P022": [], "P023": [],
    "P024": [(302, 1, "MSE-CDP CFC grant for coir clusters; unit wants own ratts and training.")],
    "P025": [
        (72, 3, "AVGC production grant for game development; next game need."),
        (66, 3, "AVGC international trade show reimbursement; GDC participation."),
        (63, 2, "AVGC early-stage startup support; requires under 2 years of operation."),
        (68, 2, "KITVEN AVGC venture fund; equity, not grant."),
        (64, 1, "AVGC IT hardware subsidy; not stated need."),
        (65, 1, "AVGC rental reimbursement; not stated need."),
        (67, 1, "AVGC IP protection reimbursement; not stated need."),
        (76, 1, "AVGC PF/ESI reimbursement; not stated need."),
        (77, 1, "AVGC training fee reimbursement; not stated need."),
        (75, 1, "AVGC quality certification; not stated need."),
    ],
    "P026": [
        (97, 3, "Biotech startup patent reimbursement 100%; needs physical incubation."),
        (92, 2, "Biotech prototyping cost reimbursement (MSME rows); lab-to-product support."),
        (90, 2, "Biotech MSME patent reimbursement 75%."),
        (96, 1, "Biotech startup marketing reimbursement; not stated need."),
        (93, 1, "Biotech quality certification; useful for diagnostics later."),
    ],
    "P027": [
        (25, 3, "A&D reimbursement for AS9100 and NADCAP certification; exact need."),
        (28, 3, "A&D investment subsidy for micro/small; 5-axis CNC purchase."),
        (26, 2, "A&D interest subsidy on technology upgradation loans."),
        (196, 2, "Industrial policy small capital subsidy; sector policy likely applies first."),
        (202, 2, "Industrial policy quality certification reimbursement."),
        (24, 1, "Electricity tax exemption and power subsidy; minor."),
        (23, 1, "Stamp duty exemption; minor."),
        (29, 1, "Land conversion reimbursement; minor."),
        (31, 1, "Technology adoption subsidy; minor."),
    ],
    "P028": [
        (187, 3, "GCC rental assistance for new GCCs beyond Bengaluru; Mysuru rent need."),
        (185, 3, "GCC recruitment reimbursement beyond Bengaluru."),
        (189, 3, "GCC local talent skilling reimbursement."),
        (174, 2, "GCC EPF reimbursement for new employees beyond Bengaluru."),
        (192, 2, "GCC internet expense reimbursement beyond Bengaluru."),
        (240, 2, "IT policy rental assistance; GCC may register as ITeS."),
        (238, 2, "IT policy recruitment assistance beyond Bengaluru; ITeS registration needed."),
        (242, 2, "IT policy skilling reimbursement beyond Bengaluru."),
        (304, 2, "Nipuna PPP training co-funding; local talent training."),
        (183, 1, "Property tax reimbursement; only if owning property."),
        (186, 1, "Electricity duty reimbursement; minor."),
        (182, 1, "Power tariff concession; minor."),
        (180, 1, "Internship stipend reimbursement; minor."),
        (184, 1, "Quality certification reimbursement; minor."),
        (176, 1, "Innovation lab capex grant; not stated need."),
        (230, 1, "IT policy EPF reimbursement; overlaps GCC benefit."),
        (0, 1, "ER&D GCC rental reimbursement; insurance GCC is not ER&D."),
        (1, 1, "ER&D GCC recruitment assistance; insurance GCC is not ER&D."),
    ],
    "P029": [
        (229, 2, "IT policy electricity duty reimbursement for new units beyond Bengaluru; data centre may qualify."),
        (236, 2, "Industrial power tariff option for IT units; power need."),
        (237, 1, "Property tax reimbursement; land need, partial."),
        (249, 1, "Off-grid premises solar grid charge exemption; partial fit."),
    ],
    "P030": [
        (297, 3, "Homestay support: domestic tariffs and no land conversion; registered homestay."),
        (296, 3, "Agri tourism project support; planned agri-tourism experience."),
        (286, 2, "Tourism capital subsidy, extra 5% for women; category fit unclear."),
        (285, 1, "Tourism sustainability assistance; not stated need."),
        (298, 1, "2020-26 tourism capital subsidy; superseded."),
        (300, 1, "2020-26 interest subsidy for agri tourism; superseded, loan unclear."),
        (320, 1, "Organic eco agri tourism incentives; organic farms only."),
    ],
    "P031": [
        (286, 3, "Tourism capital subsidy up to Rs 10 crore; Hampi is in Kalyana Karnataka (+5%)."),
        (292, 3, "5% interest subsidy for heritage hotels."),
        (298, 2, "2020-26 capital subsidy; superseded guidelines."),
        (300, 2, "2020-26 interest subsidy for heritage projects; superseded."),
        (289, 1, "Stamp duty exemption; minor."),
        (288, 1, "Registration charge exemption; minor."),
        (294, 1, "Land conversion reimbursement; minor."),
        (291, 1, "Industry status and single window; minor."),
        (285, 1, "Sustainability assistance; minor."),
    ],
    "P032": [
        (274, 3, "Space policy testing cost reimbursement; space qualification testing."),
        (273, 3, "Space policy R&D cost reimbursement 50% up to Rs 75 lakh."),
        (268, 2, "Space policy quality/standards certification reimbursement."),
        (154, 2, "KESDM R&D grant for electronics startups under 7 years."),
        (269, 1, "Technology acquisition reimbursement; not stated need."),
        (271, 1, "IP registration reimbursement; not stated need."),
        (270, 1, "Global marketing reimbursement; not stated need."),
        (272, 1, "PF/ESI reimbursement; not stated need."),
        (279, 1, "Training cost reimbursement; not stated need."),
        (263, 1, "Capital subsidy; not stated need."),
        (267, 1, "Rent reimbursement; not stated need."),
        (282, 1, "Grant to build a testing centre; aimed at developers."),
        (46, 1, "Defence testing infrastructure grant; aimed at facility builders."),
        (22, 1, "A&D R&D grant; aimed at large ER&D entities."),
    ],
    "P033": [
        (118, 3, "Cyber security R&D matching grant for KITS startups working with academia."),
        (116, 3, "Cyber security internship stipend reimbursement."),
        (117, 2, "Preferential procurement and pilots for KA cyber startups."),
        (233, 2, "IT policy internship stipend reimbursement."),
        (119, 1, "Cyber audit reimbursement; different need."),
        (228, 1, "IT policy R&D reimbursement; not academia-specific."),
        (231, 1, "IT events reimbursement for beyond-Bengaluru applicants; minor."),
        (230, 1, "IT EPF reimbursement for new units beyond Bengaluru; minor."),
        (10, 1, "Applied research in academia grant; applicant must be the college."),
    ],
    "P034": [
        (196, 3, "Small capital subsidy for manufacturing capacity expansion."),
        (227, 1, "MSME sustainability equipment subsidy; tangential."),
        (197, 1, "Electricity tax exemption; minor."),
        (198, 1, "Stamp duty exemption; minor."),
        (200, 1, "Power subsidy for micro/small; minor."),
        (203, 1, "Land conversion reimbursement; minor."),
        (57, 1, "Agri-business 2015 investment subsidy; bio-inputs borderline."),
    ],
    "P035": [
        (204, 3, "SC/ST MSME package: 75% land cost subsidy, loan subsidy, seed capital."),
        (195, 3, "Micro capital subsidy, 35% for special category; new machines."),
        (198, 2, "Stamp duty exemption on shed lease/sale deeds."),
        (203, 1, "Land conversion reimbursement; minor."),
        (200, 1, "Power subsidy for micro units; minor."),
        (197, 1, "Electricity tax exemption; minor."),
        (201, 1, "Public procurement preference; minor."),
    ],
    "P036": [
        (208, 3, "Capital expenditure subsidy up to 25% VFA for large units."),
        (213, 3, "PLI option up to 2.5% of sales for 7 years."),
        (211, 3, "Employment booster for 3x+ minimum jobs; 1500 workers."),
        (215, 2, "Women workforce booster; garment units often exceed 50% women."),
        (212, 2, "Stamp duty exemption outside zone 3."),
        (214, 2, "Land conversion reimbursement outside zone 3."),
        (209, 1, "Concessional registration; minor."),
        (206, 1, "Dormitory subsidy only for ultra mega (>1000 crore)."),
        (226, 1, "Sustainability incentives for large units; tangential."),
    ],
    "P037": [
        (103, 3, "Clean Mobility 25% capital subsidy up to Rs 10 lakh per fast charger."),
        (142, 2, "EV policy 2017 charging station subsidy; superseded."),
        (253, 1, "Tariff rebate if chargers are solar-powered."),
        (102, 1, "Battery swapping station subsidy; different infrastructure."),
    ],
    "P038": [
        (165, 3, "ESDM scheme 20% subsidy on plant and machinery."),
        (160, 3, "ESDM land subsidy 25% outside Bengaluru."),
        (161, 3, "ESDM power tariff reimbursement Rs 1/unit."),
        (159, 3, "ESDM electricity duty exemption 5 years."),
        (162, 3, "ESDM 1% PLI on turnover."),
        (147, 3, "KESDM tailor-made package for mega enterprises above Rs 250 crore."),
        (48, 3, "ESDM capital subsidy on P&M and land (copy under A&D parent)."),
        (164, 2, "ESDM stamp duty and registration reimbursement."),
        (163, 2, "ESDM land conversion reimbursement."),
        (49, 2, "ESDM power tariff and electricity duty (copy under A&D parent)."),
        (50, 2, "ESDM PLI (copy under A&D parent)."),
        (51, 2, "ESDM stamp duty and land conversion (copy under A&D parent)."),
        (144, 2, "KESDM anchor capital subsidy in greenfield clusters; first two anchors only."),
        (210, 2, "Industrial policy customised package for sunrise sectors."),
        (208, 2, "Industrial policy capex subsidy; ESDM scheme likely applies instead."),
        (213, 2, "Industrial policy PLI; ESDM scheme likely applies instead."),
        (146, 1, "KESDM stamp duty exemption; minor."),
        (155, 1, "KESDM land conversion; minor."),
        (153, 1, "KESDM industrial power tariff; minor."),
        (158, 1, "KESDM ETP subsidy; minor."),
    ],
    "P039": [
        (302, 3, "MSE-CDP CFC grant for a shared testing lab with 12+ cluster units."),
        (303, 1, "Infrastructure development grant; government-led industrial areas."),
    ],
    "P040": [], "P041": [], "P042": [], "P043": [],
    "P044": [
        (302, 3, "MSE-CDP CFC grant for artisan cluster common facility centre."),
        (303, 1, "Infrastructure development grant; government-led."),
    ],
    "P045": [  # geo null
        (328, 1, "Credit guarantee for women-owned MSEs; KA only, vague need."),
        (195, 1, "Micro capital subsidy; KA only, vague need."),
    ],
    "P046": [],
    "P047": [
        (238, 3, "IT recruitment assistance for expansion units beyond Bengaluru with 100+ hires."),
        (245, 3, "Talent relocation reimbursement for staff moved from Bengaluru."),
        (240, 2, "IT rental assistance; new units only, expansion status unclear."),
        (230, 2, "IT EPF reimbursement; new units only."),
        (242, 2, "IT skilling reimbursement; new units only."),
        (229, 1, "Electricity duty reimbursement; new units only."),
        (237, 1, "Property tax reimbursement; only if owning property."),
        (244, 1, "Internet expense reimbursement; new units only."),
        (236, 1, "Power tariff concession; minor."),
        (231, 1, "Events reimbursement; minor."),
        (233, 1, "Internship reimbursement; minor."),
        (304, 1, "Nipuna PPP training co-funding; minor."),
    ],
}

NO_RELEVANT_V2 = sorted(pid for pid, labs in L.items() if not any(g >= 2 for _, g, _ in labs))


def main():
    ids = {p["profile_id"] for p in g1}
    assert set(L) == ids, f"label/profile mismatch: {set(L) ^ ids}"
    out, seen = [], {}
    for p in g1:
        pid = p["profile_id"]
        best = {}
        for idx, grade, why in L[pid]:
            assert 0 <= idx < len(corpus), (pid, idx)
            assert grade in (1, 2, 3) and why and len(why.split()) <= 20, (pid, idx)
            r = corpus[idx]
            key = (r["parent_policy_name"], r["incentive_name"])
            if (pid, idx) in seen:
                raise AssertionError(f"duplicate row {idx} for {pid}")
            seen[(pid, idx)] = 1
            # geography rule: non-Karnataka profiles may only match National rows
            geo = p["profile"]["geography"]
            if geo and geo != "Karnataka":
                assert "National" in r["applicable_geographies"], (pid, idx, "geography violation")
            if geo is None:
                assert grade <= 2, (pid, idx, "geo_null max grade is 2")
            if key not in best or grade > best[key][0]:
                best[key] = (grade, why)
        for (parent, inc), (grade, why) in best.items():
            out.append({"profile_id": pid, "parent_policy_name": parent, "incentive_name": inc,
                        "relevance": grade, "rationale": why})
    with open(os.path.join(HERE, "g2_relevance_v2.jsonl"), "w", encoding="utf-8") as f:
        for row in out:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    c = Counter(r["relevance"] for r in out)
    per = Counter(r["profile_id"] for r in out)
    print(f"{len(out)} labels  grades={dict(sorted(c.items()))}  profiles_with_labels={len(per)}/{len(ids)}")
    print(f"parents covered={len({r['parent_policy_name'] for r in out})}/{len({r['parent_policy_name'] for r in corpus})}")
    print("profiles with no grade>=2 label:", NO_RELEVANT_V2)


if __name__ == "__main__":
    main()
