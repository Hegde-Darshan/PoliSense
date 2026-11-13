import datetime
import math
import os

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
from reportlab.platypus.flowables import Flowable
from reportlab.graphics.shapes import Drawing, Wedge, Circle, String, Rect
from reportlab.graphics import renderPDF
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Register Arial for Unicode support (₹ symbol is not in standard PDF fonts)
try:
    pdfmetrics.registerFont(TTFont("ArialT", r"C:\Windows\Fonts\arial.ttf"))
    pdfmetrics.registerFont(TTFont("ArialT-Bold", r"C:\Windows\Fonts\arialbd.ttf"))
    _UNICODE_FONT = "ArialT"
    _UNICODE_FONT_BOLD = "ArialT-Bold"
except Exception:
    _UNICODE_FONT = "Helvetica"
    _UNICODE_FONT_BOLD = "Helvetica-Bold"

# ── Colours ────────────────────────────────────────────────────────────────────
NAVY         = colors.HexColor("#1B3A6B")
NAVY_LIGHT   = colors.HexColor("#2B5598")
TEAL         = colors.HexColor("#00897B")
TEAL_LIGHT   = colors.HexColor("#E0F2F1")
AMBER        = colors.HexColor("#E65100")
AMBER_LIGHT  = colors.HexColor("#FFF3E0")
AMBER_BORDER = colors.HexColor("#F57C00")
DARK_BG      = colors.HexColor("#1A2B4A")
ORANGE_VAL   = colors.HexColor("#E65100")
GRAY_BG      = colors.HexColor("#F5F5F5")
GRAY_BAR     = colors.HexColor("#E0E0E0")
GRAY_LOCKED  = colors.HexColor("#9E9E9E")
SCORE_HIGH   = colors.HexColor("#00897B")   # teal
SCORE_MED    = colors.HexColor("#1976D2")   # blue
SCORE_LOW    = colors.HexColor("#E65100")   # orange

# ── Page geometry ──────────────────────────────────────────────────────────────
PAGE_W, PAGE_H = A4
MARGIN = 1.5 * cm
TEXT_W = PAGE_W - 2 * MARGIN

