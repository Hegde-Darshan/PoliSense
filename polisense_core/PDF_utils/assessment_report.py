"""
Full Eligibility & Benefit Quantum Report PDF generator.

Consumes a Tier2Report object and produces a structured PDF with:
  Cover page — summary stats and total potential benefit range
  Section A — Eligible policies (full detail pages)
  Section B — Partially eligible policies (full detail pages + gap callouts)
  Section C — Not eligible policies (compact gap table)

Public API:
    generate_assessment_pdf(query_name, report, submission_time, output_path)
"""

from __future__ import annotations

import datetime
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from polisense_core.AssessmentPipeline.models import FullPolicyResult, Tier2Report

# ── Colours ────────────────────────────────────────────────────────────────────
NAVY        = colors.HexColor("#1B3A6B")
NAVY_LIGHT  = colors.HexColor("#2B5598")
ROW_ALT     = colors.HexColor("#EBF2FB")
ROW_WHITE   = colors.white
LABEL_BG    = colors.HexColor("#F0F4FA")

MET_BG          = colors.HexColor("#E8F5E9")
MET_TEXT        = colors.HexColor("#1B5E20")
NOT_MET_BG      = colors.HexColor("#FFEBEE")
NOT_MET_TEXT    = colors.HexColor("#B71C1C")
UNCERTAIN_BG    = colors.HexColor("#FFF8E1")
UNCERTAIN_TEXT  = colors.HexColor("#E65100")

BADGE_ELIGIBLE  = colors.HexColor("#2E7D32")
BADGE_PARTIAL   = colors.HexColor("#E65100")
BADGE_NOT       = colors.HexColor("#C62828")

CALLOUT_INFO_BG     = colors.HexColor("#E3F2FD")
CALLOUT_INFO_BORDER = colors.HexColor("#1565C0")
CALLOUT_WARN_BG     = colors.HexColor("#FFF3E0")
CALLOUT_WARN_BORDER = colors.HexColor("#E65100")

# ── Page geometry ──────────────────────────────────────────────────────────────
PAGE_W, PAGE_H = A4
MARGIN  = 1.5 * cm
TEXT_W  = PAGE_W - 2 * MARGIN

# ── Styles ─────────────────────────────────────────────────────────────────────
STYLES = {
    "doc_title":      ParagraphStyle("doc_title", fontName="Helvetica-Bold", fontSize=18,
                                     textColor=NAVY, spaceAfter=4),
    "doc_subtitle":   ParagraphStyle("doc_subtitle", fontName="Helvetica", fontSize=9,
                                     textColor=colors.grey, spaceAfter=0),
    "section_banner": ParagraphStyle("section_banner", fontName="Helvetica-Bold", fontSize=12,
                                     textColor=colors.white),
    "section_title":  ParagraphStyle("section_title", fontName="Helvetica-Bold", fontSize=11,
                                     textColor=NAVY, spaceBefore=14, spaceAfter=4),
    "sub_section":    ParagraphStyle("sub_section", fontName="Helvetica-Bold", fontSize=9,
                                     textColor=NAVY_LIGHT, spaceBefore=8, spaceAfter=3),
    "policy_header":  ParagraphStyle("policy_header", fontName="Helvetica-Bold", fontSize=10,
                                     textColor=colors.white, leading=14),
    "badge":          ParagraphStyle("badge", fontName="Helvetica-Bold", fontSize=8,
                                     textColor=colors.white),
    "label":          ParagraphStyle("label", fontName="Helvetica-Bold", fontSize=8.5,
                                     textColor=NAVY),
    "value":          ParagraphStyle("value", fontName="Helvetica", fontSize=8.5,
                                     textColor=colors.black, leading=12),
    "benefit_headline": ParagraphStyle("benefit_headline", fontName="Helvetica-Bold",
                                       fontSize=9, textColor=NAVY_LIGHT,
                                       spaceBefore=4, spaceAfter=4, leading=13),
    "body":           ParagraphStyle("body", fontName="Helvetica", fontSize=8.5,
                                     textColor=colors.HexColor("#333333"), leading=13,
                                     spaceAfter=4),
    "source_text":    ParagraphStyle("source_text", fontName="Helvetica-Oblique", fontSize=7.5,
                                     textColor=colors.HexColor("#666666"), leading=11),
    "met_text":       ParagraphStyle("met_text", fontName="Helvetica", fontSize=8.5,
                                     textColor=MET_TEXT, leading=12),
    "not_met_text":   ParagraphStyle("not_met_text", fontName="Helvetica", fontSize=8.5,
                                     textColor=NOT_MET_TEXT, leading=12),
    "uncertain_text": ParagraphStyle("uncertain_text", fontName="Helvetica", fontSize=8.5,
                                     textColor=UNCERTAIN_TEXT, leading=12),
    "footer":         ParagraphStyle("footer", fontName="Helvetica", fontSize=7,
                                     textColor=colors.grey),
    "stat_num":       ParagraphStyle("stat_num", fontName="Helvetica-Bold", fontSize=22,
                                     textColor=NAVY, spaceAfter=0),
    "stat_label":     ParagraphStyle("stat_label", fontName="Helvetica", fontSize=8,
                                     textColor=colors.grey),
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


def _fmt(lakhs: float) -> str:
    if lakhs >= 100:
        return f"₹{lakhs / 100:.2f} crores"
    return f"₹{lakhs:.2f} lakhs"


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


def _policy_header(rank: int, policy_name: str, parent: str) -> Table:
    label = f"#{rank}  {policy_name}"
    sub = parent if parent and parent != policy_name else ""
    content = [_p(label, "policy_header")]
    if sub:
        sub_style = ParagraphStyle("ps", fontName="Helvetica", fontSize=8,
                                   textColor=colors.HexColor("#B0C4DE"), leading=11)
        content.append(Paragraph(sub, sub_style))
    return Table(
        [content],
        colWidths=[TEXT_W],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), NAVY),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ]),
    )


