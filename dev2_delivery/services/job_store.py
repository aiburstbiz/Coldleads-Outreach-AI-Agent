"""
DB-backed job store.
Same public API as the old in-memory store, but every function now takes
`db: Session` as its first argument.

Callers (routes/approval.py) must:
  1. Inject `db: Session = Depends(get_db)` into the route function.
  2. Pass `db` as the first argument to every job_store call.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session
from shared.schema import CompanyResearch
from dev2_delivery.db_models import JobDB
from dev2_delivery.models.email import EmailDraft
from dev2_delivery.models.job import Job, JobStatus


# ── private helpers ───────────────────────────────────────────────────────────

def _row_to_job(row: JobDB) -> Job:
    email_draft = EmailDraft(**row.email_draft) if row.email_draft else None
    company_data = CompanyResearch.model_validate(row.company_data) if row.company_data else None
    return Job(
        job_id=row.job_id,
        status=JobStatus(row.status),
        company_data=company_data,
        pptx_path=row.pptx_path,
        email_draft=email_draft,
        created_at=row.created_at,
        approved_at=row.approved_at,
    )

def _email_to_dict(draft: Optional[EmailDraft]) -> Optional[dict]:
    """Serialize EmailDraft → plain dict for JSON column storage."""
    if draft is None:
        return None
    # Supports both Pydantic v1 (.dict()) and v2 (.model_dump())
    return draft.model_dump() if hasattr(draft, "model_dump") else draft.dict()


# ── public API ────────────────────────────────────────────────────────────────

def create_job(db: Session, job: Job) -> Job:
    company_dict = job.company_data.model_dump(mode="json")
    row = JobDB(
        job_id=job.job_id,
        company_name=job.company_data.company_name,
        company_data=company_dict,
        status=job.status.value,
        pptx_path=job.pptx_path,
        email_draft=_email_to_dict(job.email_draft),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _row_to_job(row)

def get_job(db: Session, job_id: str) -> Optional[Job]:
    row = db.query(JobDB).filter(JobDB.job_id == job_id).first()
    return _row_to_job(row) if row else None


def update_job(db: Session, job_id: str, **kwargs) -> Optional[Job]:
    """
    Update arbitrary fields on a job.

    Usage:
        job_store.update_job(db, job_id, status=JobStatus.approved, approved_at=datetime.now(UTC))
        job_store.update_job(db, job_id, email_draft=edited_draft)
    """
    row = db.query(JobDB).filter(JobDB.job_id == job_id).first()
    if not row:
        return None

    for key, value in kwargs.items():
        if key == "status" and isinstance(value, JobStatus):
            row.status = value.value
        elif key == "email_draft" and isinstance(value, EmailDraft):
            row.email_draft = _email_to_dict(value)
        else:
            setattr(row, key, value)

    db.commit()
    db.refresh(row)
    return _row_to_job(row)


def list_jobs(db: Session) -> list[Job]:
    rows = db.query(JobDB).order_by(JobDB.created_at.desc()).all()
    return [_row_to_job(r) for r in rows]
