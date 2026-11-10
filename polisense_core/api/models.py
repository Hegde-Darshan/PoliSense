from enum import Enum
from pydantic import BaseModel


class JobStatus(str, Enum):
    queued = "queued"
    processing = "processing"
    done = "done"
    failed = "failed"


class DiscoveryResponse(BaseModel):
    job_id: str
    status: JobStatus


class JobPollResponse(BaseModel):
    job_id: str
    status: JobStatus
    error: str | None = None
    pdf_url: str | None = None