# ── Styles ─────────────────────────────────────────────────────────────────────
STYLES = {
    "brand": ParagraphStyle(
        "brand",
        fontName="Helvetica-Bold",
        fontSize=18,
        textColor=NAVY,
        spaceAfter=0,
        leading=20,
    ),
    "tagline": ParagraphStyle(
        "tagline",
        fontName="Helvetica",
        fontSize=8,
        textColor=colors.HexColor("#666666"),
        spaceAfter=0,
        leading=10,
    ),
    "badge": ParagraphStyle(
        "badge",
        fontName="Helvetica-Bold",
        fontSize=7.5,
        textColor=TEAL,
        spaceAfter=2,
        leading=10,
        spaceBefore=4,
    ),
    "report_title": ParagraphStyle(
        "report_title",
        fontName="Helvetica-Bold",
        fontSize=22,
        textColor=NAVY,
        spaceAfter=4,
        leading=26,
    ),
    "report_title_teal": ParagraphStyle(
        "report_title_teal",
        fontName="Helvetica-Bold",
        fontSize=22,
        textColor=TEAL,
        spaceAfter=4,
        spaceBefore=0,
        leading=26,
    ),
    "scheme_headline": ParagraphStyle(
        "scheme_headline",
        fontName="Helvetica-Bold",
        fontSize=18,
        textColor=SCORE_MED,
        spaceAfter=4,
        spaceBefore=4,
        leading=22,
    ),
    "info_label": ParagraphStyle(
        "info_label",
        fontName="Helvetica-Bold",
        fontSize=7,
        textColor=colors.HexColor("#888888"),
        spaceAfter=2,
        leading=9,
    ),
    "info_value": ParagraphStyle(
        "info_value",
        fontName="Helvetica-Bold",
        fontSize=9,
        textColor=ORANGE_VAL,
        spaceAfter=0,
        leading=11,
    ),
    "intro_salutation": ParagraphStyle(
        "intro_salutation",
        fontName="Helvetica-Bold",
        fontSize=10,
        textColor=NAVY,
        spaceAfter=3,
        spaceBefore=4,
        leading=13,
    ),
    "intro_body": ParagraphStyle(
        "intro_body",
        fontName="Helvetica",
        fontSize=9.5,
        textColor=colors.HexColor("#333333"),
        spaceAfter=6,
        leading=14,
    ),
    "score_caption": ParagraphStyle(
        "score_caption",
        fontName="Helvetica-Bold",
        fontSize=7,
        textColor=colors.HexColor("#888888"),
        spaceAfter=0,
        leading=9,
    ),
    "cat_name": ParagraphStyle(
        "cat_name",
        fontName="Helvetica-Bold",
        fontSize=8.5,
        textColor=colors.HexColor("#222222"),
        leading=11,
    ),
    "cat_match_high": ParagraphStyle(
        "cat_match_high",
        fontName="Helvetica-Bold",
        fontSize=8.5,
        textColor=SCORE_HIGH,
        leading=11,
    ),
    "cat_match_med": ParagraphStyle(
        "cat_match_med",
        fontName="Helvetica-Bold",
        fontSize=8.5,
        textColor=SCORE_MED,
        leading=11,
    ),
    "cat_match_low": ParagraphStyle(
        "cat_match_low",
        fontName="Helvetica-Bold",
        fontSize=8.5,
        textColor=SCORE_LOW,
        leading=11,
    ),
    "cat_count": ParagraphStyle(
        "cat_count",
        fontName="Helvetica-Bold",
        fontSize=9,
        textColor=NAVY,
        leading=11,
    ),
    "gap_header": ParagraphStyle(
        "gap_header",
        fontName="Helvetica-Bold",
        fontSize=10,
        textColor=NAVY,
        spaceAfter=4,
        leading=13,
    ),
    "gap_body": ParagraphStyle(
        "gap_body",
        fontName="Helvetica",
        fontSize=9,
        textColor=colors.HexColor("#333333"),
        spaceAfter=6,
        leading=13,
    ),
    "top_match_name": ParagraphStyle(
        "top_match_name",
        fontName="Helvetica-Bold",
        fontSize=10,
        textColor=NAVY,
        spaceAfter=2,
        leading=13,
    ),
    "top_match_headline": ParagraphStyle(
        "top_match_headline",
        fontName="Helvetica",
        fontSize=9,
        textColor=colors.HexColor("#555555"),
        spaceAfter=0,
        leading=12,
    ),
    "gap_label": ParagraphStyle(
        "gap_label",
        fontName="Helvetica-Bold",
        fontSize=8.5,
        textColor=AMBER,
        leading=11,
    ),
    "locked_badge": ParagraphStyle(
        "locked_badge",
        fontName="Helvetica-Bold",
        fontSize=7.5,
        textColor=GRAY_LOCKED,
        leading=10,
    ),
    "unlock_label": ParagraphStyle(
        "unlock_label",
        fontName="Helvetica-Bold",
        fontSize=8,
        textColor=TEAL,
        spaceBefore=4,
        spaceAfter=3,
        leading=10,
    ),
    "unlock_item": ParagraphStyle(
        "unlock_item",
        fontName="Helvetica",
        fontSize=9,
        textColor=colors.HexColor("#333333"),
        leading=13,
    ),
    "cta_heading": ParagraphStyle(
        "cta_heading",
        fontName="Helvetica-Bold",
        fontSize=12,
        textColor=colors.white,
        spaceAfter=4,
        leading=15,
    ),
    "cta_body": ParagraphStyle(
        "cta_body",
        fontName="Helvetica",
        fontSize=9,
        textColor=colors.HexColor("#CCCCCC"),
        spaceAfter=4,
        leading=13,
    ),
    "cta_link": ParagraphStyle(
        "cta_link",
        fontName="Helvetica-Bold",
        fontSize=9,
        textColor=TEAL,
        leading=13,
    ),
    "cta_price": ParagraphStyle(
        "cta_price",
        fontName=_UNICODE_FONT_BOLD,
        fontSize=22,
        textColor=colors.white,
        spaceAfter=2,
        leading=25,
    ),
    "cta_price_sub": ParagraphStyle(
        "cta_price_sub",
        fontName="Helvetica-Bold",
        fontSize=7,
        textColor=colors.white,
        leading=9,
    ),
    "disclaimer": ParagraphStyle(
        "disclaimer",
        fontName="Helvetica",
        fontSize=6.5,
        textColor=colors.HexColor("#888888"),
        leading=9,
        spaceBefore=8,
    ),
    "footer_brand": ParagraphStyle(
        "footer_brand",
        fontName="Helvetica-Bold",
        fontSize=7,
        textColor=NAVY,
        leading=10,
    ),
    "footer_contact": ParagraphStyle(
        "footer_contact",
        fontName="Helvetica",
        fontSize=7,
        textColor=TEAL,
        leading=10,
    ),
}


