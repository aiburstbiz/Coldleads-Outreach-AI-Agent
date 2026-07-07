"""
Pipeline step logger.

Usage (inside any route or service that already has a db session):

    from dev2_delivery.services.logger import log_step

    log_step(db, job_id="abc123", step="ppt_gen", status="ok", message="Saved to outputs/")
    log_step(db, job_id="abc123", step="email_gen", status="error", message=str(e))
"""

import uuid
from typing import Literal

from sqlalchemy.orm import Session

from dev2_delivery.db_models import PipelineLogDB

StepStatus = Literal["ok", "error", "skip"]


def log_step(
    db: Session,
    job_id: str,
    step: str,
    status: StepStatus,
    message: str | None = None,
) -> None:
    entry = PipelineLogDB(
        log_id=str(uuid.uuid4()),
        job_id=job_id,
        step=step,
        status=status,
        message=message,
    )
    db.add(entry)
    db.commit()


def get_logs(db: Session, job_id: str) -> list[dict]:
    """Return all log entries for a job, oldest first."""
    rows = (
        db.query(PipelineLogDB)
        .filter(PipelineLogDB.job_id == job_id)
        .order_by(PipelineLogDB.created_at.asc())
        .all()
    )
    return [
        {
            "log_id": r.log_id,
            "step": r.step,
            "status": r.status,
            "message": r.message,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
