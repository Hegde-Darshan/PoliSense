import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

# ── Colours ────────────────────────────────────────────────────────────────────
NAVY        = colors.HexColor("#1B3A6B")
NAVY_LIGHT  = colors.HexColor("#2B5598")
ROW_ALT     = colors.HexColor("#EBF2FB")
ROW_WHITE   = colors.white
CALLOUT_BG  = colors.HexColor("#FFF8E1")
CALLOUT_BORDER = colors.HexColor("#F9A825")
LABEL_BG    = colors.HexColor("#F0F4FA")

# ── Page geometry ──────────────────────────────────────────────────────────────
PAGE_W, PAGE_H = A4
MARGIN = 1.5 * cm
TEXT_W = PAGE_W - 2 * MARGIN

# ── Styles ─────────────────────────────────────────────────────────────────────
_base = getSampleStyleSheet()

STYLES = {
    "doc_title": ParagraphStyle(
        "doc_title",
        fontName="Helvetica-Bold",
        fontSize=16,
        textColor=NAVY,
        spaceAfter=2,
    ),
    "doc_subtitle": ParagraphStyle(
        "doc_subtitle",
        fontName="Helvetica",
        fontSize=9,
        textColor=colors.grey,
        spaceAfter=0,
    ),
    "section_title": ParagraphStyle(
        "section_title",
        fontName="Helvetica-Bold",
        fontSize=11,
        textColor=NAVY,
        spaceBefore=14,
        spaceAfter=4,
    ),
    "rec_title": ParagraphStyle(
        "rec_title",
        fontName="Helvetica-Bold",
        fontSize=10,
        textColor=colors.white,
        leading=14,
    ),
    "label": ParagraphStyle(
        "label",
        fontName="Helvetica-Bold",
        fontSize=8.5,
        textColor=NAVY,
    ),
    "value": ParagraphStyle(
        "value",
        fontName="Helvetica",
        fontSize=8.5,
        textColor=colors.black,
        leading=12,
    ),
    "benefit_headline": ParagraphStyle(
        "benefit_headline",
        fontName="Helvetica-Bold",
        fontSize=9,
        textColor=NAVY_LIGHT,
        spaceBefore=6,
        spaceAfter=4,
        leading=13,
    ),
    "body": ParagraphStyle(
        "body",
        fontName="Helvetica",
        fontSize=8.5,
        textColor=colors.HexColor("#333333"),
        leading=13,
        spaceAfter=4,
    ),
    "callout": ParagraphStyle(
        "callout",
        fontName="Helvetica-Oblique",
        fontSize=8.5,
        textColor=colors.HexColor("#5D4037"),
        leading=13,
        leftIndent=8,
        rightIndent=8,
    ),
    "footer": ParagraphStyle(
        "footer",
        fontName="Helvetica",
        fontSize=7,
        textColor=colors.grey,
    ),
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _p(text: str, style: str = "body") -> Paragraph:
    safe = str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return Paragraph(safe, STYLES[style])


def _join(lst, fallback: str = "Not specified") -> str:
    if not lst:
        return fallback
    filtered = [str(x) for x in lst if x]
    return ", ".join(filtered) if filtered else fallback


def _validity(start_year, end_year) -> str:
    if start_year and end_year:
        return f"{start_year} – {end_year}"
    if start_year:
        return f"{start_year} – Ongoing"
    return "Not specified"


def _two_col_table(rows: list[tuple], col_widths=None) -> Table:
    """Build a two-column label/value table with alternating row shading."""
    if col_widths is None:
        col_widths = [TEXT_W * 0.32, TEXT_W * 0.68]

    data = []
    for label, value in rows:
        data.append([_p(label, "label"), _p(value, "value")])

    style = TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), LABEL_BG),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")),
        ("ROWBACKGROUNDS", (1, 0), (1, -1), [ROW_WHITE, ROW_ALT]),
    ])

    return Table(data, colWidths=col_widths, style=style, hAlign="LEFT")


_SIMILARITY_WARN_THRESHOLD = 0.60