def _p(text: str, style: str) -> Paragraph:
    """Plain-text paragraph — escapes all special chars."""
    safe = str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return Paragraph(safe, STYLES[style])


def _ph(html: str, style: str) -> Paragraph:
    """HTML-markup paragraph — only escapes bare ampersands not part of entities."""
    return Paragraph(str(html or ""), STYLES[style])


# ── Scoring ────────────────────────────────────────────────────────────────────

def _compute_overall_score(results: list, filters: dict) -> int:
    if not results:
        return 0
    top3_scores = [r["similarity_score"] for r in results[:3]]
    avg_sim = sum(top3_scores) / len(top3_scores) * 100

    bonus = 0
    industry = filters.get("industry")
    if industry:
        if any(industry in (r.get("applicable_industries") or []) for r in results):
            bonus += 5
    geography = filters.get("geography")
    if geography:
        if any(
            any(geography.lower() in g.lower() for g in (r.get("applicable_geographies") or []))
            for r in results
        ):
            bonus += 5
    business_size = filters.get("business_size")
    if business_size:
        if any(business_size in (r.get("applicable_business_sizes") or []) for r in results):
            bonus += 5

    return max(0, min(100, int(avg_sim + bonus)))


def _compute_category_breakdown(results: list) -> list[dict]:
    """Group results by category and compute per-category match metrics."""
    groups: dict[str, list] = {}
    parent_groups: dict[str, set] = {}
    for r in results:
        cat = r.get("category") or "Other"
        groups.setdefault(cat, []).append(r["similarity_score"])
        parent_groups.setdefault(cat, set()).add(r.get("parent_policy_name") or "")

    breakdown = []
    for cat, scores in groups.items():
        avg = sum(scores) / len(scores) * 100
        if avg > 68:
            level = "High"
            color = SCORE_HIGH
        elif avg > 52:
            level = "Medium"
            color = SCORE_MED
        else:
            level = "Low"
            color = SCORE_LOW
        breakdown.append({
            "category": cat,
            "count": len(parent_groups[cat]),
            "avg_score": avg,
            "match_level": level,
            "color": color,
            "bar_pct": avg / 100,
        })

    breakdown.sort(key=lambda x: x["avg_score"], reverse=True)
    return breakdown



# ── Custom Flowables ───────────────────────────────────────────────────────────