def _eligibility_badge_row(overall: str, score: float) -> Table:
    label_map = {
        "ELIGIBLE":           ("ELIGIBLE",          BADGE_ELIGIBLE),
        "PARTIALLY_ELIGIBLE": ("PARTIALLY ELIGIBLE", BADGE_PARTIAL),
        "NOT_ELIGIBLE":       ("NOT ELIGIBLE",        BADGE_NOT),
    }
    label, fill = label_map.get(overall, ("UNKNOWN", colors.grey))
    badge = Table(
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
    score_cell = _p(f"Match Score: {score:.0%}", "label")
    return Table(
        [[badge, score_cell]],
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
    STATUS_CONFIG = {
        "MET":       ("✓ MET",       MET_BG,       MET_TEXT,       "met_text"),
        "NOT_MET":   ("✗ NOT MET",   NOT_MET_BG,   NOT_MET_TEXT,   "not_met_text"),
        "UNCERTAIN": ("? UNCERTAIN", UNCERTAIN_BG, UNCERTAIN_TEXT, "uncertain_text"),
    }
    hdr_p = lambda t: Paragraph(t, ParagraphStyle("hdr", fontName="Helvetica-Bold",
                                                   fontSize=8, textColor=colors.white))
    data = [[hdr_p("Status"), hdr_p("Criterion"), hdr_p("Company Assessment")]]
    row_colors = []

    for i, check in enumerate(criteria_checks):
        if hasattr(check, "model_dump"):
            check = check.model_dump()
        status = check.get("status", "UNCERTAIN")
        lbl, bg, _, text_style = STATUS_CONFIG.get(status, STATUS_CONFIG["UNCERTAIN"])

        criterion = check.get("criteria_description") or check.get("field") or ""
        parts = []
        if check.get("company_value"):
            parts.append(f"Provided: {check['company_value']}")
        if check.get("gap"):
            parts.append(f"Gap: {check['gap']}")
        if check.get("recommendation"):
            parts.append(f"Action: {check['recommendation']}")
        assessment = "\n".join(parts) if parts else "—"

        data.append([_p(lbl, text_style), _p(criterion, text_style), _p(assessment, text_style)])
        row_colors.append(("BACKGROUND", (0, i + 1), (-1, i + 1), bg))

    style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#BBBBBB")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ] + row_colors)
    return Table(data, colWidths=[TEXT_W * 0.18, TEXT_W * 0.35, TEXT_W * 0.47],
                 style=style, hAlign="LEFT")


def _benefit_slab_table(benefit_slabs: list) -> Table:
    hdr_p = lambda t: Paragraph(t, ParagraphStyle("hdr", fontName="Helvetica-Bold",
                                                   fontSize=8, textColor=colors.white))
    data = [[hdr_p("Benefit Slab"), hdr_p("Quantum"), hdr_p("Calculation & Conditions")]]
    CONF_COLOR = {"HIGH": MET_TEXT, "MEDIUM": UNCERTAIN_TEXT, "LOW": NOT_MET_TEXT}

    for slab in benefit_slabs:
        if hasattr(slab, "model_dump"):
            slab = slab.model_dump()

        desc = slab.get("slab_description") or "—"
        source = slab.get("source_text") or ""
        desc_cell = [_p(desc, "body")]
        if source:
            desc_cell.append(Paragraph(
                f'"{source[:200]}{"..." if len(source) > 200 else ""}"',
                STYLES["source_text"],
            ))

        not_applicable = slab.get("not_applicable_reason")
        missing = slab.get("missing_field")
        if slab.get("is_applicable") is False:
            quantum = "Not applicable"
            basis = not_applicable or "—"
        elif slab.get("is_applicable") is None:
            quantum = "UNCERTAIN"
            basis = f"Missing: {missing}" if missing else (slab.get("calculation_steps") or "—")
        else:
            effective = slab.get("effective_amount_lakhs")
            calc = slab.get("calculated_amount_lakhs")
            if effective is not None:
                quantum = _fmt(effective)
            elif calc is not None:
                quantum = _fmt(calc)
            else:
                quantum = slab.get("value_raw") or "—"
            parts = []
            if slab.get("calculation_steps"):
                parts.append(slab["calculation_steps"])
            if slab.get("cap_applied"):
                parts.append("Cap applied")
            basis = "\n".join(parts) if parts else "—"

        conf = slab.get("confidence", "LOW")
        conf_color = CONF_COLOR.get(conf, colors.grey)
        q_style = ParagraphStyle("qs", fontName="Helvetica-Bold", fontSize=8.5,
                                 textColor=conf_color, leading=12)
        data.append([desc_cell, Paragraph(quantum, q_style), _p(basis, "body")])

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
    return Table(data, colWidths=[TEXT_W * 0.33, TEXT_W * 0.22, TEXT_W * 0.45],
                 style=style, hAlign="LEFT")


def _missing_fields_callout(missing_fields: list, warn: bool = False) -> Table:
    bg = CALLOUT_WARN_BG if warn else CALLOUT_INFO_BG
    border = CALLOUT_WARN_BORDER if warn else CALLOUT_INFO_BORDER
    color = colors.HexColor("#BF360C") if warn else colors.HexColor("#0D47A1")
    hdr_style = ParagraphStyle("ih", fontName="Helvetica-Bold", fontSize=8.5,
                                textColor=color, spaceAfter=2)
    body_style = ParagraphStyle("ib", fontName="Helvetica", fontSize=8.5,
                                textColor=color, leading=13)
    fields_text = ", ".join(f.replace("_", " ").title() for f in missing_fields)
    content = [
        Paragraph("Improve this assessment:", hdr_style),
        Paragraph(
            f"Providing these details would resolve UNCERTAIN checks: {fields_text}",
            body_style,
        ),
    ]
    return Table(
        [content],
        colWidths=[TEXT_W - 2],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), bg),
            ("BOX", (0, 0), (-1, -1), 1, border),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]),
    )