def _assess_retrieval(results: list, filters: dict) -> list[str]:
    """Return a list of plain-English warnings if retrieval quality is poor."""
    if not results:
        return []

    warnings = []

    top_score = results[0]["similarity_score"]
    if top_score < _SIMILARITY_WARN_THRESHOLD:
        warnings.append(
            f"Low semantic relevance (top score: {top_score:.2f}): the retrieved policies "
            "may not directly address the stated business need. Consider refining the business "
            "description or broadening the filters."
        )

    industry = filters.get("industry")
    if industry:
        all_fallback = all(
            industry not in (r.get("applicable_industries") or [])
            for r in results
        )
        if all_fallback:
            warnings.append(
                f"No sector-specific policies found for '{industry}'. All results shown are "
                "broadly applicable across industries — a sector-targeted search returned no matches."
            )

    geography = filters.get("geography")
    if geography:
        all_fallback = all(
            not any(geography.lower() in g.lower() for g in (r.get("applicable_geographies") or []))
            for r in results
        )
        if all_fallback:
            warnings.append(
                f"No state-specific policies found for '{geography}'. All results shown are "
                "national-level schemes — no state-specific instruments were retrieved."
            )

    business_size = filters.get("business_size")
    if business_size:
        all_fallback = all(
            business_size not in (r.get("applicable_business_sizes") or [])
            for r in results
        )
        if all_fallback:
            warnings.append(
                f"No size-specific policies found for '{business_size}'. All results shown apply "
                "to businesses of all sizes — no size-targeted instruments were retrieved."
            )

    return warnings


def _warning_banner(warnings: list[str]) -> Table:
    """Red-tinted warning box listing retrieval quality issues."""
    WARN_BG     = colors.HexColor("#FFF3F3")
    WARN_BORDER = colors.HexColor("#C62828")
    WARN_TEXT   = colors.HexColor("#B71C1C")

    header_style = ParagraphStyle(
        "warn_header",
        fontName="Helvetica-Bold",
        fontSize=8.5,
        textColor=WARN_TEXT,
        spaceAfter=4,
    )
    item_style = ParagraphStyle(
        "warn_item",
        fontName="Helvetica",
        fontSize=8.5,
        textColor=WARN_TEXT,
        leading=13,
        leftIndent=10,
        spaceAfter=2,
    )

    content = [Paragraph("Retrieval Quality Notice", header_style)]
    for w in warnings:
        content.append(Paragraph(f"•  {w}", item_style))

    return Table(
        [content],
        colWidths=[TEXT_W - 2],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), WARN_BG),
            ("BOX", (0, 0), (-1, -1), 1, WARN_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]),
    )


def _callout(text: str) -> Table:
    """Render a coloured callout box."""
    inner = Table(
        [[_p(text, "callout")]],
        colWidths=[TEXT_W - 2],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), CALLOUT_BG),
            ("LINECOLOR", (0, 0), (-1, -1), CALLOUT_BORDER),
            ("BOX", (0, 0), (-1, -1), 1, CALLOUT_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ]),
    )
    return inner


def _rec_header_table(rank: int, incentive_name: str) -> Table:
    """Dark-navy header banner for each recommendation block."""
    label = f"Recommendation #{rank}  —  {incentive_name}"
    cell = Table(
        [[_p(label, "rec_title")]],
        colWidths=[TEXT_W],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), NAVY),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ]),
    )
    return cell


# ── Page template (header + footer) ───────────────────────────────────────────

def _make_doc(output_path: str, business_name: str, generated: str):
    """Create a BaseDocTemplate with a page header and footer."""

    def _on_page(canvas, doc):
        canvas.saveState()
        # Header bar
        canvas.setFillColor(NAVY)
        canvas.rect(MARGIN, PAGE_H - MARGIN - 0.7 * cm, TEXT_W, 0.7 * cm, fill=1, stroke=0)
        canvas.setFont("Helvetica-Bold", 8)
        canvas.setFillColor(colors.white)
        canvas.drawString(MARGIN + 4, PAGE_H - MARGIN - 0.45 * cm, "PoliSense — Policy Recommendations")
        right_label = f"{business_name}  |  {generated}  |  Page {doc.page}"
        canvas.drawRightString(PAGE_W - MARGIN - 4, PAGE_H - MARGIN - 0.45 * cm, right_label)
        # Footer
        canvas.setFont("Helvetica", 6.5)
        canvas.setFillColor(colors.grey)
        canvas.drawString(MARGIN, 0.7 * cm, "Generated by PoliSense. This report is for informational purposes only.")
        canvas.restoreState()

    frame = Frame(
        MARGIN,
        MARGIN + 0.5 * cm,
        TEXT_W,
        PAGE_H - 2 * MARGIN - 1.4 * cm,
        id="main",
    )
    template = PageTemplate(id="main", frames=[frame], onPage=_on_page)
    doc = BaseDocTemplate(
        output_path,
        pagesize=A4,
        pageTemplates=[template],
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN + 1.0 * cm,
        bottomMargin=MARGIN + 0.5 * cm,
    )
    return doc


