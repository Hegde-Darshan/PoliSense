"""In-memory job store for async discovery requests."""
import asyncio
from dataclasses import dataclass, field

from polisense_core.api.models import JobStatus


@dataclass
class JobState:
    status: JobStatus = JobStatus.queued
    pdf_path: str | None = None
    error: str | None = None


jobs: dict[str, JobState] = {}
jobs_lock: asyncio.Lock = asyncio.Lock()
