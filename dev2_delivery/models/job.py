from pydantic import BaseModel
from datetime import datetime
from enum import Enum
from typing import Optional
from shared.schema import CompanyResearch


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
    company_data: CompanyResearch
    created_at: datetime
    approved_at: Optional[datetime] = None