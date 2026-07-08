"""
graph/dev2_nodes.py

Dev2's four LangGraph nodes. Each node receives the full PipelineState,
does exactly one job, and returns only the keys it modifies.

Node order in the graph:
    ... -> ppt_node -> email_node -> approval_node -> send_node
"""
import uuid

from langgraph.types import interrupt

from dev2_delivery.email_generator import generate_email
from dev2_delivery.gmail_sender import send_email
from dev2_delivery.models.email import EmailDraft
from dev2_delivery.ppt_generator import generate_pptx
from shared.schema import CompanyResearch


def _deserialize_research(state: dict) -> CompanyResearch:
    raw = state["company_research"]
    if isinstance(raw, CompanyResearch):
        return raw
    return CompanyResearch.model_validate(raw)


def _deserialize_draft(data) -> EmailDraft | None:
    if not data:
        return None
    if isinstance(data, EmailDraft):
        return data
    return EmailDraft(**data)


def _serialize(obj) -> dict | None:
    if obj is None:
        return None
    return obj.model_dump(mode="json") if hasattr(obj, "model_dump") else dict(obj)


def ppt_node(state: dict) -> dict:
    try:
        data = _deserialize_research(state)
        pptx_path = generate_pptx(data)
        job_id = state.get("job_id") or uuid.uuid4().hex[:12]
        return {"pptx_path": pptx_path, "job_id": job_id}
    except Exception as e:
        return {"error": f"ppt_node failed: {e}"}


def email_node(state: dict) -> dict:
    try:
        data = _deserialize_research(state)
        draft = generate_email(data)
        return {"email_draft": _serialize(draft)}
    except Exception as e:
        return {"error": f"email_node failed: {e}"}


def approval_node(state: dict) -> dict:
    decision = interrupt({
        "job_id": state.get("job_id"),
        "pptx_path": state.get("pptx_path"),
        "email_draft": state.get("email_draft"),
    })
    status = decision.get("status", "rejected")
    edited = decision.get("email_draft")
    return {
        "approval_status": status,
        "edited_email": edited or state.get("email_draft"),
    }


def send_node(state: dict) -> dict:
    if state.get("approval_status") != "approved":
        return {"email_sent": False, "message_id": None}
    try:
        draft_data = state.get("edited_email") or state.get("email_draft")
        draft = _deserialize_draft(draft_data)
        if not draft:
            return {"error": "send_node: no email draft found", "email_sent": False}
        result = send_email(
            to=draft.recipient_email,
            subject=draft.subject,
            body_html=draft.body,
            attachment_path=state.get("pptx_path"),
        )
        return {
            "email_sent": result.get("success", False),
            "message_id": result.get("message_id"),
            "error": None if result.get("success") else result.get("error"),
        }
    except Exception as e:
        return {"error": f"send_node failed: {e}", "email_sent": False}
