import os
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from shared.schema import CompanyResearch
from dev2_delivery.database import get_db
from dev2_delivery.gmail_sender import send_email
from dev2_delivery.ppt_generator import generate_pptx
from dev2_delivery.email_generator import generate_email
from dev2_delivery.models.job import Job, JobStatus
from dev2_delivery.services import job_store

router = APIRouter()

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.post("/generate", response_class=HTMLResponse)
async def generate(request: Request, company_json: CompanyResearch, db: Session = Depends(get_db)):
    job_id = uuid.uuid4().hex[:12]

    pptx_path = generate_pptx(company_json)
    email_draft = generate_email(company_json)

    new_job = Job(
    job_id=job_id,
    company_data=company_json,   # ← was company_name=
    pptx_path=pptx_path,
    email_draft=email_draft,
)
    job_store.create_job(db, new_job)

    return RedirectResponse(url=f"/review/{job_id}", status_code=303)


@router.get("/review/{job_id}", response_class=HTMLResponse)
async def review(request: Request, job_id: str, db: Session = Depends(get_db)):
    job = job_store.get_job(db, job_id)
    if not job:
        return HTMLResponse("<h2>Job not found</h2>", status_code=404)
    return templates.TemplateResponse(request,
        "approval.html",
        {"job": job, "flash": None},
    )


@router.post("/approve/{job_id}", response_class=HTMLResponse)
async def approve(
    request: Request,
    job_id: str,
    recipient_email: str = Form(...),
    subject: str = Form(...),
    body: str = Form(...),
    db: Session = Depends(get_db),
):
    job = job_store.get_job(db, job_id)
    if not job:
        return HTMLResponse("<h2>Job not found</h2>", status_code=404)

    # Persist any edits made on the approval screen before sending
    updated_draft = job.email_draft.model_copy(update={
        "recipient_email": recipient_email,
        "subject": subject,
        "body": body,
    })
    job_store.update_job(db, job_id,
        email_draft=updated_draft,
        status=JobStatus.approved,
        approved_at=datetime.now(timezone.utc),
    )

    if job.from_pipeline:
        from graph.workflow import resume_pipeline
        result = resume_pipeline(
            thread_id=job_id,
            decision={"status": "approved", "email_draft": updated_draft.model_dump(mode="json")},
        )
        if result.get("email_sent"):
            job_store.update_job(db, job_id, status=JobStatus.sent)
            flash = {"type": "success", "message": f"Email sent! Message ID: {result.get('message_id')}"}
        else:
            job_store.update_job(db, job_id, status=JobStatus.failed)
            flash = {"type": "error", "message": f"Send failed: {result.get('error')}"}
    else:
        result = send_email(
            to=recipient_email,
            subject=subject,
            body_html=body,
            attachment_path=job.pptx_path,
        )

        if result["success"]:
            job_store.update_job(db, job_id, status=JobStatus.sent)
            flash = {"type": "success", "message": f"Email sent! Message ID: {result['message_id']}"}
        else:
            job_store.update_job(db, job_id, status=JobStatus.failed)
            flash = {"type": "error", "message": f"Send failed: {result['error']}"}

    return templates.TemplateResponse(request,
        "approval.html",
        {"job": job_store.get_job(db, job_id), "flash": flash},
    )


@router.post("/reject/{job_id}", response_class=HTMLResponse)
async def reject(request: Request, job_id: str, db: Session = Depends(get_db)):
    job = job_store.get_job(db, job_id)
    if not job:
        return HTMLResponse("<h2>Job not found</h2>", status_code=404)

    job_store.update_job(db, job_id, status=JobStatus.rejected)

    # NOTE: unlike approve(), reject() does NOT call resume_pipeline() here.
    # Resolving the LangGraph interrupt would finalize that thread (route to
    # END), leaving nothing to resume if the user edits and re-approves
    # afterward — resume_pipeline() on an already-finished thread silently
    # fails (empty state, JOBSTATUS.failed with no real error). Leaving the
    # interrupt unresolved keeps the door open for a genuine re-approve.
    flash = {"type": "error", "message": "Job rejected. You can edit and re-approve above."}
    return templates.TemplateResponse(request,
        "approval.html",
        {"job": job_store.get_job(db, job_id), "flash": flash},
    )


@router.get("/download/{job_id}")
async def download(job_id: str, db: Session = Depends(get_db)):
    job = job_store.get_job(db, job_id)
    if not job:
        return HTMLResponse("<h2>Job not found</h2>", status_code=404)
    if not job.pptx_path or not os.path.exists(job.pptx_path):
        return HTMLResponse("<h2>File not found</h2>", status_code=404)
    return FileResponse(
        job.pptx_path,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename=f"{job.company_data.company_name.replace(' ', '_')}.pptx",
    )


@router.get("/history", response_class=HTMLResponse)
async def history(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(request,
        "history.html",
        {"jobs": job_store.list_jobs(db)},
    )