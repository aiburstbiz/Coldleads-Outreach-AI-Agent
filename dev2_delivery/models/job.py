from pydantic import BaseModel, Field, computed_field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from shared.schema import CompanyResearch
from dev2_delivery.models.email import EmailDraft

class JobStatus(str, Enum):
    pending = "pending"
    generated = "generated"
    approved = "approved"
    rejected = "rejected"
    sent = "sent"
    failed = "failed"

class Job(BaseModel):
    job_id: str
    status: JobStatus = JobStatus.pending
    company_data: Optional[CompanyResearch] = None
    pptx_path: Optional[str] = None
    email_draft: Optional[EmailDraft] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    approved_at: Optional[datetime] = None
    from_pipeline: bool = False

    @computed_field
    @property
    def company_name(self) -> str:
        """
        Convenience accessor so templates and other code can reference
        job.company_name directly. Falls back to job_id for failed jobs
        that never got real company_data (e.g. a ppt_node failure).
        """
        if self.company_data:
            return self.company_data.company_name
        return self.job_id

