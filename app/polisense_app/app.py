"""
app.py
======
PoliSense — Streamlit front-end.

Renders the Business Profile Questionnaire, builds a `business_profile`
dict from the answers, runs it through the rule-based retrieval pipeline in
`retrieval.py`, and displays the ranked policy matches.

Run locally:
    streamlit run app.py

All app activity (form submissions, retrieval steps, errors) is written to
`logs.log` (see `logging_config.py`) in addition to stdout.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import streamlit as st

from config import APP_TITLE, FINAL_N, MMR_LAMBDA, TOP_K
from logging_config import get_logger
from questionnaire import QUESTIONNAIRE
from retrieval import RetrievalError, find_matching_policies, test_connection

logger = get_logger(__name__)

st.set_page_config(page_title=APP_TITLE, page_icon="🏛️", layout="wide")


# ── Session bookkeeping ─────────────────────────────────────────────────────

if "session_id" not in st.session_state:
    st.session_state.session_id = uuid.uuid4().hex[:8]
    logger.info("New Streamlit session started: session_id=%s", st.session_state.session_id)

SESSION_ID = st.session_state.session_id


# ── Helpers ──────────────────────────────────────────────────────────────────

def render_field(field: dict[str, Any]) -> Any:
    """Render a single questionnaire field widget and return its value."""
    key = f"field_{field['key']}"
    widget = field["widget"]
    label = field["label"]

    if widget == "text":
        return st.text_input(label, value=field.get("default", ""), key=key)
    if widget == "textarea":
        return st.text_area(label, value=field.get("default", ""), key=key)
    if widget == "number":
        return st.number_input(
            label, value=int(field.get("default", 0)), step=1, format="%d", key=key
        )
    if widget == "select":
        options = field["options"]
        default = field.get("default")
        index = options.index(default) if default in options else 0
        return st.selectbox(label, options, index=index, key=key)
    if widget == "multiselect":
        return st.multiselect(label, field["options"], default=field.get("default", []), key=key)

    raise ValueError(f"Unknown widget type: {widget}")  # defensive — should never happen


def build_profile_from_form(answers: dict[str, Any]) -> dict[str, Any]:
    """
    Convert raw form answers into the flat business_profile dict shape the
    retrieval pipeline expects (matches the reference sample profiles).
    """
    profile = dict(answers)

    # Clean up empty optional fields so they don't pollute filters / query text
    profile = {k: v for k, v in profile.items() if v not in (None, "", [])}

    return profile


def render_sidebar() -> None:
    with st.sidebar:
        st.markdown("### ⚙️ Retrieval settings")
        st.session_state.setdefault("top_k", TOP_K)
        st.session_state.setdefault("final_n", FINAL_N)
        st.session_state.setdefault("mmr_lambda", MMR_LAMBDA)

        st.number_input("Candidates before reranking (top_k)", min_value=5, max_value=100, key="top_k")
        st.number_input("Results to show (final_n)", min_value=1, max_value=20, key="final_n")
        st.slider(
            "MMR λ (relevance ↔ diversity)", min_value=0.0, max_value=1.0, step=0.05,
            key="mmr_lambda",
            help="1.0 = pure relevance, 0.0 = pure diversity across results.",
        )

        st.markdown("---")
        st.markdown("### 🩺 Database")
        if st.button("Test DB connection"):
            with st.spinner("Testing connection..."):
                ok = test_connection()
            if ok:
                st.success("Connected.")
            else:
                st.error("Could not connect. Check server logs / .env settings.")

        st.markdown("---")
        st.caption(f"Session: `{SESSION_ID}`")


def render_result_card(rank: int, match: dict[str, Any]) -> None:
    policy_details = match.get("policy_details") or {}
    incentive_details = match.get("incentive_details") or {}

    title = match.get("policy_name") or "Untitled policy"
    subtitle_bits = []
    if match.get("parent_policy_name"):
        subtitle_bits.append(match["parent_policy_name"])
    if match.get("incentive_name"):
        subtitle_bits.append(match["incentive_name"])
    subtitle = " · ".join(subtitle_bits)

    with st.container(border=True):
        col1, col2 = st.columns([5, 1])
        with col1:
            st.markdown(f"#### #{rank}  {title}")
            if subtitle:
                st.caption(subtitle)
        with col2:
            st.metric("MMR score", f"{match.get('mmr_score', 0):.3f}")

        meta_cols = st.columns(4)
        meta_cols[0].markdown(f"**Category**\n\n{match.get('category') or '—'}")
        meta_cols[1].markdown(f"**Geography**\n\n{match.get('geography') or '—'}")
        meta_cols[2].markdown(f"**Business size**\n\n{match.get('business_size') or '—'}")
        meta_cols[3].markdown(f"**Similarity**\n\n{match.get('similarity', 0):.3f}")

        summary = policy_details.get("policy_summary")
        if summary:
            st.markdown(f"**Summary:** {summary}")

        eligibility = policy_details.get("eligibility_criteria")
        if eligibility:
            with st.expander("Eligibility criteria"):
                st.write(eligibility)

        benefits = incentive_details.get("benefits") or {}
        if benefits:
            with st.expander("Benefits"):
                for k, v in benefits.items():
                    st.markdown(f"- **{k}**: {v}")

        goals = policy_details.get("policy_goals") or []
        attrs = policy_details.get("special_attributes") or []
        if goals or attrs:
            with st.expander("Policy goals & special attributes"):
                if goals:
                    st.markdown("**Goals:** " + ", ".join(goals))
                if attrs:
                    st.markdown("**Special attributes:** " + ", ".join(attrs))


# ── Main layout ─────────────────────────────────────────────────────────────

def main() -> None:
    st.title("🏛️ PoliSense")
    st.markdown(
        "Fill in your business profile below to get matched with the most "
        "relevant government policies and incentive schemes."
    )

    render_sidebar()

    answers: dict[str, Any] = {}

    with st.form("profile_form"):
        for section in QUESTIONNAIRE:
            st.markdown(f"### {section['title']}")
            st.caption(section["info"])
            for field in section["fields"]:
                answers[field["key"]] = render_field(field)
            st.divider()

        submitted = st.form_submit_button("🔍 Find matching policies", type="primary", use_container_width=True)

    if not submitted:
        return

    logger.info("[session=%s] Form submitted.", SESSION_ID)

    profile = build_profile_from_form(answers)
    logger.info("[session=%s] Built business_profile: %s", SESSION_ID, profile)

    if not profile.get("industry") and not profile.get("state"):
        st.warning("Please fill in at least your industry and state so we can find relevant matches.")
        logger.warning("[session=%s] Submission rejected: missing industry/state.", SESSION_ID)
        return

    top_k = st.session_state["top_k"]
    final_n = st.session_state["final_n"]
    mmr_lambda = st.session_state["mmr_lambda"]

    start = time.perf_counter()
    with st.spinner("Matching your business against available policies..."):
        try:
            results = find_matching_policies(
                profile, top_k=top_k, final_n=final_n, lmbda=mmr_lambda
            )
        except RetrievalError as exc:
            elapsed = time.perf_counter() - start
            logger.error("[session=%s] Retrieval failed after %.2fs: %s", SESSION_ID, elapsed, exc)
            st.error(f"Something went wrong while searching for policies: {exc}")
            return
        except Exception:
            elapsed = time.perf_counter() - start
            logger.exception("[session=%s] Unexpected error after %.2fs.", SESSION_ID, elapsed)
            st.error("An unexpected error occurred. Please try again or contact support.")
            return

    elapsed = time.perf_counter() - start
    logger.info("[session=%s] Retrieval succeeded in %.2fs, %d result(s).", SESSION_ID, elapsed, len(results))

    st.markdown(f"## 🎯 Top {len(results)} matches")
    if not results:
        st.info("No matching policies were found. Try broadening your answers (e.g. leave state blank).")
        return

    st.caption(f"Search completed in {elapsed:.2f}s")

    for match in results:
        render_result_card(match.get("mmr_rank", 0), match)


if __name__ == "__main__":
    main()
