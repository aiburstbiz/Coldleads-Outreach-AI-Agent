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

_cached_signature_html = None
_signature_fetch_attempted = False


def _get_gmail_signature() -> str | None:
    """
    Fetch the account's saved Gmail signature (primary send-as alias),
    so generated emails match what the reviewer would see if they sent
    the email manually. Cached per-process since it rarely changes.

    Returns None if unavailable for any reason (auth error, no signature
    configured, network issue) — this must never raise, since a Gmail
    Settings API hiccup should not block email draft generation. Callers
    fall back to the plain-text sign-off in that case.
    """
    global _cached_signature_html, _signature_fetch_attempted
    if _signature_fetch_attempted:
        return _cached_signature_html

    _signature_fetch_attempted = True
    try:
        from dev2_delivery.services.gmail_auth import get_gmail_service
        service = get_gmail_service()
        aliases = service.users().settings().sendAs().list(userId="me").execute()
        for alias in aliases.get("sendAs", []):
            if alias.get("isPrimary"):
                sig = alias.get("signature")
                _cached_signature_html = sig if sig else None
                break
    except Exception:
        _cached_signature_html = None

    return _cached_signature_html

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
        "signature_html": _get_gmail_signature(),
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