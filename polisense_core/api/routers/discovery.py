import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from fastapi.responses import FileResponse

from polisense_core.api.models import DiscoveryResponse, JobPollResponse, JobStatus
from polisense_core.api.store import JobState, jobs, jobs_lock
from polisense_core.discovery_pipeline import process_batch
from polisense_core.retrieval_pipeline import RETRIEVALS_DIR
from polisense_core.utils.zoho_transforms import TIMESTAMP_COL, transform_rows_to_batch

logger = logging.getLogger(__name__)

router = APIRouter()

_API_SECRET = os.getenv("DISCOVERY_API_SECRET", "")
PDF_STORE_DIR = Path(os.getenv("PDF_STORE_DIR", str(RETRIEVALS_DIR / "api")))


def _check_secret(provided: str) -> None:
    if not _API_SECRET:
        raise HTTPException(status_code=500, detail="DISCOVERY_API_SECRET not configured on server")
    if provided != _API_SECRET:
        raise HTTPException(status_code=401, detail="Invalid secret")


async def _run_discovery(job_id: str, zoho_data: dict) -> None:
    async with jobs_lock:
        jobs[job_id].status = JobStatus.processing

    try:
        job_dir = PDF_STORE_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        await asyncio.to_thread(process_batch, zoho_data, 20, job_dir)

        pdfs = list(job_dir.glob("*.pdf"))
        pdf_path = str(pdfs[0]) if pdfs else None
        if pdf_path is None:
            raise RuntimeError("Pipeline completed but no PDF was written")

        async with jobs_lock:
            jobs[job_id].status = JobStatus.done
            jobs[job_id].pdf_path = pdf_path

        logger.info("Job %s done — PDF: %s", job_id, pdf_path)

    except Exception as exc:
        logger.exception("Job %s failed: %s", job_id, exc)
        async with jobs_lock:
            jobs[job_id].status = JobStatus.failed
            jobs[job_id].error = str(exc)


@router.post("/discovery", response_model=DiscoveryResponse, status_code=202)
async def create_discovery_job(
    request: Request,
    background_tasks: BackgroundTasks,
    x_zoho_secret: str = Header(..., description="Shared secret configured as DISCOVERY_API_SECRET"),
) -> DiscoveryResponse:
    """Accept a raw Zoho form submission and start the discovery pipeline asynchronously.

    Poll GET /discovery/{job_id} to check status. Download the PDF via
    GET /discovery/{job_id}/pdf once status is 'done'.
    """
    _check_secret(x_zoho_secret)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Request body must be valid JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Request body must be a JSON object")

    # Inject current time as 'Submitted' if the field is absent so the PDF gets a proper timestamp.
    if TIMESTAMP_COL not in body:
        body[TIMESTAMP_COL] = datetime.now(timezone.utc).strftime("%d/%m/%Y %I:%M:%S %p")

    zoho_data = transform_rows_to_batch([body])
    if not zoho_data:
        raise HTTPException(
            status_code=422,
            detail="Could not extract a valid submission — check that 'Legal Name of the Enterprise' is present",
        )

    job_id = str(uuid4())
    async with jobs_lock:
        jobs[job_id] = JobState()

    background_tasks.add_task(_run_discovery, job_id, zoho_data)
    logger.info("Discovery job %s queued", job_id)

    return DiscoveryResponse(job_id=job_id, status=JobStatus.queued)


@router.get("/discovery/{job_id}", response_model=JobPollResponse)
async def get_job_status(
    job_id: str,
    x_zoho_secret: str = Header(..., description="Shared secret configured as DISCOVERY_API_SECRET"),
) -> JobPollResponse:
    """Poll the status of a discovery job."""
    _check_secret(x_zoho_secret)

    async with jobs_lock:
        state = jobs.get(job_id)

    if state is None:
        raise HTTPException(status_code=404, detail="Job not found")

    pdf_url = f"/discovery/{job_id}/pdf" if state.status == JobStatus.done else None
    return JobPollResponse(
        job_id=job_id,
        status=state.status,
        error=state.error,
        pdf_url=pdf_url,
    )


@router.get("/discovery/{job_id}/pdf")
async def download_pdf(
    job_id: str,
    x_zoho_secret: str = Header(..., description="Shared secret configured as DISCOVERY_API_SECRET"),
) -> FileResponse:
    """Download the generated discovery PDF for a completed job."""
    _check_secret(x_zoho_secret)

    async with jobs_lock:
        state = jobs.get(job_id)

    if state is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if state.status == JobStatus.failed:
        raise HTTPException(status_code=500, detail=f"Job failed: {state.error}")
    if state.status != JobStatus.done:
        raise HTTPException(status_code=409, detail=f"Job not ready — current status: {state.status.value}")

    pdf_path = Path(state.pdf_path)
    if not pdf_path.exists():
        raise HTTPException(status_code=410, detail="PDF file no longer available on disk")

    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=pdf_path.name,
    )
