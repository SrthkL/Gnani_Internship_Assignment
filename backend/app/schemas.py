from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UploadResponse(BaseModel):
    """Identify an upload and report its processing state."""

    id: str
    status: str


class UploadDetail(UploadResponse):
    """Return recording information and its transcript."""

    # Allow reading fields from a SQLAlchemy Upload object.
    model_config = ConfigDict(from_attributes=True)

    filename: str
    transcript: str | None = None
    created_at: datetime
    progress: int = 0