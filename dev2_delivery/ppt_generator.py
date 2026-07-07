"""
ppt_generator.py — Dev2 service
Consumes a CompanyResearch object and produces a filled .pptx file.

Slides:
  1. Title
  2. About
  3. Products & Services
  4. News
  5. LLM Analysis
  6. Recommended Services
  7. Company Snapshot       ← NEW (skipped if company_snapshot is empty)
  8. Spotlight Use Case     ← NEW (skipped if spotlight_use_case is None)
"""
import os
import uuid
from pptx import Presentation
from pptx.util import Pt
from shared.schema import CompanyResearch

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "templates", "template.pptx")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "outputs")


# ── text helpers ──────────────────────────────────────────────────────────────

def _replace_text(shape, replacements: dict):
    """Replace {{key}} placeholders in a shape's text frame."""
    if not shape.has_text_frame:
        return
    for para in shape.text_frame.paragraphs:
        for run in para.runs:
            for key, val in replacements.items():
                if key in run.text:
                    run.text = run.text.replace(key, val)


def _format_list(items: list, prefix="• ") -> str:
    if not items:
        return "None found"
    return "\n".join(f"{prefix}{item}" for item in items)


def _format_news(news_items: list) -> str:
    if not news_items:
        return "No recent news found"
    lines = []
    for item in news_items:
        date = f" ({item.date})" if item.date else ""
        lines.append(f"• {item.title}{date}\n  {item.summary}")
    return "\n\n".join(lines)


def _format_recommended_services(services: list) -> str:
    if not services:
        return "No recommendations generated"
    lines = []
    for svc in services:
        priority_label = f"[{svc.priority.value.upper()}]"
        lines.append(f"• {svc.service} {priority_label}\n  {svc.reason}")
    return "\n\n".join(lines)


# ── new slide helpers ─────────────────────────────────────────────────────────

def _set_text_frame(tf, lines: list[tuple]):
    """
    Populate a text frame from a list of (text, bold, font_size) tuples.
    Clears existing content first.
    """
    tf.clear()
    first = True
    for text, bold, size in lines:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        run = p.add_run()
        run.text = text
        run.font.bold = bold
        if size:
            run.font.size = Pt(size)


def _add_snapshot_slide(prs: Presentation, stats: list) -> None:
    """
    Slide 7 — Company at a Glance.
    Adds one stat block per SnapshotStat: bold label + lighter caption.
    Skipped entirely if stats list is empty.
    """
    if not stats:
        return

    layout = prs.slide_layouts[1]          # Title and Content
    slide = prs.slides.add_slide(layout)

    if slide.shapes.title:
        slide.shapes.title.text = "Company at a Glance"

    content_ph = slide.placeholders[1]
    tf = content_ph.text_frame
    tf.word_wrap = True

    lines = []
    for stat in stats:
        lines.append((stat.label, True, 20))
        lines.append((f"  {stat.caption}", False, 12))
        lines.append(("", False, 10))          # spacer

    _set_text_frame(tf, lines)


def _add_spotlight_slide(prs: Presentation, use_case) -> None:
    """
    Slide 8 — Spotlight Use Case (flagship AI pipeline).
    Skipped entirely if use_case is None.
    """
    if not use_case:
        return

    layout = prs.slide_layouts[1]
    slide = prs.slides.add_slide(layout)

    if slide.shapes.title:
        slide.shapes.title.text = use_case.title

    content_ph = slide.placeholders[1]
    tf = content_ph.text_frame
    tf.word_wrap = True

    lines = []

    # Pipeline stages
    for stage in use_case.stages:
        lines.append((f"→ {stage.stage}", True, 14))
        lines.append((f"   {stage.description}", False, 12))
        lines.append(("", False, 10))

    # Outcomes
    if use_case.estimated_outcomes:
        lines.append(("Expected Outcomes", True, 14))
        for outcome in use_case.estimated_outcomes:
            lines.append((f"• {outcome}", False, 12))

    _set_text_frame(tf, lines)


# ── main entry point ──────────────────────────────────────────────────────────

def generate_pptx(data: CompanyResearch) -> str:
    """
    Generate a filled .pptx from a CompanyResearch object.
    Returns the absolute path to the saved file.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    prs = Presentation(TEMPLATE_PATH)

    # Replacements for the 6 existing template slides
    replacements = {
        "{{company_name}}": data.company_name,
        "{{website_url}}": data.website_url,
        "{{about_summary}}": data.about.summary if data.about else "N/A",
        "{{industry}}": data.about.industry if data.about else "N/A",
        "{{founded}}": data.about.founded or "N/A",
        "{{size}}": data.about.size or "N/A",
        "{{products}}": _format_list(data.products),
        "{{services}}": _format_list(data.services),
        "{{news}}": _format_news(data.news),
        "{{pain_points}}": _format_list(data.llm_analysis.pain_points),
        "{{growth_signals}}": _format_list(data.llm_analysis.growth_signals),
        "{{tech_stack}}": _format_list(data.llm_analysis.tech_stack_hints),
        "{{recommended_services}}": _format_recommended_services(data.recommended_services),
    }

    for slide in prs.slides:
        for shape in slide.shapes:
            _replace_text(shape, replacements)

    # Append new slides (each helper skips itself if data is empty/None)
    _add_snapshot_slide(prs, data.company_snapshot)
    _add_spotlight_slide(prs, data.spotlight_use_case)

    filename = f"{data.company_name.replace(' ', '_')}_{uuid.uuid4().hex[:8]}.pptx"
    output_path = os.path.join(OUTPUT_DIR, filename)
    prs.save(output_path)
    return output_path