def _section_banner(title: str, fill_color) -> Table:
    return Table(
        [[_p(f"  {title}  ", "section_banner")]],
        colWidths=[TEXT_W],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), fill_color),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
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
        canvas.drawRightString(PAGE_W - MARGIN - 4, PAGE_H - MARGIN - 0.45 * cm,
                               f"{business_name}  |  {generated}  |  Page {doc.page}")
        canvas.setFont("Helvetica", 6.5)
        canvas.setFillColor(colors.grey)
        canvas.drawString(
            MARGIN, 0.7 * cm,
            "Generated by PoliSense. Benefit calculations are estimates based on submitted profile data. "
            "Final amounts are determined by the sanctioning authority.",
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


# ── Per-policy page builder ────────────────────────────────────────────────────

def _policy_page(story: list, rank: int, result: FullPolicyResult, show_benefit: bool = True):
    """Append flowables for one policy result to story."""
    policy_data = result.eligibility
    if hasattr(policy_data, "model_dump"):
        elig_dict = policy_data.model_dump()
    else:
        elig_dict = dict(policy_data)

    story.append(Spacer(1, 6))
    story.append(_policy_header(rank, result.policy_name, result.parent_policy_name))
    story.append(_eligibility_badge_row(
        elig_dict.get("overall_eligibility", "PARTIALLY_ELIGIBLE"),
        result.similarity_score,
    ))

    # Policy metadata
    story.append(_two_col_table([
        ("Policy Framework", result.parent_policy_name or "—"),
        ("Scheme",           result.policy_name or "—"),
        ("Match Score",      f"{result.similarity_score:.0%}"),
    ]))
    story.append(Spacer(1, 4))

    # Eligibility analysis
    story.append(_p("Eligibility Analysis", "sub_section"))
    criteria = elig_dict.get("criteria_checks") or []
    if criteria:
        story.append(_eligibility_table(criteria))
    else:
        story.append(_p("No structured eligibility criteria available for this policy.", "body"))

    missing = elig_dict.get("missing_profile_fields") or []
    if missing:
        story.append(Spacer(1, 4))
        story.append(_missing_fields_callout(missing))

    if not show_benefit:
        # NOT_ELIGIBLE — show gap summary instead of benefit calc
        all_gaps = [
            c.get("gap") or c.get("recommendation") or ""
            for c in criteria
            if c.get("status") == "NOT_MET" and (c.get("gap") or c.get("recommendation"))
        ]
        if all_gaps:
            story.append(Spacer(1, 4))
            gap_lines = "\n".join(f"• {g}" for g in all_gaps[:4])
            story.append(_p(f"Key eligibility gaps:\n{gap_lines}", "body"))
        return

    # Applicable incentives with benefit calculations
    if result.applicable_incentives:
        story.append(_p("Applicable Incentives & Benefit Quantum", "sub_section"))
        for incentive in result.applicable_incentives:
            if hasattr(incentive, "model_dump"):
                inc_dict = incentive.model_dump()
            else:
                inc_dict = dict(incentive)

            inc_name = inc_dict.get("incentive_name") or ""
            inc_type = inc_dict.get("incentive_type") or ""
            headline = inc_dict.get("benefit_headline") or ""
            app_status = inc_dict.get("applicability") or ""

            # Incentive sub-header
            status_color = BADGE_ELIGIBLE if app_status == "APPLICABLE" else UNCERTAIN_TEXT
            inc_header_style = ParagraphStyle(
                "ih", fontName="Helvetica-Bold", fontSize=9,
                textColor=status_color, spaceBefore=6, spaceAfter=2,
            )
            status_label = "✓" if app_status == "APPLICABLE" else "?"
            story.append(Paragraph(f"{status_label} {inc_name} ({inc_type})", inc_header_style))
            if headline:
                story.append(_p(headline, "benefit_headline"))

            slabs = inc_dict.get("benefit_slabs") or []
            if slabs:
                story.append(_benefit_slab_table(slabs))

            total = inc_dict.get("total_potential_benefit_lakhs")
            if total is not None:
                total_style = ParagraphStyle(
                    "tot", fontName="Helvetica-Bold", fontSize=9,
                    textColor=BADGE_ELIGIBLE, spaceAfter=4,
                )
                story.append(Paragraph(f"Total potential benefit: {_fmt(total)}", total_style))

            # Application details
            auth     = inc_dict.get("application_authority")
            process  = inc_dict.get("application_process")
            deadline = inc_dict.get("application_deadline")
            if any([auth, process, deadline]):
                app_rows = []
                if auth:     app_rows.append(("Authority", auth))
                if process:  app_rows.append(("Process", process))
                if deadline: app_rows.append(("Deadline", deadline))
                story.append(Spacer(1, 2))
                story.append(_two_col_table(app_rows))

    # Policy-level total
    pol_total = result.total_potential_benefit_lakhs
    if pol_total is not None:
        total_box = Table(
            [[_p(f"Total potential benefit across all incentives: {_fmt(pol_total)}",
                 "benefit_headline")]],
            colWidths=[TEXT_W],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), MET_BG),
                ("BOX", (0, 0), (-1, -1), 1, BADGE_ELIGIBLE),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ]),
        )
        story.append(Spacer(1, 4))
        story.append(total_box)

    # Not-applicable incentives summary (brief)
    if result.not_applicable_incentives:
        names = ", ".join(
            (i.incentive_name if hasattr(i, "incentive_name") else i.get("incentive_name") or "")
            for i in result.not_applicable_incentives
        )
        story.append(Spacer(1, 4))
        story.append(_p(f"Not applicable incentives: {names}", "source_text"))


