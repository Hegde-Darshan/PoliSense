"""Deterministic, non-LLM evaluator for the DISCOVERY retrieval pipeline (EVALUATION.md section 3).

Run from the repo root:
    venv/Scripts/python.exe -m evals.retrieval_eval [--profiles P] [--labels L] [--top-k 20]
        [--rel-threshold 2] [--no-ablations] [--worst 8] [--selftest]

Design: retrieve_policies is treated as a black box, so this file does not need to change
when the retrieval steps change.
- Headline metrics come from calling retrieve_policies exactly like production does. Filter
  keys are taken from the production caller (polisense_core.retrieval_pipeline._FILTER_KEYS),
  limited to parameters retrieve_policies accepts.
- Stage diagnostics (stage ablations, stage reach, why a relevant item was missed) come from
  the optional `trace` dict that retrieve_policies fills in. Whatever stages it reports are
  scored; if the hook is missing, those sections are skipped.
- Knob ablations use public parameters or patch module attributes, and are skipped with a
  reason when the parameter/attribute no longer exists.

Only local sentence-transformers models run (via retrieve_policies). The DB session is read-only.
Labels are matched by (parent_policy_name, incentive_name).
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import inspect
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
DEFAULT_FILTER_KEYS = ("industry", "geography", "business_size")  # used only if the production constant is gone


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


INC = lambda r: inc_key(r.get("parent_policy_name"), r.get("incentive_name"))
POL = lambda r: (r.get("parent_policy_name") or "").strip()


# ── Retrieval adapter (black box + optional trace) ───────────────────────────

class Retriever:
    """Calls retrieve_policies the way production does; knows nothing about its internals."""

    def __init__(self):
        import polisense_core.RetrievalPipeline.pg_retriever as pgr
        self.module = pgr
        self.fn = pgr.retrieve_policies
        self.params = set(inspect.signature(self.fn).parameters)
        try:
            from polisense_core.retrieval_pipeline import _FILTER_KEYS as prod_keys
            self.filter_source = "polisense_core.retrieval_pipeline._FILTER_KEYS"
        except ImportError:
            prod_keys, self.filter_source = DEFAULT_FILTER_KEYS, "evaluator default"
        self.filter_keys = tuple(k for k in prod_keys if k in self.params)
        self.dropped_filter_keys = tuple(k for k in prod_keys if k not in self.params)
        self.supports_trace = "trace" in self.params

    def filters_for(self, profile):
        return {k: profile[k] for k in self.filter_keys if profile.get(k)}

    def __call__(self, query, conn, top_k, filters, trace=None, **extra):
        kw = {"query": query, "conn": conn, "top_k": top_k, **filters, **extra}
        if trace is not None and self.supports_trace:
            kw["trace"] = trace
        return self.fn(**kw)

    def knobs(self):
        """Numeric module-level constants (boost weights etc.), recorded for reproducibility."""
        return {k: v for k, v in vars(self.module).items()
                if k.lstrip("_")[:1].isupper() and k.lstrip("_").isupper()
                and isinstance(v, (int, float)) and not isinstance(v, bool)}


@contextlib.contextmanager
def patched(module, attrs):
    """Temporarily replace module attributes. Yields the list of names that do not exist."""
    missing = [a for a in attrs if not hasattr(module, a)]
    saved = {a: getattr(module, a) for a in attrs if a not in missing}
    try:
        for a in saved:
            setattr(module, a, attrs[a])
        yield missing
    finally:
        for a, v in saved.items():
            setattr(module, a, v)


def memoize_models(module):
    """Memoised replacements for the model calls retrieve_policies makes, so ablations reuse
    the scores computed by the production call instead of re-running the cross-encoder.
    Returns {attr: wrapper} for whichever of these functions the module still imports."""
    out = {}
    if hasattr(module, "rerank_with_cross_encoder"):
        orig, cache = module.rerank_with_cross_encoder, {}

        def rerank(query, texts, *a, **k):
            extra = repr((a, sorted(k.items())))
            todo = [t for t in dict.fromkeys(texts) if (query, t, extra) not in cache]
            if todo:
                cache.update({(query, t, extra): s for t, s in zip(todo, orig(query, todo, *a, **k))})
            return [cache[(query, t, extra)] for t in texts]
        out["rerank_with_cross_encoder"] = rerank
    if hasattr(module, "embed_documents"):
        orig_e, cache_e = module.embed_documents, {}

        def embed(text, *a, **k):
            key = (text, repr((a, sorted(k.items()))))
            if key not in cache_e:
                cache_e[key] = orig_e(text, *a, **k)
            return cache_e[key]
        out["embed_documents"] = embed
    return out


# Knob ablations. Each is skipped (with the reason reported) if its parameter or attribute is gone.
KNOB_ABLATIONS = [
    {"name": "no_rerank", "label": "without cross-encoder rerank", "kwargs": {"rerank": False}},
    {"name": "no_boost", "label": "without metadata boost",
     "patch": {"_compute_metadata_boost": lambda *a, **k: 0.0}},
    {"name": "large_pool", "label": "2.5x larger pool (top_k x2.5, truncated)", "top_k_mult": 2.5},
]


# ── Per-ranking scoring ──────────────────────────────────────────────────────

def dedupe(rows, keyfn):
    seen, out = set(), []
    for r in rows:
        k = keyfn(r)
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


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


def reach(rows, labels, keyfn, thr):
    """Share of relevant keys present anywhere in `rows` (no cutoff)."""
    rel = {k for k, g in labels.items() if g >= thr}
    return None if not rel else len(rel & {keyfn(r) for r in rows}) / len(rel)


def geo_ok(geos, geography):
    geos = geos or []
    return "National" in geos or any(geography.lower() in (g or "").lower() for g in geos)


def industry_match(r, industry):
    targets = industry if isinstance(industry, list) else [industry]
    inds = r.get("applicable_industries") or []
    return any(t in inds for t in targets) or "All Sectors" in inds


def size_match(r, size):
    sizes = r.get("applicable_business_sizes") or []
    return size in sizes or "All" in sizes


def polisense_checks(rows, filters, k, this_year):
    top = rows[:k]
    n = len(top) or 1
    geo, ind, size = filters.get("geography"), filters.get("industry"), filters.get("business_size")
    return {
        "geo_violations": None if not geo else sum(not geo_ok(r.get("applicable_geographies"), geo) for r in top),
        "n_results": len(top),
        **{f"unique_parents@{kk}": len({POL(r) for r in rows[:kk]}) for kk in KS},
        **{f"dup_rate@{kk}": (1 - len({POL(r) for r in rows[:kk]}) / len(rows[:kk])) if rows[:kk] else None for kk in KS},
        "industry_match_rate": None if not ind else sum(industry_match(r, ind) for r in top) / n,
        "size_match_rate": None if not size else sum(size_match(r, size) for r in top) / n,
        "validity_rate": sum(r.get("end_year") is None or r["end_year"] >= this_year for r in top) / n,
    }


# ── Failure diagnosis (generic over trace stages) ────────────────────────────

def _rank(keys, key):
    return keys.index(key) + 1 if key in keys else None


def diagnose(key, keyfn, trace, geography, db_rows_for_key, final_keys, cutoff):
    """Why is relevant `key` not in the final top `cutoff`?"""
    if not db_rows_for_key:
        return "label_not_in_db"
    if geography and not any(geo_ok(r["applicable_geographies"], geography) for r in db_rows_for_key):
        return "filtered_by_geography"
    rank = _rank(final_keys, key)
    if rank:
        return f"ranked_low (rank {rank})"
    stages = [s for s in (trace or {}).get("stages", []) if s != "final"]
    if not stages:
        return "not_returned (no trace)"
    present = [s for s in stages if key in {keyfn(r) for r in trace.get(s, [])}]
    if not present:
        return "never_retrieved"
    return f"dropped_after_{present[-1]}"


def row_summary(r, rank, grade):
    rnd = lambda x, n=4: round(x, n) if isinstance(x, (int, float)) else x
    return {
        "rank": rank, "parent": r.get("parent_policy_name"), "incentive": r.get("incentive_name"),
        "geo": r.get("applicable_geographies"), "industries": r.get("applicable_industries"),
        "sizes": r.get("applicable_business_sizes"), "similarity": rnd(r.get("similarity_score")),
        "incentive_score": rnd(r.get("incentive_score")), "metadata_boost": rnd(r.get("metadata_boost")),
        "grade": grade,
    }


# ── Main evaluation ──────────────────────────────────────────────────────────

def run(args):
    from polisense_core.utils.postgres_utils import get_connection

    R = Retriever()
    memo = memoize_models(R.module)
    thr, top_k, this_year = args.rel_threshold, args.top_k, date.today().year
    profiles = load_jsonl(args.profiles)
    label_rows = load_jsonl(args.labels)
    inc_labels, pol_labels = load_labels(label_rows)

    conn = get_connection()
    conn.set_session(readonly=True)
    with conn.cursor() as cur:
        cur.execute("SELECT policy_id, parent_policy_name, incentive_name, applicable_geographies, "
                    "applicable_industries, applicable_business_sizes, end_year FROM policies")
        cols = [d[0] for d in cur.description]
        db = [dict(zip(cols, raw)) for raw in cur.fetchall()]
    by_inc, by_pol = defaultdict(list), defaultdict(list)
    for r in db:
        by_inc[INC(r)].append(r)
        by_pol[POL(r)].append(r)

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
    if R.dropped_filter_keys:
        warnings.append(f"production filter keys not accepted by retrieve_policies: {R.dropped_filter_keys}")
    if not R.supports_trace:
        warnings.append("retrieve_policies has no `trace` parameter: stage ablations, stage reach and miss "
                        "diagnosis are skipped")
    warnings = sorted(set(warnings))

    # Decide which knob ablations can run with the current code.
    knob_plan, skipped = [], {}
    if not args.no_ablations:
        for spec in KNOB_ABLATIONS:
            bad_kw = [k for k in spec.get("kwargs", {}) if k not in R.params]
            bad_attr = [a for a in spec.get("patch", {}) if not hasattr(R.module, a)]
            if bad_kw or bad_attr:
                skipped[spec["name"]] = f"missing parameter {bad_kw}" if bad_kw else f"missing attribute {bad_attr}"
            else:
                knob_plan.append(spec)

    per_profile, latencies, cold_start, trace_mismatch = [], [], None, []
    abl_scores = defaultdict(list)   # ablation/stage name -> [score_both]
    stage_reach = defaultdict(list)  # stage name -> [(inc, pol)]
    stage_len = defaultdict(list)
    stage_order, trace_config = [], None
    for i, p in enumerate(profiles):
        pid, query, prof = p["profile_id"], p["query"], p.get("profile") or {}
        filters = R.filters_for(prof)
        il, pl = inc_labels.get(pid, {}), pol_labels.get(pid, {})

        trace = {} if R.supports_trace else None
        with patched(R.module, memo):  # memo only stores; each new query is a cache miss, so latency is honest
            t0 = time.perf_counter()
            prod = R(query, conn, top_k, filters, trace=trace)
            dt = time.perf_counter() - t0
        if i == 0:
            cold_start = dt
        else:
            latencies.append(dt)
        prod_ids = [r.get("policy_id") for r in prod]

        if trace:
            trace_config = trace_config or trace.get("config")
            for s in trace.get("stages", []):
                if s not in stage_order:
                    stage_order.append(s)
            if "final" in trace and [r.get("policy_id") for r in trace["final"]] != prod_ids:
                trace_mismatch.append(pid)
            if not args.no_ablations:
                for s in trace.get("stages", []):
                    rows = trace.get(s, [])
                    abl_scores[f"stage:{s}"].append(score_both(rows, il, pl, thr))
                    stage_reach[s].append((reach(rows, il, INC, thr), reach(rows, pl, POL, thr)))
                    stage_len[s].append(len(rows))

        for spec in knob_plan:
            k2 = math.ceil(top_k * spec.get("top_k_mult", 1))
            with patched(R.module, {**memo, **spec.get("patch", {})}):
                rows = R(query, conn, k2, filters, **spec.get("kwargs", {}))
            abl_scores[spec["name"]].append(score_both(rows[:top_k], il, pl, thr))

        scores = score_both(prod, il, pl, thr)
        checks = polisense_checks(prod, filters, top_k, this_year)
        inc_final, pol_final = dedupe(prod, INC), dedupe(prod, POL)
        misses = []
        for key, g in sorted(il.items(), key=lambda kv: -kv[1]):
            if g >= thr and key not in inc_final[:10]:
                misses.append({"level": "incentive", "key": list(key), "grade": g, "final_rank": _rank(inc_final, key),
                               "diagnosis": diagnose(key, INC, trace, filters.get("geography"), by_inc.get(key), inc_final, 10)})
        for key, g in sorted(pl.items(), key=lambda kv: -kv[1]):
            if g >= thr and key not in pol_final[:10]:
                misses.append({"level": "policy", "key": [key], "grade": g, "final_rank": _rank(pol_final, key),
                               "diagnosis": diagnose(key, POL, trace, filters.get("geography"), by_pol.get(key), pol_final, 10)})
        flags = []
        if prod and len({POL(r) for r in prod[:10]}) <= 2:
            flags.append("duplicate_crowding")
        if checks["geo_violations"]:
            flags.append("geo_violation")
        if not prod:
            flags.append("no_results")
        per_profile.append({
            "profile_id": pid, "business_name": p.get("business_name"), "query": query, "filters": filters,
            "difficulty": p.get("difficulty"), "tags": p.get("tags") or [], "latency_s": round(dt, 3),
            "n_bm25_hits": len(trace["bm25"]) if trace and "bm25" in trace else None,
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
    bm25_hits = [pp["n_bm25_hits"] for pp in per_profile if pp["n_bm25_hits"] is not None]
    checks_agg = {
        "geo_violation_rate": (sum(c["geo_violations"] for c in geo_rows) / max(1, sum(c["n_results"] for c in geo_rows)))
        if geo_rows else None,
        "profiles_with_geo_violation": sum(1 for c in geo_rows if c["geo_violations"]),
        "profiles_with_no_results": sum(1 for pp in per_profile if "no_results" in pp["flags"]),
        **{c: mean([pp["checks"][c] for pp in per_profile]) for c in check_names},
        "corpus_coverage_rows": len(retrieved_ids) / max(1, len(db)),
        "corpus_coverage_parents": len(retrieved_parents & all_parents) / max(1, len(all_parents)),
        "n_rows": len(db), "n_parents": len(all_parents),
        "profiles_with_zero_bm25_hits": sum(1 for h in bm25_hits if h == 0) if bm25_hits else None,
        "mean_bm25_hits": mean(bm25_hits) if bm25_hits else None,
        "cold_start_s": cold_start,
        "latency_p50_s": percentile(latencies, 50), "latency_p95_s": percentile(latencies, 95),
        "trace_mismatches": trace_mismatch,
    }

    ablations = {cfg: {lvl: agg(rows, lvl) for lvl in ("inc", "pol")} for cfg, rows in abl_scores.items()}
    reach_tab = {s: {"inc": mean([a for a, _ in stage_reach[s]]), "pol": mean([b for _, b in stage_reach[s]]),
                     "avg_len": mean(stage_len[s])} for s in stage_order if s in stage_reach}

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

    diag_counts = {lvl: Counter(m["diagnosis"].split(" (")[0] for pp in per_profile for m in pp["misses"]
                                if m["level"] == lvl) for lvl in ("incentive", "policy")}
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
            "n_profiles": len(profiles), "n_labels": len(label_rows), "top_k": top_k, "rel_threshold": thr,
            "validity_year": this_year, "filter_keys": list(R.filter_keys), "filter_source": R.filter_source,
            "retriever_params": sorted(R.params), "trace_supported": R.supports_trace,
            "trace_config": trace_config, "stages": stage_order, "knobs": R.knobs(),
        },
        "dataset_warnings": warnings, "headline": headline, "checks": checks_agg,
        "ablations": ablations, "ablation_labels": {s["name"]: s["label"] for s in KNOB_ABLATIONS},
        "skipped_ablations": skipped, "stage_reach": reach_tab, "slices": slice_tab,
        "diagnosis_counts": {k: dict(v) for k, v in diag_counts.items()}, "flag_counts": dict(flag_counts),
        "worst_by_ndcg10": worst_ndcg, "worst_by_recall20": worst_recall,
        "never_retrieved_relevant": never_retrieved, "never_retrieved_parents": never_parents,
        "per_profile": per_profile,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = RESULTS / f"retrieval_eval_{stamp}.json"
    json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    md_path = RESULTS / f"retrieval_report_{stamp}.md"  # timestamped: never overwrite an earlier report
    md_path.write_text(render_md(report), encoding="utf-8")
    print(f"\nWrote {json_path}\nWrote {md_path}")
    h = headline
    print(f"Production  inc: nDCG@10={_f(h['inc'].get('nDCG@10'))} R@20={_f(h['inc'].get('R@20'))} "
          f"MRR={_f(h['inc'].get('MRR'))} | pol: nDCG@10={_f(h['pol'].get('nDCG@10'))} R@20={_f(h['pol'].get('R@20'))}")
    return report


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
    obs, h, c, a = [], rep["headline"], rep["checks"], rep["ablations"]
    get = lambda cfg, m: (a.get(cfg) or {}).get("inc", {}).get(m)
    sr = rep["stage_reach"]
    if sr and h["inc"].get("R@20") is not None:
        best = max(sr, key=lambda s: sr[s]["inc"] or 0)
        if sr[best]["inc"] is not None:
            gap = sr[best]["inc"] - h["inc"]["R@20"]
            obs.append(f"Best stage reach (incentive) is {_f(sr[best]['inc'])} at `{best}` vs final R@20 "
                       f"{_f(h['inc']['R@20'])} (gap {_f(gap)}). " +
                       ("Relevant items are found but cut later: widen the pool passed to later stages."
                        if gap > 0.1 else "Later stages lose little."))
    for name, label in rep["ablation_labels"].items():
        for m in ("nDCG@10", "R@20"):
            vx, vy = get(name, m), h["inc"].get(m)
            if vx is not None and vy is not None:
                d = vy - vx
                verdict = "helps" if d > 0.02 else "hurts" if d < -0.02 else "is neutral"
                obs.append(f"Production vs {label}: incentive {m} {_f(vx)} -> {_f(vy)} ({d:+.3f}); "
                           f"the difference {verdict}.")
    if "stage:vector" in a and "stage:rrf" in a:
        for m in ("nDCG@10", "R@20"):
            vx, vy = get("stage:vector", m), get("stage:rrf", m)
            if vx is not None and vy is not None:
                obs.append(f"Adding BM25 via RRF (stage vector -> rrf): incentive {m} {_f(vx)} -> {_f(vy)} ({vy - vx:+.3f}).")
    dc = rep["diagnosis_counts"].get("incentive") or {}
    if dc:
        top = max(dc, key=dc.get)
        obs.append(f"Most common reason a relevant incentive misses the top 10: `{top}` ({dc[top]} of {sum(dc.values())}).")
    if c.get("geo_violation_rate"):
        obs.append(f"Geography violation rate is {_f(c['geo_violation_rate'])} (should be 0): check geography tags.")
    if c.get("profiles_with_no_results"):
        obs.append(f"{c['profiles_with_no_results']} profiles got no results at all.")
    if (c.get("dup_rate@10") or 0) > 0.4:
        obs.append(f"Duplicate rate@10 is {_f(c['dup_rate@10'])}: top results are crowded by a few parents. "
                   "Consider parent-level dedupe/diversification before the report.")
    if c.get("corpus_coverage_parents") is not None and c["corpus_coverage_parents"] < 0.6:
        obs.append(f"Only {_f(c['corpus_coverage_parents'])} of parents appear in any top-{rep['meta']['top_k']}: "
                   f"{len(rep['never_retrieved_parents'])} parents are never surfaced (see Never-retrieved).")
    if c.get("profiles_with_zero_bm25_hits"):
        obs.append(f"{c['profiles_with_zero_bm25_hits']} profiles get zero BM25 hits, so BM25 contributes nothing for them "
                   "(plainto_tsquery ANDs every term). Consider OR-ed terms.")
    if c.get("validity_rate") is not None and c["validity_rate"] < 1:
        obs.append(f"Validity rate {_f(c['validity_rate'])}: some results have end_year in the past.")
    if c.get("trace_mismatches"):
        obs.append(f"Trace 'final' stage differs from the returned list for {len(c['trace_mismatches'])} profiles: "
                   "the trace hook in retrieve_policies is out of date.")
    return obs


def render_md(rep):
    m, h, c = rep["meta"], rep["headline"], rep["checks"]
    L = ["# Retrieval evaluation report", "",
         f"Generated {m['timestamp']} · git `{(m['git_sha'] or '')[:10]}` · {m['n_profiles']} profiles, "
         f"{m['n_labels']} labels · top_k={m['top_k']} · relevant = grade ≥ {m['rel_threshold']}", "",
         f"Profiles `{m['profiles_file']}` ({m['profiles_sha256']}), labels `{m['labels_file']}` ({m['labels_sha256']})", "",
         f"Filters passed (from {m['filter_source']}): `{', '.join(m['filter_keys'])}` · "
         f"trace: {'yes, stages ' + ' → '.join(m['stages']) if m['trace_supported'] else 'not supported'}", "",
         f"Retriever config: `{json.dumps(m['trace_config'])}` · knobs: `{json.dumps(m['knobs'])}`", ""]
    if rep["dataset_warnings"]:
        L += ["## Dataset warnings", ""] + [f"- {w}" for w in rep["dataset_warnings"][:50]] + [""]

    cols = [f"{x}@{k}" for x in ("R", "P", "HR", "nDCG", "MAP") for k in (5, 10, 20)] + ["MRR"]
    L += ["## Headline metrics (production `retrieve_policies`)", "",
          _table(["level"] + cols, [[lvl] + [h[key].get(cc) for cc in cols] for lvl, key in
                                    (("incentive", "inc"), ("policy", "pol"))]), "",
          "Policy level: results deduped by parent (first occurrence), grade = max grade of its incentives.", ""]

    if rep["ablations"] or rep["skipped_ablations"]:
        acols = ["R@5", "R@10", "R@20", "nDCG@10", "MRR", "MAP@10"]
        rows = [["production"] + [h["inc"].get(x) for x in acols] + [h["pol"].get(x) for x in acols]]
        for cfg in [f"stage:{s}" for s in m["stages"]] + list(rep["ablation_labels"]):
            if cfg in rep["ablations"]:
                a = rep["ablations"][cfg]
                name = cfg if cfg.startswith("stage:") else rep["ablation_labels"][cfg]
                rows.append([name] + [a["inc"].get(x) for x in acols] + [a["pol"].get(x) for x in acols])
        L += ["## Ablations", "",
              "`stage:X` rows score the ranked list each pipeline stage produced (from the trace); the other rows "
              "re-run production with one knob changed.", "",
              _table(["config"] + [f"inc {x}" for x in acols] + [f"pol {x}" for x in acols], rows), ""]
        if rep["skipped_ablations"]:
            L += ["Skipped (code no longer has the knob): " +
                  "; ".join(f"{k}: {v}" for k, v in rep["skipped_ablations"].items()), ""]
    if rep["stage_reach"]:
        L += ["## Stage reach", "",
              "Share of relevant items present anywhere in each stage's list (no cutoff). A drop between stages "
              "shows where relevant items are lost.", "",
              _table(["stage", "avg list length", "inc reach", "pol reach"],
                     [[s, v["avg_len"], v["inc"], v["pol"]] for s, v in rep["stage_reach"].items()]), ""]

    sc = ["n", "inc_nDCG@10", "inc_R@20", "inc_MRR", "pol_nDCG@10", "pol_R@20", "pol_MRR", "pol_HR@5"]
    L += ["## Slices", "", _table(["slice"] + sc, [[k] + [v.get(x) for x in sc] for k, v in sorted(rep["slices"].items())]), ""]

    ck = [("Geography violation rate", c["geo_violation_rate"]), ("Profiles with a geo violation", c["profiles_with_geo_violation"]),
          ("Profiles with no results", c["profiles_with_no_results"]),
          *[(f"Unique parents@{k}", c.get(f"unique_parents@{k}")) for k in KS],
          *[(f"Duplicate rate@{k}", c.get(f"dup_rate@{k}")) for k in KS],
          ("Industry match rate (top k)", c.get("industry_match_rate")), ("Size match rate (top k)", c.get("size_match_rate")),
          ("Validity rate", c.get("validity_rate")),
          ("Mean BM25 hits (from trace)", c.get("mean_bm25_hits")),
          ("Profiles with zero BM25 hits", c.get("profiles_with_zero_bm25_hits")),
          (f"Corpus coverage, rows (of {c['n_rows']})", c["corpus_coverage_rows"]),
          (f"Corpus coverage, parents (of {c['n_parents']})", c["corpus_coverage_parents"]),
          ("Cold start (s, first call incl. model load)", c["cold_start_s"]),
          ("Latency p50 (s)", c["latency_p50_s"]), ("Latency p95 (s)", c["latency_p95_s"]),
          ("Trace/return mismatches", ", ".join(c["trace_mismatches"]) or "none")]
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
              _table(["#", "grade", "parent", "incentive", "geo", "industries", "sim", "ce score", "boost"],
                     [[r["rank"], r["grade"], (r["parent"] or "")[:60], (r["incentive"] or "")[:60],
                       ", ".join(r["geo"] or [])[:30], ", ".join(r["industries"] or [])[:40],
                       r["similarity"], r["incentive_score"], r["metadata_boost"]] for r in pp["top10"]]), ""]

    L += ["## Never-retrieved", "", "Relevant labelled incentives that never appear in any profile's top-k:", ""]
    L += [f"- {n['key'][0]} / {n['key'][1]} (profiles: {', '.join(n['profiles'])}{'' if n['in_db'] else '; NOT IN DB'})"
          for n in rep["never_retrieved_relevant"]] or ["- none"]
    L += ["", f"Parents never retrieved for any profile ({len(rep['never_retrieved_parents'])}):", ""]
    L += [f"- {p}" for p in rep["never_retrieved_parents"]] or ["- none"]
    L += ["", "## Observations / what to tune", ""] + [f"- {o}" for o in _observations(rep)] + [""]
    return "\n".join(L)


# ── Self-test (no DB, no models) ─────────────────────────────────────────────

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
    assert abs(ap_at_k(g, n_rel, 5, thr) - (1 + 2 / 3) / 3) < 1e-9
    assert ap_at_k([0, 0], 2, 2, thr) == 0.0
    assert percentile([1, 2, 3, 4], 50) == 2.5

    # Adapter + diagnosis against a fake retriever: proves the evaluator only depends on the
    # signature and the trace, and degrades when either changes.
    import types
    row = lambda pid, parent, inc: {"policy_id": pid, "parent_policy_name": parent, "incentive_name": inc,
                                    "applicable_geographies": ["Karnataka"]}
    a, b, c_ = row(1, "P", "a"), row(2, "P", "b"), row(3, "Q", "c")

    def fake(query, conn, top_k=5, industry=None, geography=None, trace=None, newfilter=None):
        if trace is not None:
            trace.update({"stages": ["vector", "rrf", "final"], "vector": [a, b, c_], "rrf": [a, b], "final": [a]})
        return [a]
    mod = types.SimpleNamespace(retrieve_policies=fake, _BOOST=1.5, rerank_with_cross_encoder=lambda q, t: [0.0] * len(t))
    R = Retriever.__new__(Retriever)
    R.module, R.fn, R.params = mod, fake, set(inspect.signature(fake).parameters)
    R.filter_keys = tuple(k for k in ("industry", "geography", "enquiry_purpose") if k in R.params)
    R.supports_trace = True
    assert R.filter_keys == ("industry", "geography")  # unsupported production key is dropped, not passed
    tr = {}
    R("q", None, 5, {"geography": "Karnataka"}, trace=tr)
    db_rows = [{"applicable_geographies": ["Karnataka"]}]
    assert diagnose(("Q", "c"), INC, tr, "Karnataka", db_rows, dedupe(tr["final"], INC), 10) == "dropped_after_vector"
    assert diagnose(("P", "b"), INC, tr, "Karnataka", db_rows, dedupe(tr["final"], INC), 10) == "dropped_after_rrf"
    assert diagnose(("Z", "z"), INC, tr, "Karnataka", db_rows, [], 10) == "never_retrieved"
    assert diagnose(("Z", "z"), INC, tr, "Goa", db_rows, [], 10) == "filtered_by_geography"
    assert diagnose(("Z", "z"), INC, None, None, db_rows, [], 10) == "not_returned (no trace)"
    assert R.knobs() == {"_BOOST": 1.5}
    with patched(mod, {"_BOOST": 0.0, "_GONE": 1}) as missing:
        assert mod._BOOST == 0.0 and missing == ["_GONE"]
    assert mod._BOOST == 1.5 and not hasattr(mod, "_GONE")
    memo = memoize_models(mod)
    assert set(memo) == {"rerank_with_cross_encoder"}
    print("selftest OK")


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