class DonutChart(Flowable):
    """Circular score gauge rendered as a donut chart."""

    def __init__(self, score: int, size: float = 130):
        super().__init__()
        self.score = score
        self.width = size
        self.height = size

    def draw(self):
        score = max(0, min(100, self.score))
        cx = self.width / 2
        cy = self.height / 2
        r_outer = self.width / 2 - 6
        r_inner = r_outer * 0.60

        if score > 65:
            arc_color = SCORE_HIGH
        elif score > 45:
            arc_color = SCORE_MED
        else:
            arc_color = SCORE_LOW

        d = Drawing(self.width, self.height)

        # Background circle
        d.add(Circle(cx, cy, r_outer, fillColor=GRAY_BAR, strokeColor=None))

        # Score arc: counterclockwise from (90 - sweep) to 90 equals clockwise from top
        if score > 0:
            sweep = 360 * score / 100
            d.add(Wedge(
                cx, cy, r_outer,
                startangledegrees=90 - sweep,
                endangledegrees=90,
                fillColor=arc_color,
                strokeColor=None,
            ))

        # Inner white circle to create donut hole
        d.add(Circle(cx, cy, r_inner, fillColor=colors.white, strokeColor=None))

        # Score number
        d.add(String(
            cx, cy + 6,
            str(score),
            fontSize=26,
            fontName="Helvetica-Bold",
            fillColor=arc_color,
            textAnchor="middle",
        ))
        d.add(String(
            cx, cy - 10,
            "out of 100",
            fontSize=7.5,
            fontName="Helvetica",
            fillColor=colors.HexColor("#888888"),
            textAnchor="middle",
        ))

        renderPDF.draw(d, self.canv, 0, 0)


class ProgressBar(Flowable):
    """Horizontal progress bar."""

    def __init__(self, pct: float, bar_color, width: float = 100, height: float = 8):
        super().__init__()
        self.pct = max(0.0, min(1.0, pct))
        self.bar_color = bar_color
        self.width = width
        self.height = height

    def draw(self):
        c = self.canv
        # Background
        c.setFillColor(GRAY_BAR)
        c.rect(0, 0, self.width, self.height, fill=1, stroke=0)
        # Filled portion
        filled = self.width * self.pct
        if filled > 0:
            c.setFillColor(self.bar_color)
            c.rect(0, 0, filled, self.height, fill=1, stroke=0)


# ── Section builders ───────────────────────────────────────────────────────────

def _header_section(profile: dict, report_id: str, generated: str) -> list:
    business_name = profile.get("business_name") or "—"
    person_name   = profile.get("person_name") or business_name
    flowables = []

    # Brand row: name + logo placeholder
    logo_placeholder = Table(
        [[_p("YOUR LOGO", "info_label")]],
        colWidths=[80],
        style=TableStyle([
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#BBBBBB")),
            ("LINEDASH", (0, 0), (-1, -1), 2, 2),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]),
    )
    brand_cell = [
        _p("GetSchemes", "brand"),
        _p("Subsidies · Schemes · Grants · Incentives", "tagline"),
    ]
    brand_table = Table(
        [[brand_cell, logo_placeholder]],
        colWidths=[TEXT_W - 90, 90],
        style=TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]),
    )
    flowables.append(brand_table)

    # Title
    flowables.append(_p("ELIGIBILITY TEASER REPORT", "report_title_teal"))
    flowables.append(HRFlowable(width=TEXT_W, thickness=1.5, color=NAVY, spaceAfter=8))

    # Client info bar (4 columns)
    col_w = TEXT_W / 4
    info_data = [[
        [_p("PREPARED FOR", "info_label"), _p(person_name, "info_value")],
        [_p("COMPANY", "info_label"), _p(business_name, "info_value")],
        [_p("REPORT DATE", "info_label"), _p(generated, "info_value")],
        [_p("REPORT ID", "info_label"), _p(report_id, "info_value")],
    ]]
    info_table = Table(
        info_data,
        colWidths=[col_w] * 4,
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), GRAY_BG),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#DDDDDD")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DDDDDD")),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]),
    )
    flowables.append(info_table)
    return flowables


def _intro_text(profile: dict, results: list) -> list:
    business_name = profile.get("business_name") or "Your Business"
    person_name   = profile.get("person_name") or business_name

    safe_name = business_name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    scheme_count = len(set(r.get("parent_policy_name") for r in results if r.get("parent_policy_name")))

    items = [
        Spacer(1, 4),
        _p(f"Dear {person_name},", "intro_salutation"),
    ]
    if scheme_count:
        items.append(_ph(f"<b>{scheme_count}</b> schemes matched your profile.", "scheme_headline"))
    items.append(_ph(
        f"We scored <b>{safe_name}</b> against every scheme category relevant to your "
        f"sector, location and investment. Here is how strongly you match.",
        "intro_body",
    ))
    return items


