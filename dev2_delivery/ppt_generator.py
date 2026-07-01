"""
ppt_generator.py — Dev2 service
Consumes a CompanyResearch object and produces a filled .pptx file.
"""
import os
import uuid
from pptx import Presentation
from pptx.util import Pt
from shared.schema import CompanyResearch

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "templates", "template.pptx")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "outputs")


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


def generate_pptx(data: CompanyResearch) -> str:
    """
    Generate a filled .pptx from a CompanyResearch object.
    Returns the path to the saved file.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    prs = Presentation(TEMPLATE_PATH)

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

    filename = f"{data.company_name.replace(' ', '_')}_{uuid.uuid4().hex[:8]}.pptx"
    output_path = os.path.join(OUTPUT_DIR, filename)
    prs.save(output_path)
    return output_path