# ── Main public function ───────────────────────────────────────────────────────

def generate_pdf(query_name: str, entry: dict, output_path: str) -> None:
    """
    Generate a professional PDF report for a single retrieval result.

    Args:
        query_name: Human-readable label for this query (used in the report title).
        entry:      Dict with keys: query (str), profile (dict), filters (dict), results (list).
        output_path: Absolute or relative path for the output .pdf file.
    """
    profile   = entry.get("profile", {})
    query     = entry.get("query", "")
    results   = entry.get("results", [])

    sub_time = entry.get("submission_time")
    submitted_str = sub_time.strftime("%d %b %Y, %H:%M") if sub_time else None
    generated = datetime.datetime.now().strftime("%d %b %Y, %H:%M")

    business_name = profile.get("business_name") or query_name
    doc = _make_doc(output_path, business_name, generated)

    story = []

    # ── Document title ─────────────────────────────────────────────────────────
    story.append(_p("Policy Recommendations Report", "doc_title"))
    subtitle = f"Prepared for: {business_name}  ·  Report generated: {generated}"
    if submitted_str:
        subtitle += f"  ·  Form submitted: {submitted_str}"
    story.append(_p(subtitle, "doc_subtitle"))
    story.append(HRFlowable(width=TEXT_W, thickness=1.5, color=NAVY, spaceAfter=8))

    # ── Section A: Client Brief ────────────────────────────────────────────────
    story.append(_p("Client Brief", "section_title"))

    brief_rows = [
        ("Business Name",     profile.get("business_name") or "Not specified"),
        ("Industry",          profile.get("industry")      or "Not specified"),
        ("Location",          profile.get("geography")     or "Not specified"),
        ("Business Size",     profile.get("business_size") or "Not specified"),
        ("Support Category",  profile.get("enquiry_purpose") or profile.get("category") or "Not specified"),
        ("Business Focus",    query                         or "Not specified"),
    ]
    story.append(_two_col_table(brief_rows))

    # ── Section B: Policy Recommendations ─────────────────────────────────────
    story.append(_p("Policy Recommendations", "section_title"))

    filters = entry.get("filters", {})
    warnings = _assess_retrieval(results, filters)
    if warnings:
        story.append(Spacer(1, 4))
        story.append(_warning_banner(warnings))
        story.append(Spacer(1, 6))

    if not results:
        story.append(_p(
            "No matching policies were identified for the provided profile and query. "
            "Consider broadening the industry or geography filters and rerunning the analysis.",
            "body",
        ))
    else:
        # Deduplicate by policy_id while preserving order
        seen_ids: set = set()
        unique_results = []
        for r in results:
            pid = r.get("policy_id")
            if pid not in seen_ids:
                seen_ids.add(pid)
                unique_results.append(r)

        for rank, r in enumerate(unique_results, start=1):
            pd_  = r.get("policy_details")  or {}
            id_  = r.get("incentive_details") or {}

            story.append(Spacer(1, 6))
            story.append(_rec_header_table(rank, r.get("incentive_name", "—")))

            # Policy details table
            detail_rows = [
                ("Policy Framework",  r.get("parent_policy_name") or "—"),
                ("Scheme",            r.get("policy_name")        or "—"),
                ("Incentive",         r.get("incentive_name")     or "—"),
                ("Category",          r.get("category")           or "—"),
                ("Target Industries", _join(r.get("applicable_industries"))),
                ("Applicable Sizes",  _join(r.get("applicable_business_sizes"))),
                ("Geography",         _join(r.get("applicable_geographies"))),
                ("Validity",          _validity(r.get("start_year"), r.get("end_year"))),
            ]
            story.append(_two_col_table(detail_rows))
            story.append(Spacer(1, 6))

            # Key benefit headline
            benefit_headline = id_.get("benefit_headline") or pd_.get("benefit_headline")
            if benefit_headline:
                story.append(_p(benefit_headline, "benefit_headline"))

            # Benefit description
            description = id_.get("description")
            if description:
                story.append(_p(description, "body"))

            # Tier 2 callout
            story.append(Spacer(1, 4))
            story.append(_callout(
                "Detailed eligibility breakdown and calculated benefit quantum are available "
                "in the accompanying Full Eligibility & Benefit Report."
            ))

            # Divider between recommendations (not after the last one)
            if rank < len(unique_results):
                story.append(Spacer(1, 8))
                story.append(HRFlowable(width=TEXT_W, thickness=0.5, color=colors.HexColor("#CCCCCC")))

    doc.build(story)