def _score_section(overall_score: int, category_breakdown: list[dict]) -> list:
    donut_size = 110
    donut = DonutChart(overall_score, size=donut_size)
    caption = _p("OVERALL ELIGIBILITY SCORE", "score_caption")

    # Wrap left content in a nested table so reportlab sizes the cell correctly
    left_nested = Table(
        [[donut], [caption]],
        colWidths=[donut_size + 10],
        style=TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]),
    )

    col_header_style = ParagraphStyle(
        "_ch", fontName="Helvetica-Bold", fontSize=7,
        textColor=colors.HexColor("#888888"), leading=9,
    )
    left_col_w = donut_size + 20
    right_col_w = TEXT_W - left_col_w
    # Column widths must sum exactly to right_col_w
    bar_w     = 80
    match_w   = 54
    schemes_w = 52   # needs 42pt text space after 8pt padding for "SCHEMES"
    cat_w     = right_col_w - bar_w - match_w - schemes_w

    cat_rows = [[
        Paragraph("CATEGORY", col_header_style),
        Paragraph("MATCH", col_header_style),
        Paragraph("", col_header_style),
        Paragraph("SCHEMES", col_header_style),
    ]]

    for item in category_breakdown:
        match_style = {
            "High": "cat_match_high",
            "Medium": "cat_match_med",
            "Low": "cat_match_low",
        }.get(item["match_level"], "cat_match_med")

        bar = ProgressBar(item["bar_pct"], item["color"], width=bar_w, height=7)
        cat_rows.append([
            _p(item["category"], "cat_name"),
            bar,
            _p(item["match_level"], match_style),
            _p(f"[{item['count']}]", "cat_count"),
        ])

    cat_table = Table(
        cat_rows,
        colWidths=[cat_w, bar_w, match_w, schemes_w],
        style=TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (1, 0), (1, -1), 6),
            ("RIGHTPADDING", (1, 0), (1, -1), 0),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#DDDDDD")),
        ]),
    )

    outer = Table(
        [[left_nested, cat_table]],
        colWidths=[left_col_w, right_col_w],
        style=TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]),
    )
    return [Spacer(1, 4), outer]


def _top_match_section(results: list) -> list:
    """Show the top-matching scheme name + benefit headline; lock the rest."""
    if not results:
        return []

    top = results[0]
    policy_name = top.get("parent_policy_name") or top.get("policy_name") or "—"
    benefit_headline = (
        (top.get("incentive_details") or {}).get("benefit_headline")
        or (top.get("policy_details") or {}).get("benefit_headline")
        or ""
    )
    hidden_count = len(set(r.get("parent_policy_name") for r in results[1:] if r.get("parent_policy_name")))

    rows = [
        [_p("TOP MATCH PREVIEW", "badge")],
        [_p(policy_name, "top_match_name")],
    ]
    if benefit_headline:
        safe_headline = benefit_headline.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        rows.append([_ph(f"<i>{safe_headline}</i>", "top_match_headline")])
    if hidden_count > 0:
        rows.append([_ph(f"\U0001F512  +{hidden_count} more scheme details locked — unlock in full report", "locked_badge")])

    callout = Table(
        rows,
        colWidths=[TEXT_W - 22],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), TEAL_LIGHT),
            ("BOX", (0, 0), (-1, -1), 1, TEAL),
            ("LINEBEFORE", (0, 0), (0, -1), 4, TEAL),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ("RIGHTPADDING", (0, 0), (-1, -1), 12),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]),
    )
    return [Spacer(1, 6), callout]


