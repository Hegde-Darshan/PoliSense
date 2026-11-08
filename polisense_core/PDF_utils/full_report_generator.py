"""
Full Eligibility & Benefit Quantum Report generator.

Produces an exhaustive PDF for each retrieved policy showing:
  - Policy match score and overall eligibility status
  - Per-criterion eligibility checklist (MET / NOT_MET / UNCERTAIN)
  - Calculated benefit quantum with step-by-step arithmetic
  - Application authority, process, and deadline

Shares the visual language (colors, typography) of report_generator.py.

Public API:
    generate_full_report_pdf(query_name, entry, output_path)
"""

import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
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

# ── Shared colours ─────────────────────────────────────────────────────────────
NAVY        = colors.HexColor("#1B3A6B")
NAVY_LIGHT  = colors.HexColor("#2B5598")
ROW_ALT     = colors.HexColor("#EBF2FB")
ROW_WHITE   = colors.white
LABEL_BG    = colors.HexColor("#F0F4FA")

# Status row colours
MET_BG          = colors.HexColor("#E8F5E9")
MET_TEXT        = colors.HexColor("#1B5E20")
NOT_MET_BG      = colors.HexColor("#FFEBEE")
NOT_MET_TEXT    = colors.HexColor("#B71C1C")
UNCERTAIN_BG    = colors.HexColor("#FFF8E1")
UNCERTAIN_TEXT  = colors.HexColor("#E65100")

# Eligibility badge fill colours
BADGE_ELIGIBLE  = colors.HexColor("#2E7D32")
BADGE_PARTIAL   = colors.HexColor("#E65100")
BADGE_NOT       = colors.HexColor("#C62828")

CALLOUT_INFO_BG     = colors.HexColor("#E3F2FD")
CALLOUT_INFO_BORDER = colors.HexColor("#1565C0")

# ── Page geometry ──────────────────────────────────────────────────────────────
PAGE_W, PAGE_H = A4
MARGIN  = 1.5 * cm
TEXT_W  = PAGE_W - 2 * MARGIN

# ── Styles ─────────────────────────────────────────────────────────────────────
STYLES = {
    "doc_title": ParagraphStyle("doc_title", fontName="Helvetica-Bold", fontSize=16,
                                textColor=NAVY, spaceAfter=2),
    "doc_subtitle": ParagraphStyle("doc_subtitle", fontName="Helvetica", fontSize=9,
                                   textColor=colors.grey, spaceAfter=0),
    "section_title": ParagraphStyle("section_title", fontName="Helvetica-Bold", fontSize=11,
                                    textColor=NAVY, spaceBefore=14, spaceAfter=4),
    "sub_section": ParagraphStyle("sub_section", fontName="Helvetica-Bold", fontSize=9,
                                  textColor=NAVY_LIGHT, spaceBefore=8, spaceAfter=3),
    "rec_title": ParagraphStyle("rec_title", fontName="Helvetica-Bold", fontSize=10,
                                textColor=colors.white, leading=14),
    "badge": ParagraphStyle("badge", fontName="Helvetica-Bold", fontSize=8,
                             textColor=colors.white),
    "label": ParagraphStyle("label", fontName="Helvetica-Bold", fontSize=8.5, textColor=NAVY),
    "value": ParagraphStyle("value", fontName="Helvetica", fontSize=8.5,
                             textColor=colors.black, leading=12),
    "benefit_headline": ParagraphStyle("benefit_headline", fontName="Helvetica-Bold",
                                       fontSize=9, textColor=NAVY_LIGHT,
                                       spaceBefore=6, spaceAfter=4, leading=13),
    "body": ParagraphStyle("body", fontName="Helvetica", fontSize=8.5,
                            textColor=colors.HexColor("#333333"), leading=13, spaceAfter=4),
    "source_text": ParagraphStyle("source_text", fontName="Helvetica-Oblique", fontSize=7.5,
                                  textColor=colors.HexColor("#666666"), leading=11),
    "met_text": ParagraphStyle("met_text", fontName="Helvetica", fontSize=8.5,
                               textColor=MET_TEXT, leading=12),
    "not_met_text": ParagraphStyle("not_met_text", fontName="Helvetica", fontSize=8.5,
                                   textColor=NOT_MET_TEXT, leading=12),
    "uncertain_text": ParagraphStyle("uncertain_text", fontName="Helvetica", fontSize=8.5,
                                     textColor=UNCERTAIN_TEXT, leading=12),
    "footer": ParagraphStyle("footer", fontName="Helvetica", fontSize=7, textColor=colors.grey),
}