# ── Cover page ─────────────────────────────────────────────────────────────────

def _cover_page(
    story: list,
    report: Tier2Report,
    generated: str,
    submission_time: Optional[datetime.datetime],
):
    business = report.business_name
    story.append(_p("Full Eligibility & Benefit Report", "doc_title"))
    subtitle = f"Prepared for: {business}  ·  Report generated: {generated}"
    if submission_time:
        subtitle += f"  ·  Form submitted: {submission_time.strftime('%d %b %Y, %H:%M')}"
    story.append(_p(subtitle, "doc_subtitle"))
    story.append(HRFlowable(width=TEXT_W, thickness=1.5, color=NAVY, spaceAfter=12))

    # Client profile brief
    story.append(_p("Client Profile", "section_title"))
    p = report.profile
    brief_rows = [
        ("Business Name",      p.get("business_name") or "—"),
        ("Industry",           _join(p.get("industry"))),
        ("Location",           p.get("geography") or "—"),
        ("Business Size",      p.get("business_size") or "—"),
        ("Enterprise Type",    p.get("enterprise_type") or "—"),
        ("P&M Investment",     _fmt(p["investment_pm_lakhs"]) if p.get("investment_pm_lakhs") else "—"),
        ("Total Project Cost", _fmt(p["total_project_cost_lakhs"]) if p.get("total_project_cost_lakhs") else "—"),
        ("Entity Type",        p.get("entity_type") or "—"),
        ("Udyam Number",       p.get("udyam_number") or "—"),
        ("Special Attributes", _join(p.get("special_attributes"))),
    ]
    story.append(_two_col_table(brief_rows))
    story.append(Spacer(1, 12))

    # Summary stats
    story.append(_p("Analysis Summary", "section_title"))
    total = report.total_potential_benefit_lakhs
    stats = [
        (str(report.total_eligible_count),         "Eligible Policies"),
        (str(len(report.partially_eligible_policies)), "Partially Eligible"),
        (str(len(report.not_eligible_policies)),    "Not Eligible"),
        (
            _fmt(total) if total is not None else "—",
            "Total Potential Benefit (Eligible + Partial)",
        ),
    ]
    stat_data = [[
        Table(
            [[_p(num, "stat_num")], [_p(lbl, "stat_label")]],
            colWidths=[TEXT_W / 4 - 4],
            style=TableStyle([
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]),
        )
        for num, lbl in stats
    ]]
    story.append(Table(
        stat_data,
        colWidths=[TEXT_W / 4] * 4,
        style=TableStyle([
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#CCCCCC")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#EEEEEE")),
            ("BACKGROUND", (0, 0), (-1, -1), LABEL_BG),
        ]),
    ))

    # Missing fields callout (global)
    if report.global_missing_fields:
        story.append(Spacer(1, 10))
        story.append(_missing_fields_callout(report.global_missing_fields, warn=True))

    story.append(PageBreak())