def _gap_section() -> list:
    header = _p("What is pulling your score down?", "gap_header")

    # LOCKED gap bars
    locked_rows = []
    for i in range(1, 4):  # always show 3 locked bars
        bar = ProgressBar(0.55, GRAY_BAR, width=TEXT_W * 0.50, height=6)
        locked_badge = Table(
            [[_p("\U0001F512 LOCKED", "locked_badge")]],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), GRAY_BG),
                ("BOX", (0, 0), (-1, -1), 0.5, GRAY_LOCKED),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]),
        )
        locked_rows.append([
            _p(f"Gap {i}", "gap_label"),
            bar,
            locked_badge,
        ])

    gap_inner_w = TEXT_W - 22
    gaps_table = Table(
        locked_rows,
        colWidths=[50, gap_inner_w * 0.55, gap_inner_w * 0.30],
        style=TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]),
    )

    content = [[header], [gaps_table]]
    callout = Table(
        content,
        colWidths=[TEXT_W - 22],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), AMBER_LIGHT),
            ("BOX", (0, 0), (-1, -1), 1.5, AMBER_BORDER),
            ("LINEBEFORE", (0, 0), (0, -1), 4, AMBER_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ("RIGHTPADDING", (0, 0), (-1, -1), 12),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]),
    )
    return [Spacer(1, 6), callout]


def _unlock_section() -> list:
    label = _p("YOUR FULL REPORT UNLOCKS", "unlock_label")
    divider = HRFlowable(width=TEXT_W, thickness=0.5, color=colors.HexColor("#CCCCCC"), spaceAfter=6)

    col_w = TEXT_W / 2
    bullet_rows = [
        ["✓  Which scheme sits in each category",    "✓  The gaps and how to close them"],
        ["✓  Priority order — what to apply for first", "✓  Documents and deadlines per scheme"],
    ]
    bullet_data = [
        [_p(row[0], "unlock_item"), _p(row[1], "unlock_item")]
        for row in bullet_rows
    ]
    bullet_table = Table(
        bullet_data,
        colWidths=[col_w, col_w],
        style=TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]),
    )
    return [Spacer(1, 6), label, divider, bullet_table]


def _cta_section(payment_link: str) -> list:
    left_content = [
        _p("Unlock your complete report", "cta_heading"),
        _p("Scheme names, amounts, documents and deadlines for your business.", "cta_body"),
        _p(f"Pay securely: {payment_link}", "cta_link"),
    ]
    right_content = [
        _p("₹499", "cta_price"),
        _p("ONE-TIME · FULL REPORT", "cta_price_sub"),
    ]

    right_cell = Table(
        [[left_col] for left_col in right_content],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), TEAL),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("LEFTPADDING", (0, 0), (-1, -1), 14),
            ("RIGHTPADDING", (0, 0), (-1, -1), 14),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ]),
        colWidths=[100],
    )

    cta = Table(
        [[left_content, right_cell]],
        colWidths=[TEXT_W - 120, 120],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (0, 0), DARK_BG),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (0, 0), 14),
            ("BOTTOMPADDING", (0, 0), (0, 0), 14),
            ("LEFTPADDING", (0, 0), (0, 0), 14),
            ("RIGHTPADDING", (0, 0), (0, 0), 10),
            ("TOPPADDING", (1, 0), (1, 0), 0),
            ("BOTTOMPADDING", (1, 0), (1, 0), 0),
            ("LEFTPADDING", (1, 0), (1, 0), 0),
            ("RIGHTPADDING", (1, 0), (1, 0), 0),
        ]),
    )
    return [Spacer(1, 8), cta]


