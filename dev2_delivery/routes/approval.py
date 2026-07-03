import os
import uuid
from datetime import datetime
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from shared.schema import CompanyResearch
from dev2_delivery.ppt_generator import generate_pptx
from dev2_delivery.email_generator import generate_email
from dev2_delivery.services.job_store import (
    create_job, get_job, update_status, list_jobs
)

router = APIRouter()

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.post("/generate", response_class=HTMLResponse)
async def generate(request: Request, company_json: CompanyResearch):
    """
    Accept a CompanyResearch object, generate PPT + email, create a job.
    Returns the job_id so the caller can visit /review/{job_id}.
    """
    job_id = uuid.uuid4().hex[:12]

    pptx_path = generate_pptx(company_json)
    email_draft = generate_email(company_json)

    create_job(
        job_id=job_id,
        company_name=company_json.company_name,
        pptx_path=pptx_path,
        email_draft=email_draft.model_dump(),
    )

    return RedirectResponse(url=f"/review/{job_id}", status_code=303)


@router.get("/review/{job_id}", response_class=HTMLResponse)
async def review(request: Request, job_id: str):
    job = get_job(job_id)
    if not job:
        return HTMLResponse("<h2>Job not found</h2>", status_code=404)
    return templates.TemplateResponse(request,
        "approval.html",
        {"job": job, "flash": None}
    )


@router.post("/approve/{job_id}", response_class=HTMLResponse)
async def approve(
    request: Request,
    job_id: str,
    recipient_email: str = Form(...),
    subject: str = Form(...),
    body: str = Form(...),
):
    job = get_job(job_id)
    if not job:
        return HTMLResponse("<h2>Job not found</h2>", status_code=404)

    # Update the email draft with any edits made on the approval screen
    job["email_draft"]["recipient_email"] = recipient_email
    job["email_draft"]["subject"] = subject
    job["email_draft"]["body"] = body

    update_status(job_id, "approved", approved_at=datetime.utcnow().isoformat())

    # Gmail send will be wired in here on Day 5
    # For now just mark approved and show confirmation
    flash = {"type": "success", "message": "Approved! Email will be sent shortly."}
    return templates.TemplateResponse(request,
        "approval.html",
        {"job": get_job(job_id), "flash": flash}
    )


@router.post("/reject/{job_id}", response_class=HTMLResponse)
async def reject(request: Request, job_id: str):
    job = get_job(job_id)
    if not job:
        return HTMLResponse("<h2>Job not found</h2>", status_code=404)

    update_status(job_id, "rejected")
    flash = {"type": "error", "message": "Job rejected. You can edit and re-approve above."}
    return templates.TemplateResponse(request,
        "approval.html",
        {"job": get_job(job_id), "flash": flash}
    )


@router.get("/download/{job_id}")
async def download(job_id: str):
    job = get_job(job_id)
    if not job:
        return HTMLResponse("<h2>Job not found</h2>", status_code=404)
    pptx_path = job["pptx_path"]
    if not os.path.exists(pptx_path):
        return HTMLResponse("<h2>File not found</h2>", status_code=404)
    return FileResponse(
        pptx_path,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename=f"{job['company_name'].replace(' ', '_')}.pptx"
    )


@router.get("/history", response_class=HTMLResponse)
async def history(request: Request):
    return templates.TemplateResponse(request,
        "history.html",
        {"jobs": list_jobs()}
    )