# ── Generic helpers ────────────────────────────────────────────────────────────

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


def _two_col_table(rows: list, col_widths=None) -> Table:
    if col_widths is None:
        col_widths = [TEXT_W * 0.32, TEXT_W * 0.68]
    data = [[_p(lbl, "label"), _p(val, "value")] for lbl, val in rows]
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


# ── Recommendation-specific helpers ───────────────────────────────────────────

def _rec_header(rank: int, incentive_name: str) -> Table:
    label = f"Recommendation #{rank}  —  {incentive_name}"
    return Table(
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


def _eligibility_badge_row(overall: str, similarity_score: float) -> Table:
    """Coloured badge showing overall eligibility + similarity score."""
    label_map = {
        "ELIGIBLE":           ("ELIGIBLE",           BADGE_ELIGIBLE),
        "PARTIALLY_ELIGIBLE": ("PARTIALLY ELIGIBLE",  BADGE_PARTIAL),
        "NOT_ELIGIBLE":       ("NOT ELIGIBLE",         BADGE_NOT),
    }
    label, fill = label_map.get(overall, ("UNKNOWN", colors.grey))
    score_str = f"Match Score: {similarity_score:.0%}"

    badge_cell = Table(
        [[_p(f"  {label}  ", "badge")]],
        colWidths=[TEXT_W * 0.3],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), fill),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]),
    )
    score_cell = _p(score_str, "label")

    return Table(
        [[badge_cell, score_cell]],
        colWidths=[TEXT_W * 0.35, TEXT_W * 0.65],
        style=TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]),
    )


def _eligibility_table(criteria_checks: list) -> Table:
    """
    Three-column eligibility checklist:
      Status | Criterion (what's required) | Company Assessment
    """
    STATUS_CONFIG = {
        "MET":       ("✓ MET",       MET_BG,       MET_TEXT,       "met_text"),
        "NOT_MET":   ("✗ NOT MET",   NOT_MET_BG,   NOT_MET_TEXT,   "not_met_text"),
        "UNCERTAIN": ("? UNCERTAIN", UNCERTAIN_BG, UNCERTAIN_TEXT, "uncertain_text"),
    }

    # Header row
    hdr_style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#BBBBBB")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ])

    data = [[
        Paragraph("Status", ParagraphStyle("hdr", fontName="Helvetica-Bold",
                                           fontSize=8, textColor=colors.white)),
        Paragraph("Criterion", ParagraphStyle("hdr", fontName="Helvetica-Bold",
                                              fontSize=8, textColor=colors.white)),
        Paragraph("Company Assessment", ParagraphStyle("hdr", fontName="Helvetica-Bold",
                                                       fontSize=8, textColor=colors.white)),
    ]]
    row_colors = []

    for i, check in enumerate(criteria_checks):
        status = check.get("status", "UNCERTAIN")
        lbl, bg, _, text_style = STATUS_CONFIG.get(status, STATUS_CONFIG["UNCERTAIN"])

        criterion_parts = [check.get("criteria_description") or check.get("field") or ""]
        assessment_parts = []
        if check.get("company_value"):
            assessment_parts.append(f"Provided: {check['company_value']}")
        if check.get("gap"):
            assessment_parts.append(f"Gap: {check['gap']}")
        if check.get("recommendation"):
            assessment_parts.append(f"Action: {check['recommendation']}")
        assessment = "\n".join(assessment_parts) if assessment_parts else "—"

        row = [
            _p(lbl, text_style),
            _p("\n".join(criterion_parts), text_style),
            _p(assessment, text_style),
        ]
        data.append(row)
        row_colors.append(("BACKGROUND", (0, i + 1), (-1, i + 1), bg))

    style = TableStyle([
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CCCCCC")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
    ] + row_colors)

    col_widths = [TEXT_W * 0.18, TEXT_W * 0.35, TEXT_W * 0.47]
    return Table(data, colWidths=col_widths, style=style, hAlign="LEFT")