def _draw_footer(canvas, margin, text_w):
    """Draw disclaimer + company contact line at the bottom of the page."""
    y_base = margin - 0.1 * cm
    canvas.setFont("Helvetica", 6.5)
    canvas.setFillColor(colors.HexColor("#888888"))
    disclaimer = (
        "*All figures are estimates based on the information you shared in the eligibility form. "
        "Final eligibility and benefit amounts are decided by the sanctioning department. "
        "This teaser is confidential and prepared only for the addressee."
    )
    canvas.drawString(margin, y_base + 1.4 * cm, disclaimer)
    canvas.setStrokeColor(colors.HexColor("#CCCCCC"))
    canvas.setLineWidth(0.5)
    canvas.line(margin, y_base + 1.2 * cm, margin + text_w, y_base + 1.2 * cm)
    canvas.setFont("Helvetica-Bold", 7)
    canvas.setFillColor(NAVY)
    canvas.drawString(margin, y_base + 0.7 * cm, "GetSchemes · a brand of AICALTALLY SOLUTIONS LLP")
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(TEAL)
    canvas.drawRightString(
        margin + text_w, y_base + 0.7 * cm,
        "[www.getschemes.in]  ·  [+91 XXXXX XXXXX]  ·  [hello@getschemes.in]",
    )


# ── Page template ──────────────────────────────────────────────────────────────

def _make_doc(output_path: str, business_name: str, generated: str):
    footer_h = 1.8 * cm  # space reserved for footer at bottom

    def _on_page(canvas, doc):
        canvas.saveState()
        # Top header bar
        canvas.setFillColor(NAVY)
        canvas.rect(MARGIN, PAGE_H - MARGIN - 0.7 * cm, TEXT_W, 0.7 * cm, fill=1, stroke=0)
        canvas.setFont("Helvetica-Bold", 8)
        canvas.setFillColor(colors.white)
        canvas.drawString(MARGIN + 4, PAGE_H - MARGIN - 0.45 * cm, "GetSchemes — Eligibility Teaser Report")
        right_label = f"{business_name}  |  {generated}"
        canvas.drawRightString(PAGE_W - MARGIN - 4, PAGE_H - MARGIN - 0.45 * cm, right_label)
        # Footer
        _draw_footer(canvas, MARGIN, TEXT_W)
        canvas.restoreState()

    frame = Frame(
        MARGIN,
        MARGIN + footer_h,
        TEXT_W,
        PAGE_H - 2 * MARGIN - 0.7 * cm - footer_h,
        id="main",
    )
    template = PageTemplate(id="main", frames=[frame], onPage=_on_page)
    doc = BaseDocTemplate(
        output_path,
        pagesize=A4,
        pageTemplates=[template],
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN + 0.8 * cm,
        bottomMargin=MARGIN + footer_h,
    )
    return doc


# ── Public API ─────────────────────────────────────────────────────────────────

def generate_discovery_pdf(query_name: str, entry: dict, output_path: str) -> None:
    """
    Generate a one-page Discovery scorecard PDF.

    Args:
        query_name:  Human-readable label for this query.
        entry:       Dict with keys:
                       profile (dict) — business_name, industry, geography, business_size
                       query (str)
                       results (list[dict]) — from retrieve_policies(), top_k=20
                       submission_time (datetime | None)
                       filters (dict) — filters applied (industry, geography, business_size)
                       report_id (str | None)
                       payment_link (str | None)
        output_path: Absolute or relative path for the output .pdf file.
    """
    profile   = entry.get("profile", {})
    results   = entry.get("results", [])
    filters   = entry.get("filters", {})

    generated = datetime.datetime.now().strftime("%d/%m/%Y")
    business_name = profile.get("business_name") or query_name

    report_id = entry.get("report_id") or f"GS-TR-{datetime.datetime.now().strftime('%d%m%Y%H%M')}"
    payment_link = entry.get("payment_link") or os.getenv("PAYMENT_LINK", "[Payment Link]")

    overall_score = _compute_overall_score(results, filters)
    category_breakdown = _compute_category_breakdown(results)

    doc = _make_doc(output_path, business_name, generated)
    story = []

    story.extend(_header_section(profile, report_id, generated))
    story.extend(_intro_text(profile, results))
    story.extend(_score_section(overall_score, category_breakdown))
    story.extend(_top_match_section(results))
    story.extend(_gap_section())
    story.extend(_unlock_section())
    story.extend(_cta_section(payment_link))

    doc.build(story)
