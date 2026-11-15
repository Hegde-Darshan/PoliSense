"""Deterministic, non-LLM evaluator for the DISCOVERY retrieval pipeline (EVALUATION.md section 3).

Run from the repo root:
    venv/Scripts/python.exe -m evals.retrieval_eval [--profiles P] [--labels L] [--top-k 20]
        [--rel-threshold 2] [--no-ablations] [--worst 8] [--selftest]

Only local sentence-transformers models are used (bge-small embeddings, bge-reranker-base).
The DB connection is opened read-only. Labels are matched by (parent_policy_name, incentive_name).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import time
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASETS = ROOT / "evals" / "datasets"
RESULTS = ROOT / "evals" / "results"
KS = (5, 10, 20)
RRF_K = 60
BGE_PREFIX = "Represent this sentence for searching relevant passages: "
ZOHO_SUFFIX = " government grants subsidies and incentives"
FILTER_KEYS = ("industry", "geography", "business_size")
EMBED_MODEL, RERANK_MODEL = "BAAI/bge-small-en-v1.5", "BAAI/bge-reranker-base"


# ── Metric functions (pure) ──────────────────────────────────────────────────
# `grades` is the graded relevance of each ranked item, in rank order.

def recall_at_k(grades, n_rel, k, thr):
    return None if not n_rel else sum(g >= thr for g in grades[:k]) / n_rel


def precision_at_k(grades, k, thr):
    return sum(g >= thr for g in grades[:k]) / k


def hit_rate_at_k(grades, k, thr):
    return float(any(g >= thr for g in grades[:k]))


def dcg(grades):
    return sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(grades))


def ndcg_at_k(grades, label_grades, k):
    ideal = dcg(sorted(label_grades, reverse=True)[:k])
    return None if ideal <= 0 else dcg(grades[:k]) / ideal


def ap_at_k(grades, n_rel, k, thr):
    if not n_rel:
        return None
    hits, total = 0, 0.0
    for i, g in enumerate(grades[:k], 1):
        if g >= thr:
            hits += 1
            total += hits / i
    return total / min(n_rel, k)


def reciprocal_rank(grades, n_rel, thr):
    if not n_rel:
        return None
    return next((1 / i for i, g in enumerate(grades, 1) if g >= thr), 0.0)


def percentile(values, p):
    s = sorted(values)
    if not s:
        return None
    idx = (len(s) - 1) * p / 100
    lo, hi = math.floor(idx), math.ceil(idx)
    return s[lo] + (s[hi] - s[lo]) * (idx - lo)


def mean(values):
    v = [x for x in values if x is not None]
    return sum(v) / len(v) if v else None


def _selftest():
    g, labels, thr = [3, 0, 2, 0, 1], [3, 2, 2, 1], 2
    n_rel = sum(x >= thr for x in labels)  # 3
    assert abs(recall_at_k(g, n_rel, 5, thr) - 2 / 3) < 1e-9
    assert recall_at_k(g, n_rel, 1, thr) == 1 / 3
    assert precision_at_k(g, 5, thr) == 0.4
    assert hit_rate_at_k([0, 1, 0], 3, thr) == 0.0 and hit_rate_at_k(g, 1, thr) == 1.0
    # dcg = 7 + 3/log2(4) + 1/log2(6) = 8.88685; idcg = 7 + 3/log2(3) + 3/2 + 1/log2(5) = 10.82347
    assert abs(ndcg_at_k(g, labels, 5) - 0.82107) < 1e-4
    assert ndcg_at_k([3, 2, 2, 1], labels, 4) == 1.0 and ndcg_at_k(g, [0], 5) is None
    assert reciprocal_rank(g, n_rel, thr) == 1.0
    assert abs(reciprocal_rank([0, 0, 2], 1, thr) - 1 / 3) < 1e-9
    assert reciprocal_rank([0, 0], 1, thr) == 0.0 and reciprocal_rank(g, 0, thr) is None
    # AP@5: hits at ranks 1 and 3 -> (1/1 + 2/3) / min(3, 5)
    assert abs(ap_at_k(g, n_rel, 5, thr) - (1 + 2 / 3) / 3) < 1e-9
    assert ap_at_k([0, 0], 2, 2, thr) == 0.0
    assert percentile([1, 2, 3, 4], 50) == 2.5
    print("selftest OK")


# ── Dataset loading ──────────────────────────────────────────────────────────

def load_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def inc_key(parent, incentive):
    return ((parent or "").strip(), (incentive or "").strip())


def load_labels(label_rows):
    """Returns ({pid: {(parent, inc): grade}}, {pid: {parent: max grade}}).
    Labels with incentive_name null count at policy level only."""
    inc, pol = defaultdict(dict), defaultdict(dict)
    for r in label_rows:
        pid, parent, grade = r["profile_id"], (r["parent_policy_name"] or "").strip(), int(r["relevance"])
        pol[pid][parent] = max(pol[pid].get(parent, 0), grade)
        if r.get("incentive_name"):
            key = inc_key(parent, r["incentive_name"])
            inc[pid][key] = max(inc[pid].get(key, 0), grade)
    return inc, pol


def filters_for(profile):
    return {k: profile[k] for k in FILTER_KEYS if profile.get(k)}


# ── Retrieval (replicates pg_retriever.retrieve_policies stage by stage) ─────

def _rows(cur):
    cols = [d[0] for d in cur.description]
    out = []
    for raw in cur.fetchall():
        r = dict(zip(cols, raw))
        r["policy_details"] = r["policy_details"] or {}
        r["incentive_details"] = r["incentive_details"] or {}
        out.append(r)
    return out


def fetch_candidates(conn, query, qvec, geography, fetch_n):
    where, fparams = _build_filter_clause(geography)
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {_SELECT_COLUMNS}, 1 - (embedding <=> %s::vector) AS similarity_score "
            f"FROM policies {where} ORDER BY embedding <=> %s::vector LIMIT %s",
            [qvec] + fparams + [qvec, fetch_n],
        )
        vec = _rows(cur)
    parts = ["search_vector @@ plainto_tsquery('english', %s)"] + ([where.replace("WHERE ", "", 1)] if where else [])
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {_SELECT_COLUMNS}, ts_rank_cd(search_vector, plainto_tsquery('english', %s)) AS similarity_score "
            f"FROM policies WHERE {' AND '.join(parts)} ORDER BY similarity_score DESC LIMIT %s",
            [query, query] + fparams + [fetch_n],
        )
        bm25 = _rows(cur)
    return vec, bm25


def run_stages(conn, query, qvec, filters, top_k, score_cache, fetch_mult=2, rerank_n=None):
    """All ablation stages for one query. rerank_n = how many RRF results the cross-encoder sees."""
    rerank_n = rerank_n or top_k
    vec, bm25 = fetch_candidates(conn, query, qvec, filters.get("geography"), top_k * fetch_mult)
    copy = lambda rows: [dict(r) for r in rows]  # _rrf_merge mutates BM25-only rows
    pool = {r["policy_id"]: r for r in bm25}
    pool.update({r["policy_id"]: r for r in vec})
    rrf_full = _rrf_merge(copy(bm25), copy(vec), top_k=len(pool)) if bm25 else copy(vec)
    rrf_scores = defaultdict(float)
    for lst in (bm25, vec):
        for rank, r in enumerate(lst, 1):
            rrf_scores[r["policy_id"]] += 1.0 / (RRF_K + rank)
    cands = copy(rrf_full[:rerank_n])
    # Cross-encoder is the slow part (~0.5s/pair on CPU): reuse scores keyed by policy_id
    # (seeded from the production call), only scoring rows not seen yet for this query.
    todo = [r for r in cands if r["policy_id"] not in score_cache]
    if todo:
        clean = query.replace(ZOHO_SUFFIX, "").strip()
        scores = rerank_with_cross_encoder(clean, [_build_incentive_text(r) for r in todo])
        score_cache.update({r["policy_id"]: float(s) for r, s in zip(todo, scores)})
    for r in cands:
        r["incentive_score"] = score_cache[r["policy_id"]]
    for r in cands:
        r["metadata_boost"] = _compute_metadata_boost(r, filters.get("industry"), filters.get("business_size"))
        r["rrf_score"] = rrf_scores[r["policy_id"]]
    reranked = sorted(cands, key=lambda r: r.get("incentive_score", r["similarity_score"]), reverse=True)
    final = sorted(cands, key=lambda r: r.get("incentive_score", r["similarity_score"]) + r["metadata_boost"],
                   reverse=True)
    return {
        "vector": vec[:top_k], "bm25": bm25[:top_k], "rrf": rrf_full[:top_k], "rrf_full": rrf_full,
        "rerank": reranked[:top_k], "final": final[:top_k], "pool": list(pool.values()), "n_bm25": len(bm25),
    }


# ── Per-ranking scoring ──────────────────────────────────────────────────────

def dedupe(rows, keyfn):
    seen, out = set(), []
    for r in rows:
        k = keyfn(r)
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


INC = lambda r: inc_key(r["parent_policy_name"], r["incentive_name"])
POL = lambda r: (r["parent_policy_name"] or "").strip()


def score_keys(keys, labels, thr):
    grades = [labels.get(k, 0) for k in keys]
    n_rel = sum(g >= thr for g in labels.values())
    m = {"n_rel": n_rel, "MRR": reciprocal_rank(grades, n_rel, thr)}
    for k in KS:
        m[f"R@{k}"] = recall_at_k(grades, n_rel, k, thr)
        m[f"P@{k}"] = precision_at_k(grades, k, thr) if n_rel else None
        m[f"HR@{k}"] = hit_rate_at_k(grades, k, thr) if n_rel else None
        m[f"nDCG@{k}"] = ndcg_at_k(grades, list(labels.values()), k)
        m[f"MAP@{k}"] = ap_at_k(grades, n_rel, k, thr)
    return m


def score_both(rows, inc_labels, pol_labels, thr):
    return {"inc": score_keys(dedupe(rows, INC), inc_labels, thr),
            "pol": score_keys(dedupe(rows, POL), pol_labels, thr)}


def candidate_recall(pool_rows, labels, keyfn, thr):
    rel = {k for k, g in labels.items() if g >= thr}
    return None if not rel else len(rel & {keyfn(r) for r in pool_rows}) / len(rel)


def geo_ok(geos, geography):
    geos = geos or []
    return "National" in geos or any(geography.lower() in (g or "").lower() for g in geos)


def polisense_checks(rows, filters, k, this_year):
    top = rows[:k]
    n = len(top) or 1
    geo = filters.get("geography")
    ind, size = filters.get("industry"), filters.get("business_size")
    return {
        "geo_violations": None if not geo else sum(not geo_ok(r["applicable_geographies"], geo) for r in top),
        "n_results": len(top),
        **{f"unique_parents@{kk}": len({POL(r) for r in rows[:kk]}) for kk in KS},
        **{f"dup_rate@{kk}": (1 - len({POL(r) for r in rows[:kk]}) / len(rows[:kk])) if rows[:kk] else None for kk in KS},
        "industry_match_rate": None if not ind else sum(_compute_metadata_boost(r, ind, None) > 0 for r in top) / n,
        "size_match_rate": None if not size else sum(_compute_metadata_boost(r, None, size) > 0 for r in top) / n,
        "validity_rate": sum(r["end_year"] is None or r["end_year"] >= this_year for r in top) / n,
    }


# ── Failure diagnosis ────────────────────────────────────────────────────────

def _rank(keys, key):
    return keys.index(key) + 1 if key in keys else None


def diagnose(key, keyfn, st, geography, db_rows_for_key, cutoff, top_k):
    """Why is relevant `key` not in the final top `cutoff`?"""
    if not db_rows_for_key:
        return "label_not_in_db"
    if key not in {keyfn(r) for r in st["pool"]}:
        if geography and not any(geo_ok(r["applicable_geographies"], geography) for r in db_rows_for_key):
            return "filtered_by_geography"
        return "not_in_candidates"
    rrf_rank = _rank(dedupe(st["rrf_full"], keyfn), key)
    if key not in dedupe(st["rrf"], keyfn):
        return "dropped_by_truncation"
    rr_rank = _rank(dedupe(st["rerank"], keyfn), key)
    fin_rank = _rank(dedupe(st["final"], keyfn), key)
    if rr_rank <= cutoff and fin_rank > cutoff:
        return "outranked_by_boost"
    if rr_rank - rrf_rank >= 5:
        return "reranker_demoted"
    return "ranked_low"


def row_summary(r, rank, grade):
    return {
        "rank": rank, "parent": r["parent_policy_name"], "incentive": r["incentive_name"],
        "geo": r["applicable_geographies"], "industries": r["applicable_industries"],
        "sizes": r["applicable_business_sizes"], "similarity": round(r["similarity_score"], 4),
        "rrf": round(r.get("rrf_score", 0.0), 5), "incentive_score": round(r.get("incentive_score", 0.0), 4),
        "metadata_boost": r.get("metadata_boost", 0.0), "grade": grade,
    }


# ── Main evaluation ──────────────────────────────────────────────────────────

ABLATIONS = ("vector", "bm25", "rrf", "rerank", "final")
ABL_NAMES = {"vector": "1 vector only", "bm25": "2 BM25 only", "rrf": "3 RRF", "rerank": "4 RRF + rerank",
             "final": "5 RRF + rerank + boost (prod)", "large_pool": "6 large pool (fetch x5, rerank 50)"}


def run(args):
    global get_connection, embed_documents, rerank_with_cross_encoder
    global retrieve_policies, _SELECT_COLUMNS, _build_filter_clause, _rrf_merge
    global _compute_metadata_boost, _build_incentive_text
    from polisense_core.utils.postgres_utils import get_connection, embed_documents, rerank_with_cross_encoder
    from polisense_core.RetrievalPipeline.pg_retriever import (
        retrieve_policies, _SELECT_COLUMNS, _build_filter_clause, _rrf_merge,
        _compute_metadata_boost, _build_incentive_text,
    )
    import polisense_core.RetrievalPipeline.pg_retriever as pgr

    thr, top_k, this_year = args.rel_threshold, args.top_k, date.today().year
    profiles = load_jsonl(args.profiles)
    label_rows = load_jsonl(args.labels)
    inc_labels, pol_labels = load_labels(label_rows)

    conn = get_connection()
    conn.set_session(readonly=True)
    with conn.cursor() as cur:
        cur.execute("SELECT policy_id, parent_policy_name, incentive_name, applicable_geographies, "
                    "applicable_industries, applicable_business_sizes, end_year FROM policies")
        db = _rows_plain(cur)
    by_inc, by_pol = defaultdict(list), defaultdict(list)
    for r in db:
        by_inc[INC(r)].append(r)
        by_pol[POL(r)].append(r)

    # Dataset warnings
    warnings = []
    pids = {p["profile_id"] for p in profiles}
    for r in label_rows:
        key = inc_key(r["parent_policy_name"], r.get("incentive_name"))
        if (r.get("incentive_name") and key not in by_inc) or key[0] not in by_pol:
            warnings.append(f"label key not in DB: {key[0]!r} / {r.get('incentive_name')!r} (profile {r['profile_id']})")
        if r["profile_id"] not in pids:
            warnings.append(f"label for unknown profile_id {r['profile_id']!r}")
    for p in profiles:
        if not pol_labels.get(p["profile_id"]):
            warnings.append(f"profile {p['profile_id']} has no labels")
    warnings = sorted(set(warnings))

    per_profile, latencies, cold_start, prod_mismatch = [], [], None, []
    abl_scores = defaultdict(list)  # config -> [score_both]
    cand_recall = defaultdict(list)  # config -> [(inc, pol)]
    embed_cache = {}
    for i, p in enumerate(profiles):
        pid, query, prof = p["profile_id"], p["query"], p.get("profile") or {}
        filters = filters_for(prof)
        il, pl = inc_labels.get(pid, {}), pol_labels.get(pid, {})

        t0 = time.perf_counter()
        prod = retrieve_policies(query=query, conn=conn, top_k=top_k, **filters)
        dt = time.perf_counter() - t0
        if i == 0:
            cold_start = dt
        else:
            latencies.append(dt)

        if query not in embed_cache:
            embed_cache[query] = embed_documents(BGE_PREFIX + query)
        qvec = embed_cache[query]
        # First profile: score independently so the replication assert is a real check of the
        # rerank step too; afterwards seed from production's scores to save CPU time.
        cache = {} if i == 0 else {r["policy_id"]: r["incentive_score"] for r in prod if "incentive_score" in r}
        st = run_stages(conn, query, qvec, filters, top_k, cache)
        rep_ids, prod_ids = [r["policy_id"] for r in st["final"]], [r["policy_id"] for r in prod]
        if rep_ids != prod_ids:
            prod_mismatch.append(pid)
            if i == 0:
                raise AssertionError(f"replicated production order != retrieve_policies for {pid}")

        if not args.no_ablations:
            for cfg in ABLATIONS:
                abl_scores[cfg].append(score_both(st[cfg], il, pl, thr))
            cand_recall["default"].append((candidate_recall(st["pool"], il, INC, thr),
                                           candidate_recall(st["pool"], pl, POL, thr)))
            big = run_stages(conn, query, qvec, filters, top_k, cache, fetch_mult=5, rerank_n=50)
            abl_scores["large_pool"].append(score_both(big["final"], il, pl, thr))
            cand_recall["large_pool"].append((candidate_recall(big["pool"], il, INC, thr),
                                              candidate_recall(big["pool"], pl, POL, thr)))

        # Annotate prod rows with rrf score for display (from replicated stage, same ids)
        rrf_by_id = {r["policy_id"]: r.get("rrf_score", 0.0) for r in st["final"]}
        for r in prod:
            r["rrf_score"] = rrf_by_id.get(r["policy_id"], 0.0)

        scores = score_both(prod, il, pl, thr)
        checks = polisense_checks(prod, filters, top_k, this_year)
        inc_keys10 = dedupe(prod, INC)[:10]
        pol_keys10 = dedupe(prod, POL)[:10]
        misses = []
        for key, g in sorted(il.items(), key=lambda kv: -kv[1]):
            if g >= thr and key not in inc_keys10:
                misses.append({"level": "incentive", "key": list(key), "grade": g,
                               "final_rank": _rank(dedupe(prod, INC), key),
                               "diagnosis": diagnose(key, INC, st, filters.get("geography"), by_inc.get(key), 10, top_k)})
        for key, g in sorted(pl.items(), key=lambda kv: -kv[1]):
            if g >= thr and key not in pol_keys10:
                misses.append({"level": "policy", "key": [key], "grade": g,
                               "final_rank": _rank(dedupe(prod, POL), key),
                               "diagnosis": diagnose(key, POL, st, filters.get("geography"), by_pol.get(key), 10, top_k)})
        flags = []
        if len({POL(r) for r in prod[:10]}) <= 2:
            flags.append("duplicate_crowding")
        if checks["geo_violations"]:
            flags.append("geo_violation")
        per_profile.append({
            "profile_id": pid, "business_name": p.get("business_name"), "query": query, "filters": filters,
            "difficulty": p.get("difficulty"), "tags": p.get("tags") or [], "latency_s": round(dt, 3),
            "n_bm25_hits": st["n_bm25"],
            "metrics": scores, "checks": checks, "misses": misses, "flags": flags,
            "returned_ids": [str(x) for x in prod_ids],
            "returned_keys": [list(INC(r)) for r in prod],
            "top10": [row_summary(r, j, il.get(INC(r), 0)) for j, r in enumerate(prod[:10], 1)],
            "expected": [{"key": list(k), "grade": g} for k, g in sorted(il.items(), key=lambda kv: -kv[1])]
                        + [{"key": [k, None], "grade": g} for k, g in sorted(pl.items(), key=lambda kv: -kv[1])
                           if not any(kk[0] == k for kk in il)],
        })
        print(f"  [{i + 1}/{len(profiles)}] {pid}: inc nDCG@10={_f(scores['inc']['nDCG@10'])} "
              f"pol R@20={_f(scores['pol']['R@20'])} ({dt:.2f}s)")
    conn.close()

    # ── Aggregates ──
    metric_names = list(per_profile[0]["metrics"]["inc"].keys()) if per_profile else []
    agg = lambda rows, lvl: {m: mean([r[lvl][m] for r in rows]) for m in metric_names if m != "n_rel"}
    headline = {lvl: agg([pp["metrics"] for pp in per_profile], lvl) for lvl in ("inc", "pol")}

    check_names = [c for c in (per_profile[0]["checks"] if per_profile else {}) if c not in ("geo_violations", "n_results")]
    geo_rows = [pp["checks"] for pp in per_profile if pp["checks"]["geo_violations"] is not None]
    retrieved_ids = {x for pp in per_profile for x in pp["returned_ids"]}
    retrieved_parents = {k[0] for pp in per_profile for k in pp["returned_keys"]}
    all_parents = set(by_pol)
    checks_agg = {
        "geo_violation_rate": (sum(c["geo_violations"] for c in geo_rows) / max(1, sum(c["n_results"] for c in geo_rows)))
        if geo_rows else None,
        "profiles_with_geo_violation": sum(1 for c in geo_rows if c["geo_violations"]),
        **{c: mean([pp["checks"][c] for pp in per_profile]) for c in check_names},
        "corpus_coverage_rows": len(retrieved_ids) / max(1, len(db)),
        "corpus_coverage_parents": len(retrieved_parents & all_parents) / max(1, len(all_parents)),
        "n_rows": len(db), "n_parents": len(all_parents),
        "profiles_with_zero_bm25_hits": sum(1 for pp in per_profile if pp["n_bm25_hits"] == 0),
        "mean_bm25_hits": mean([pp["n_bm25_hits"] for pp in per_profile]),
        "cold_start_s": cold_start,
        "latency_p50_s": percentile(latencies, 50), "latency_p95_s": percentile(latencies, 95),
        "replication_mismatches": prod_mismatch,
    }

    ablations = {}
    for cfg, rows in abl_scores.items():
        ablations[cfg] = {lvl: agg(rows, lvl) for lvl in ("inc", "pol")}
    cand = {cfg: {"inc": mean([a for a, _ in v]), "pol": mean([b for _, b in v])} for cfg, v in cand_recall.items()}

    slices = defaultdict(list)
    for pp in per_profile:
        slices["all"].append(pp)
        slices[f"difficulty={pp['difficulty']}"].append(pp)
        for t in pp["tags"]:
            slices[f"tag={t}"].append(pp)
        slices[f"geo={pp['filters'].get('geography') or 'null'}"].append(pp)
    slice_tab = {name: {"n": len(rows), **{f"{lvl}_{m}": mean([r["metrics"][lvl][m] for r in rows])
                                          for lvl in ("inc", "pol") for m in ("nDCG@10", "R@20", "MRR", "HR@5")}}
                 for name, rows in slices.items()}

    diag_counts = {lvl: Counter(m["diagnosis"] for pp in per_profile for m in pp["misses"] if m["level"] == lvl)
                   for lvl in ("incentive", "policy")}
    flag_counts = Counter(f for pp in per_profile for f in pp["flags"])

    returned_by_profile = {pp["profile_id"]: {tuple(k) for k in pp["returned_keys"]} for pp in per_profile}
    all_returned = set().union(*returned_by_profile.values()) if returned_by_profile else set()
    never = defaultdict(list)
    for pid, labels in inc_labels.items():
        for k, g in labels.items():
            if g >= thr and k not in all_returned:
                never[k].append(pid)
    never_retrieved = [{"key": list(k), "profiles": v, "in_db": k in by_inc} for k, v in sorted(never.items())]
    never_parents = sorted(all_parents - retrieved_parents)

    def sort_key(m):
        return lambda pp: (pp["metrics"]["inc"][m] if pp["metrics"]["inc"][m] is not None else 9)
    worst_ndcg = [pp["profile_id"] for pp in sorted(per_profile, key=sort_key("nDCG@10"))[:args.worst]]
    worst_recall = [pp["profile_id"] for pp in sorted(per_profile, key=sort_key("R@20"))[:args.worst]]

    report = {
        "meta": {
            "timestamp": datetime.now().isoformat(timespec="seconds"), "git_sha": _git_sha(),
            "profiles_file": str(args.profiles), "profiles_sha256": sha256(args.profiles),
            "labels_file": str(args.labels), "labels_sha256": sha256(args.labels),
            "n_profiles": len(profiles), "n_labels": len(label_rows), "top_k": top_k, "fetch_n": top_k * 2,
            "rrf_k": RRF_K, "industry_boost": pgr._INDUSTRY_BOOST, "size_boost": pgr._SIZE_BOOST,
            "rel_threshold": thr, "embed_model": EMBED_MODEL, "rerank_model": RERANK_MODEL,
            "query_prefix": BGE_PREFIX, "validity_year": this_year,
        },
        "dataset_warnings": warnings, "headline": headline, "checks": checks_agg,
        "ablations": ablations, "candidate_recall": cand, "slices": slice_tab,
        "diagnosis_counts": {k: dict(v) for k, v in diag_counts.items()}, "flag_counts": dict(flag_counts),
        "worst_by_ndcg10": worst_ndcg, "worst_by_recall20": worst_recall,
        "never_retrieved_relevant": never_retrieved, "never_retrieved_parents": never_parents,
        "per_profile": per_profile,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = RESULTS / f"retrieval_eval_{stamp}.json"
    json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    md_path = RESULTS / "retrieval_report.md"
    md_path.write_text(render_md(report), encoding="utf-8")
    print(f"\nWrote {json_path}\nWrote {md_path}")
    h = headline
    print(f"Production  inc: nDCG@10={_f(h['inc'].get('nDCG@10'))} R@20={_f(h['inc'].get('R@20'))} "
          f"MRR={_f(h['inc'].get('MRR'))} | pol: nDCG@10={_f(h['pol'].get('nDCG@10'))} R@20={_f(h['pol'].get('R@20'))}")
    return report


def _rows_plain(cur):
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, raw)) for raw in cur.fetchall()]


def _git_sha():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return None


# ── Markdown report ──────────────────────────────────────────────────────────

def _f(x, nd=3):
    return "-" if x is None else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))


def _table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(_f(c) if not isinstance(c, str) else c.replace("|", "/") for c in row) + " |" for row in rows]
    return "\n".join(out)


def _observations(rep):
    obs, h, c, a, cr = [], rep["headline"], rep["checks"], rep["ablations"], rep["candidate_recall"]
    get = lambda cfg, lvl, m: (a.get(cfg) or {}).get(lvl, {}).get(m)
    if cr.get("default") and h["inc"].get("R@20") is not None and cr["default"]["inc"] is not None:
        gap = cr["default"]["inc"] - h["inc"]["R@20"]
        obs.append(f"Candidate recall (incentive) is {_f(cr['default']['inc'])} vs final R@20 {_f(h['inc']['R@20'])} "
                   f"(gap {_f(gap)}). " + ("Truncating RRF to top_k before rerank loses relevant items: rerank a larger pool."
                                            if gap > 0.1 else "Truncation before rerank costs little."))
    for (x, y, label) in (("rerank", "rrf", "Cross-encoder rerank"), ("final", "rerank", "Metadata boost"),
                          ("large_pool", "final", "Larger rerank pool (fetch x5, rerank 50)"),
                          ("rrf", "vector", "Adding BM25 via RRF")):
        for m in ("nDCG@10", "R@20"):
            vx, vy = get(x, "inc", m), get(y, "inc", m)
            if vx is not None and vy is not None:
                d = vx - vy
                verdict = "helps" if d > 0.02 else "hurts" if d < -0.02 else "is neutral"
                obs.append(f"{label} {verdict} on incentive {m}: {_f(vy)} -> {_f(vx)} ({d:+.3f}).")
    dc = rep["diagnosis_counts"].get("incentive") or {}
    if dc:
        top = max(dc, key=dc.get)
        obs.append(f"Most common reason a relevant incentive misses the top 10: `{top}` ({dc[top]} of {sum(dc.values())}).")
    if c.get("geo_violation_rate"):
        obs.append(f"Geography violation rate is {_f(c['geo_violation_rate'])} (should be 0): check geography tags.")
    if (c.get("dup_rate@10") or 0) > 0.4:
        obs.append(f"Duplicate rate@10 is {_f(c['dup_rate@10'])}: top results are crowded by a few parents. "
                   "Consider parent-level dedupe/diversification before the report.")
    if c.get("corpus_coverage_parents") is not None and c["corpus_coverage_parents"] < 0.6:
        obs.append(f"Only {_f(c['corpus_coverage_parents'])} of parents appear in any top-{rep['meta']['top_k']}: "
                   f"{len(rep['never_retrieved_parents'])} parents are never surfaced (see Never-retrieved).")
    if c.get("profiles_with_zero_bm25_hits"):
        obs.append(f"{c['profiles_with_zero_bm25_hits']} profiles get zero BM25 hits (plainto_tsquery ANDs every term, "
                   "so long queries rarely match); BM25 then contributes nothing. Consider OR-ed terms (websearch/to_tsquery).")
    if c.get("validity_rate") is not None and c["validity_rate"] < 1:
        obs.append(f"Validity rate {_f(c['validity_rate'])}: some results have end_year in the past.")
    if (c.get("industry_match_rate") or 1) > 0.95:
        obs.append(f"Industry match rate {_f(c['industry_match_rate'])}: the +1.0 boost may be swamping relevance.")
    return obs


def render_md(rep):
    m, h, c = rep["meta"], rep["headline"], rep["checks"]
    L = [f"# Retrieval evaluation report", "",
         f"Generated {m['timestamp']} · git `{(m['git_sha'] or '')[:10]}` · {m['n_profiles']} profiles, "
         f"{m['n_labels']} labels · top_k={m['top_k']} · fetch_n={m['fetch_n']} · RRF k={m['rrf_k']} · "
         f"boosts industry={m['industry_boost']} size={m['size_boost']} · relevant = grade ≥ {m['rel_threshold']}", "",
         f"Profiles `{m['profiles_file']}` ({m['profiles_sha256']}), labels `{m['labels_file']}` ({m['labels_sha256']})", ""]
    if rep["dataset_warnings"]:
        L += ["## Dataset warnings", ""] + [f"- {w}" for w in rep["dataset_warnings"][:50]] + [""]

    cols = [f"{x}@{k}" for x in ("R", "P", "HR", "nDCG", "MAP") for k in (5, 10, 20)] + ["MRR"]
    L += ["## Headline metrics (production config)", "",
          _table(["level"] + cols, [[lvl] + [h[key].get(cc) for cc in cols] for lvl, key in
                                    (("incentive", "inc"), ("policy", "pol"))]), "",
          "Policy level: results deduped by parent (first occurrence), grade = max grade of its incentives.", ""]

    if rep["ablations"]:
        acols = ["R@5", "R@10", "R@20", "nDCG@10", "MRR", "MAP@10"]
        rows = []
        for cfg in (*ABLATIONS, "large_pool"):
            if cfg in rep["ablations"]:
                a = rep["ablations"][cfg]
                rows.append([ABL_NAMES[cfg]] + [a["inc"].get(x) for x in acols] + [a["pol"].get(x) for x in acols])
        L += ["## Ablations", "", _table(["config"] + [f"inc {x}" for x in acols] + [f"pol {x}" for x in acols], rows), ""]
        cr = rep["candidate_recall"]
        L += [_table(["candidate pool", "inc recall", "pol recall"],
                     [[k, v["inc"], v["pol"]] for k, v in cr.items()]), "",
              "Candidate recall = recall of the union of vector + BM25 fetch_n lists before truncation to top_k.", ""]

    sc = ["n", "inc_nDCG@10", "inc_R@20", "inc_MRR", "pol_nDCG@10", "pol_R@20", "pol_MRR", "pol_HR@5"]
    L += ["## Slices", "", _table(["slice"] + sc, [[k] + [v.get(x) for x in sc] for k, v in sorted(rep["slices"].items())]), ""]

    ck = [("Geography violation rate", c["geo_violation_rate"]), ("Profiles with a geo violation", c["profiles_with_geo_violation"]),
          *[(f"Unique parents@{k}", c.get(f"unique_parents@{k}")) for k in KS],
          *[(f"Duplicate rate@{k}", c.get(f"dup_rate@{k}")) for k in KS],
          ("Industry match rate (top k)", c.get("industry_match_rate")), ("Size match rate (top k)", c.get("size_match_rate")),
          ("Validity rate", c.get("validity_rate")),
          (f"Mean BM25 hits (of fetch_n={m['fetch_n']})", c.get("mean_bm25_hits")),
          ("Profiles with zero BM25 hits (falls back to vector only)", c.get("profiles_with_zero_bm25_hits")),
          (f"Corpus coverage, rows (of {c['n_rows']})", c["corpus_coverage_rows"]),
          (f"Corpus coverage, parents (of {c['n_parents']})", c["corpus_coverage_parents"]),
          ("Cold start (s, first call incl. model load)", c["cold_start_s"]),
          ("Latency p50 (s)", c["latency_p50_s"]), ("Latency p95 (s)", c["latency_p95_s"]),
          ("Replication mismatches vs retrieve_policies", ", ".join(c["replication_mismatches"]) or "none")]
    L += ["## PoliSense checks", "", _table(["check", "value"], [[a, b] for a, b in ck]), ""]

    L += ["## Worst cases", "",
          f"Miss diagnoses (relevant items outside the top 10): incentive {rep['diagnosis_counts'].get('incentive')}, "
          f"policy {rep['diagnosis_counts'].get('policy')}. Flags: {rep['flag_counts']}", ""]
    pp_by = {pp["profile_id"]: pp for pp in rep["per_profile"]}
    shown = []
    for pid in rep["worst_by_ndcg10"] + rep["worst_by_recall20"]:
        if pid in shown:
            continue
        shown.append(pid)
        pp = pp_by[pid]
        mi, mp = pp["metrics"]["inc"], pp["metrics"]["pol"]
        L += [f"### {pid}: {pp['business_name']} ({pp['difficulty']}; {', '.join(pp['tags'])})", "",
              f"- Query: {pp['query']}", f"- Filters: `{json.dumps(pp['filters'])}`",
              f"- incentive nDCG@10 {_f(mi['nDCG@10'])}, R@20 {_f(mi['R@20'])}, MRR {_f(mi['MRR'])} · "
              f"policy nDCG@10 {_f(mp['nDCG@10'])}, R@20 {_f(mp['R@20'])}" +
              (f" · flags: {', '.join(pp['flags'])}" if pp["flags"] else ""), "", "Expected (top labels):", ""]
        miss_by = {(mm["level"], tuple(mm["key"])): mm for mm in pp["misses"]}
        inc_keys = dedupe([{"parent_policy_name": a, "incentive_name": b} for a, b in pp["returned_keys"]], INC)
        pol_keys = dedupe([{"parent_policy_name": a} for a, _ in pp["returned_keys"]], POL)
        for e in pp["expected"][:10]:
            k = tuple(e["key"])
            mm = miss_by.get(("policy", (k[0],))) if k[1] is None else miss_by.get(("incentive", k))
            rank = _rank(pol_keys, k[0]) if k[1] is None else _rank(inc_keys, k)
            status = f"rank {rank}" if rank else f"not in top {m['top_k']}"
            if mm:
                status = f"MISSING from top 10 ({status}): **{mm['diagnosis']}**"
            L.append(f"- [{e['grade']}] {k[0]} / {k[1] or '(policy)'}: {status}")
        L += ["", "Returned (top 10):", "",
              _table(["#", "grade", "parent", "incentive", "geo", "industries", "sim", "rrf", "ce score", "boost"],
                     [[r["rank"], r["grade"], r["parent"][:60], (r["incentive"] or "")[:60],
                       ", ".join(r["geo"] or [])[:30], ", ".join(r["industries"] or [])[:40],
                       r["similarity"], r["rrf"], r["incentive_score"], r["metadata_boost"]] for r in pp["top10"]]), ""]

    L += ["## Never-retrieved", "", "Relevant labelled incentives that never appear in any profile's top-k:", ""]
    L += [f"- {n['key'][0]} / {n['key'][1]} (profiles: {', '.join(n['profiles'])}{'' if n['in_db'] else '; NOT IN DB'})"
          for n in rep["never_retrieved_relevant"]] or ["- none"]
    L += ["", f"Parents never retrieved for any profile ({len(rep['never_retrieved_parents'])}):", ""]
    L += [f"- {p}" for p in rep["never_retrieved_parents"]] or ["- none"]
    L += ["", "## Observations / what to tune", ""] + [f"- {o}" for o in _observations(rep)] + [""]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profiles", type=Path, default=DATASETS / "g1_profiles.jsonl")
    ap.add_argument("--labels", type=Path, default=DATASETS / "g2_relevance.jsonl")
    ap.add_argument("--top-k", type=int, default=20)
    ap.add_argument("--rel-threshold", type=int, default=2)
    ap.add_argument("--no-ablations", action="store_true")
    ap.add_argument("--worst", type=int, default=8, help="number of worst profiles to list per metric")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        _selftest()
        return
    run(args)


if __name__ == "__main__":
    main()