# ── Public API ─────────────────────────────────────────────────────────────────

def generate_assessment_pdf(
    query_name: str,
    report: Tier2Report,
    submission_time: Optional[datetime.datetime],
    output_path: str,
) -> None:
    """
    Generate the full eligibility & benefit quantum PDF.

    Args:
        query_name:      Human-readable label for this query (used in logs).
        report:          Tier2Report from assessment_pipeline.run_assessment().
        submission_time: Original Zoho form submission datetime (or None).
        output_path:     Path for the output .pdf file.
    """
    generated = datetime.datetime.now().strftime("%d %b %Y, %H:%M")
    business  = report.business_name
    doc = _make_doc(output_path, business, generated)
    story = []

    # Cover page
    _cover_page(story, report, generated, submission_time)

    # ── Section A — Eligible ───────────────────────────────────────────────────
    if report.eligible_policies:
        story.append(_section_banner(
            f"Section A — Eligible Policies  ({len(report.eligible_policies)} found)",
            BADGE_ELIGIBLE,
        ))
        for rank, result in enumerate(report.eligible_policies, start=1):
            _policy_page(story, rank, result, show_benefit=True)
            if rank < len(report.eligible_policies):
                story.append(HRFlowable(width=TEXT_W, thickness=0.5,
                                        color=colors.HexColor("#CCCCCC"), spaceAfter=4))

    # ── Section B — Partially Eligible ────────────────────────────────────────
    if report.partially_eligible_policies:
        story.append(Spacer(1, 10))
        story.append(_section_banner(
            f"Section B — Partially Eligible Policies  ({len(report.partially_eligible_policies)} found)",
            BADGE_PARTIAL,
        ))
        for rank, result in enumerate(report.partially_eligible_policies, start=1):
            _policy_page(story, rank, result, show_benefit=True)
            if rank < len(report.partially_eligible_policies):
                story.append(HRFlowable(width=TEXT_W, thickness=0.5,
                                        color=colors.HexColor("#CCCCCC"), spaceAfter=4))

    # ── Section C — Not Eligible ───────────────────────────────────────────────
    if report.not_eligible_policies:
        story.append(Spacer(1, 10))
        story.append(_section_banner(
            f"Section C — Not Eligible Policies  ({len(report.not_eligible_policies)} found)",
            BADGE_NOT,
        ))
        story.append(Spacer(1, 6))
        story.append(_p(
            "The following policies did not meet one or more hard eligibility criteria. "
            "The gap column explains what would need to change for eligibility.",
            "body",
        ))
        story.append(Spacer(1, 6))

        # Compact gap table for all NOT_ELIGIBLE
        hdr_p = lambda t: Paragraph(t, ParagraphStyle("hdr", fontName="Helvetica-Bold",
                                                       fontSize=8, textColor=colors.white))
        ne_data = [[hdr_p("Policy / Scheme"), hdr_p("Key Eligibility Gap"), hdr_p("What Would Need to Change")]]
        for result in report.not_eligible_policies:
            if hasattr(result.eligibility, "model_dump"):
                elig_dict = result.eligibility.model_dump()
            else:
                elig_dict = dict(result.eligibility)
            criteria = elig_dict.get("criteria_checks") or []
            not_met = [c for c in criteria if c.get("status") == "NOT_MET"]
            gap = not_met[0].get("gap") or not_met[0].get("criteria_description") if not_met else "—"
            rec = not_met[0].get("recommendation") or "—" if not_met else "—"
            ne_data.append([
                _p(result.policy_name or result.parent_policy_name or "—", "body"),
                _p(gap, "not_met_text"),
                _p(rec, "body"),
            ])

        ne_style = TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), BADGE_NOT),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CCCCCC")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [ROW_WHITE, NOT_MET_BG]),
        ])
        story.append(Table(
            ne_data,
            colWidths=[TEXT_W * 0.30, TEXT_W * 0.35, TEXT_W * 0.35],
            style=ne_style,
            hAlign="LEFT",
        ))

    doc.build(story)
