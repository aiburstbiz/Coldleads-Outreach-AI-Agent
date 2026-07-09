from sqlalchemy import Column, String, DateTime, Text, JSON
from sqlalchemy.sql import func
from sqlalchemy import Boolean
from dev2_delivery.database import Base


class JobDB(Base):
    __tablename__ = "jobs"

    job_id = Column(String, primary_key=True, index=True)
    company_name = Column(String, nullable=False)
    company_data = Column(JSON, nullable=True)
    status = Column(String, nullable=False, default="pending")
    pptx_path = Column(String, nullable=True)
    email_draft = Column(JSON, nullable=True)          # stored as JSONB in Postgres
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    from_pipeline = Column(Boolean, nullable=False, default=False)

class PipelineLogDB(Base):
    __tablename__ = "logs"

    log_id = Column(String, primary_key=True, index=True)
    job_id = Column(String, nullable=False, index=True)
    step = Column(String, nullable=False)
    status = Column(String, nullable=False)            # "ok" | "error" | "skip"
    message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