def _benefit_table(benefit_calculations: list) -> Table:
    """
    Three-column benefit quantum table:
      Benefit (description + applicable_to) | Calculated Amount | Basis & Conditions
    """
    CONF_COLOR = {"HIGH": MET_TEXT, "MEDIUM": UNCERTAIN_TEXT, "LOW": NOT_MET_TEXT}

    data = [[
        Paragraph("Benefit", ParagraphStyle("hdr", fontName="Helvetica-Bold",
                                            fontSize=8, textColor=colors.white)),
        Paragraph("Quantum", ParagraphStyle("hdr", fontName="Helvetica-Bold",
                                            fontSize=8, textColor=colors.white)),
        Paragraph("Calculation & Conditions", ParagraphStyle("hdr", fontName="Helvetica-Bold",
                                                             fontSize=8, textColor=colors.white)),
    ]]

    for calc in benefit_calculations:
        desc = calc.get("benefit_description") or "—"
        applicable = calc.get("applicable_to")
        if applicable:
            desc_text = f"{desc}\n({applicable})"
        else:
            desc_text = desc

        not_applicable = calc.get("not_applicable_reason")
        if not_applicable:
            quantum_text = "Not applicable"
            basis_text = not_applicable
        else:
            effective = calc.get("effective_benefit") or calc.get("calculated_amount") or "—"
            quantum_text = effective
            parts = []
            if calc.get("calculation_steps"):
                parts.append(calc["calculation_steps"])
            if calc.get("cap_applied"):
                parts.append("Cap applied — see calculation")
            if calc.get("conditions"):
                parts.append(f"Conditions: {calc['conditions']}")
            basis_text = "\n".join(parts) if parts else "—"

        conf = calc.get("confidence", "LOW")
        conf_color = CONF_COLOR.get(conf, colors.grey)
        conf_style = ParagraphStyle(
            "conf", fontName="Helvetica", fontSize=8.5, textColor=conf_color, leading=12
        )

        # Source text footnote
        source = calc.get("source_text")
        source_cell_content = [_p(desc_text, "body")]
        if source:
            source_cell_content.append(
                Paragraph(f'"{source[:200]}{"..." if len(source) > 200 else ""}"', STYLES["source_text"])
            )

        data.append([
            source_cell_content,
            Paragraph(quantum_text, conf_style),
            _p(basis_text, "body"),
        ])

    style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CCCCCC")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [ROW_WHITE, ROW_ALT]),
    ])

    col_widths = [TEXT_W * 0.33, TEXT_W * 0.22, TEXT_W * 0.45]
    return Table(data, colWidths=col_widths, style=style, hAlign="LEFT")


def _missing_fields_callout(missing_fields: list) -> Table:
    """Blue info box listing profile fields that would improve the assessment."""
    info_style = ParagraphStyle(
        "info", fontName="Helvetica", fontSize=8.5,
        textColor=colors.HexColor("#0D47A1"), leading=13
    )
    hdr_style = ParagraphStyle(
        "info_hdr", fontName="Helvetica-Bold", fontSize=8.5,
        textColor=colors.HexColor("#0D47A1"), spaceAfter=2
    )
    content = [
        Paragraph("Improve this assessment:", hdr_style),
        Paragraph(
            "Providing these additional details would convert UNCERTAIN checks to definitive results: "
            + ", ".join(missing_fields.replace("_", " ").title() for missing_fields in missing_fields),
            info_style,
        ),
    ]
    return Table(
        [content],
        colWidths=[TEXT_W - 2],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), CALLOUT_INFO_BG),
            ("BOX", (0, 0), (-1, -1), 1, CALLOUT_INFO_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]),
    )


# ── Page template ──────────────────────────────────────────────────────────────

