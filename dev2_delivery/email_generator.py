"""
email_generator.py — Dev2 service
Consumes a CompanyResearch object and produces an EmailDraft.
Uses Jinja2 for templating. No LLM call needed — the pain points
and recommended services from Dev1's analysis are already personalized.
"""
import os
from jinja2 import Environment, FileSystemLoader
from dotenv import load_dotenv
from shared.schema import CompanyResearch
from dev2_delivery.models.email import EmailDraft

load_dotenv()

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates", "email")

SENDER_NAME = os.getenv("SENDER_NAME", "AIBurst Team")
SENDER_TITLE = os.getenv("SENDER_TITLE", "AI Consulting")
DEFAULT_CONTACT = os.getenv("DEFAULT_CONTACT_NAME", "there")


def generate_email(data: CompanyResearch) -> EmailDraft:
    """
    Generate a personalized outreach email from a CompanyResearch object.
    Returns an EmailDraft with subject, HTML body, and recipient info.
    """
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
    template = env.get_template("outreach.html")

    # Derive recipient email — use contact.email if available
    recipient_email = (
        data.contact.email
        if data.contact and data.contact.email
        else "unknown@unknown.com"
    )

    # Use first word of company name as contact name fallback
    contact_name = DEFAULT_CONTACT

    # Only include high + medium priority recommendations in the email
    filtered_services = [
        svc for svc in data.recommended_services
        if svc.priority.value in ("high", "medium")
    ]

    context = {
        "company_name": data.company_name,
        "contact_name": contact_name,
        "industry": data.about.industry if data.about else "your industry",
        "founded": data.about.founded if data.about else None,
        "pain_points": data.llm_analysis.pain_points if data.llm_analysis else [],
        "recommended_services": filtered_services,
        "sender_name": SENDER_NAME,
        "sender_title": SENDER_TITLE,
    }

    body_html = template.render(**context)

    subject = (
        f"AI Solutions for {data.company_name} "
        f"— Addressing {data.llm_analysis.pain_points[0].lower()}"
        if data.llm_analysis and data.llm_analysis.pain_points
        else f"AI Solutions for {data.company_name}"
    )

    return EmailDraft(
        recipient_email=recipient_email,
        subject=subject,
        body=body_html,
        company_name=data.company_name,
    )