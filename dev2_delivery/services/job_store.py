"""
In-memory job store — replaced by PostgreSQL in Day 6.
Keyed by job_id. Stores job status, email draft, and pptx path.
"""
from typing import Dict, Any

_store: Dict[str, Any] = {}


def create_job(job_id: str, company_name: str, pptx_path: str, email_draft: dict):
    _store[job_id] = {
        "job_id": job_id,
        "company_name": company_name,
        "status": "pending",
        "pptx_path": pptx_path,
        "email_draft": email_draft,
        "approved_at": None,
    }


def get_job(job_id: str) -> dict | None:
    return _store.get(job_id)


def update_status(job_id: str, status: str, **kwargs):
    if job_id in _store:
        _store[job_id]["status"] = status
        _store[job_id].update(kwargs)


def list_jobs() -> list:
    return list(_store.values())