def _make_doc(output_path: str, business_name: str, generated: str) -> BaseDocTemplate:
    def _on_page(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(NAVY)
        canvas.rect(MARGIN, PAGE_H - MARGIN - 0.7 * cm, TEXT_W, 0.7 * cm, fill=1, stroke=0)
        canvas.setFont("Helvetica-Bold", 8)
        canvas.setFillColor(colors.white)
        canvas.drawString(MARGIN + 4, PAGE_H - MARGIN - 0.45 * cm,
                          "PoliSense — Full Eligibility & Benefit Report")
        right_label = f"{business_name}  |  {generated}  |  Page {doc.page}"
        canvas.drawRightString(PAGE_W - MARGIN - 4, PAGE_H - MARGIN - 0.45 * cm, right_label)
        canvas.setFont("Helvetica", 6.5)
        canvas.setFillColor(colors.grey)
        canvas.drawString(
            MARGIN, 0.7 * cm,
            "Generated by PoliSense. Benefit calculations are estimates based on submitted profile data. "
            "Final amounts are determined by the sanctioning authority."
        )
        canvas.restoreState()

    frame = Frame(
        MARGIN, MARGIN + 0.5 * cm,
        TEXT_W, PAGE_H - 2 * MARGIN - 1.4 * cm,
        id="main",
    )
    template = PageTemplate(id="main", frames=[frame], onPage=_on_page)
    return BaseDocTemplate(
        output_path,
        pagesize=A4,
        pageTemplates=[template],
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN + 1.0 * cm, bottomMargin=MARGIN + 0.5 * cm,
    )


# ── Main public function ───────────────────────────────────────────────────────

def generate_full_report_pdf(query_name: str, entry: dict, output_path: str) -> None:
    """
    Generate the full eligibility & benefit quantum PDF report.

    Args:
        query_name:   Human-readable label for this query.
        entry:        Dict with keys: query, profile, filters, results, submission_time.
                      Each result in results should carry:
                        eligibility_check  — output of check_eligibility()
                        benefit_calculations — output of calculate_benefits()
        output_path:  Path for the output .pdf file.
    """
    profile   = entry.get("profile", {})
    query     = entry.get("query", "")
    results   = entry.get("results", [])
    filters   = entry.get("filters", {})

    sub_time = entry.get("submission_time")
    submitted_str = sub_time.strftime("%d %b %Y, %H:%M") if sub_time else None
    generated = datetime.datetime.now().strftime("%d %b %Y, %H:%M")

    business_name = profile.get("business_name") or query_name
    doc = _make_doc(output_path, business_name, generated)
    story = []

    # ── Document title ─────────────────────────────────────────────────────────
    story.append(_p("Full Eligibility & Benefit Report", "doc_title"))
    subtitle = f"Prepared for: {business_name}  ·  Report generated: {generated}"
    if submitted_str:
        subtitle += f"  ·  Form submitted: {submitted_str}"
    story.append(_p(subtitle, "doc_subtitle"))
    story.append(HRFlowable(width=TEXT_W, thickness=1.5, color=NAVY, spaceAfter=8))

    # ── Section A: Client Brief ────────────────────────────────────────────────
    story.append(_p("Client Brief", "section_title"))
    brief_rows = [
        ("Business Name",     profile.get("business_name")         or "Not specified"),
        ("Industry",          profile.get("industry")              or "Not specified"),
        ("Location",          profile.get("geography")             or "Not specified"),
        ("Business Size",     profile.get("business_size")         or "Not specified"),
        ("Enterprise Type",   profile.get("enterprise_type")       or "Not specified"),
        ("Fixed Investment",  _fmt_investment(profile)),
        ("Employees",         _fmt_employees(profile)),
        ("Loan Amount",       _fmt_loan(profile)),
        ("Special Categories", _join(profile.get("special_attributes"))),
        ("Business Focus",    query                                 or "Not specified"),
    ]
    story.append(_two_col_table(brief_rows))

    # ── Section B: Policy Analysis ─────────────────────────────────────────────
    story.append(_p("Policy Eligibility & Benefit Analysis", "section_title"))

    if not results:
        story.append(_p(
            "No matching policies were identified for the provided profile and query. "
            "Consider broadening the industry or geography filters and rerunning the analysis.",
            "body",
        ))
    else:
        seen_ids: set = set()
        unique_results = []
        for r in results:
            pid = r.get("policy_id")
            if pid not in seen_ids:
                seen_ids.add(pid)
                unique_results.append(r)

        for rank, r in enumerate(unique_results, start=1):
            pd_ = r.get("policy_details")   or {}
            id_ = r.get("incentive_details") or {}
            eligibility  = r.get("eligibility_check")      or {}
            benefit_calcs = r.get("benefit_calculations")  or []

            story.append(Spacer(1, 8))
            story.append(_rec_header(rank, r.get("incentive_name", "—")))

            # Eligibility status badge + similarity score
            overall = eligibility.get("overall_eligibility", "PARTIALLY_ELIGIBLE")
            sim_score = r.get("similarity_score", 0.0)
            story.append(_eligibility_badge_row(overall, sim_score))

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
            story.append(Spacer(1, 4))

            # Benefit headline
            headline = id_.get("benefit_headline") or pd_.get("benefit_headline")
            if headline:
                story.append(_p(headline, "benefit_headline"))

            # ── Eligibility Analysis section ───────────────────────────────────
            story.append(_p("Eligibility Analysis", "sub_section"))

            criteria_checks = eligibility.get("criteria_checks") or []
            if criteria_checks:
                story.append(_eligibility_table(criteria_checks))
            else:
                story.append(_p(
                    "Eligibility criteria not available in structured form for this policy. "
                    "Review the policy document for manual assessment.",
                    "body",
                ))

            # Show raw eligibility text from policy_details as reference
            ec = pd_.get("eligibility_criteria") or {}
            raw_elig = ec.get("raw_text")
            if raw_elig:
                story.append(Spacer(1, 3))
                story.append(Paragraph(
                    f"Policy source: \"{raw_elig[:400]}{'...' if len(raw_elig) > 400 else ''}\"",
                    STYLES["source_text"],
                ))

            # Missing profile fields callout
            missing = eligibility.get("missing_profile_fields") or []
            if missing:
                story.append(Spacer(1, 4))
                story.append(_missing_fields_callout(missing))

            # ── Benefit Calculation section ────────────────────────────────────
            story.append(_p("Benefit Quantum", "sub_section"))

            if benefit_calcs:
                story.append(_benefit_table(benefit_calcs))
            else:
                desc = id_.get("description")
                if desc:
                    story.append(_p(desc, "body"))
                story.append(_p(
                    "Benefit calculation not available — benefit details not found in structured form.",
                    "body",
                ))

            # ── Application details ────────────────────────────────────────────
            auth     = id_.get("application_authority")
            process  = id_.get("application_process")
            deadline = id_.get("application_deadline")
            incent_elig = id_.get("incentive_specific_eligibility")

            if any([auth, process, deadline, incent_elig]):
                story.append(_p("Application Details", "sub_section"))
                app_rows = []
                if auth:
                    app_rows.append(("Authority", auth))
                if process:
                    app_rows.append(("Process", process))
                if deadline:
                    app_rows.append(("Deadline", deadline))
                if incent_elig:
                    app_rows.append(("Incentive-specific Eligibility", incent_elig))
                story.append(_two_col_table(app_rows))

            # Divider between recommendations
            if rank < len(unique_results):
                story.append(Spacer(1, 10))
                story.append(HRFlowable(
                    width=TEXT_W, thickness=0.5, color=colors.HexColor("#CCCCCC")
                ))

    doc.build(story)


# ── Profile display helpers ────────────────────────────────────────────────────

def _fmt_investment(profile: dict) -> str:
    val = profile.get("investment_amount_lakhs")
    if val is None:
        return "Not provided"
    val = float(val)
    if val >= 100:
        return f"₹{val / 100:.2f} crores"
    return f"₹{val:.2f} lakhs"


def _fmt_employees(profile: dict) -> str:
    val = profile.get("employee_count")
    return str(val) if val is not None else "Not provided"


def _fmt_loan(profile: dict) -> str:
    val = profile.get("loan_amount_lakhs")
    if val is None:
        return "Not provided"
    val = float(val)
    if val >= 100:
        return f"₹{val / 100:.2f} crores"
    return f"₹{val:.2f} lakhs"
