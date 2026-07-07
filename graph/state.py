"""
graph/state.py — Shared pipeline state

Single source of truth for the LangGraph state schema.
Both Dev1 and Dev2 nodes read from and write to this state.

Field ownership:
    Dev1  → website_url, company_research, search_attempts,
             scrape_attempts, analyze_attempts, quality_notes,
             current_step, scraped_site
    Dev2  → job_id, pptx_path, email_draft, approval_status,
             edited_email, email_sent, message_id
    Both  → error
"""

from typing import Literal, Optional
from typing_extensions import TypedDict


class PipelineState(TypedDict):

    # ── input ──────────────────────────────────────────────────────────────
    company_name: str

    # ── Dev1 outputs ───────────────────────────────────────────────────────
    website_url: Optional[str]
    scraped_site: Optional[str]            # actual URL that was scraped
    company_research: Optional[dict]       # serialized CompanyResearch

    # Dev1 evaluator / retry tracking
    search_attempts: Optional[int]
    scrape_attempts: Optional[int]
    analyze_attempts: Optional[int]
    quality_notes: Optional[list]          # notes from Dev1's evaluator nodes
    current_step: Optional[str]            # e.g. "search" | "scrape" | "analyze"

    # ── Dev2 outputs ───────────────────────────────────────────────────────
    job_id: Optional[str]
    pptx_path: Optional[str]
    email_draft: Optional[dict]            # serialized EmailDraft
    approval_status: Optional[Literal["approved", "rejected"]]
    edited_email: Optional[dict]           # draft after human edits in approval UI
    email_sent: Optional[bool]
    message_id: Optional[str]

    # ── shared error tracking ──────────────────────────────────────────────
    error: Optional[str]
