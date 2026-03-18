from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from .models import MediaStatus, MediaType

class WebhookPayload(BaseModel):
    torrent_id: str
    torrent_name: str
    torrent_dir: str

class FileMoveSchema(BaseModel):
    id: int
    download_id: int
    src_path: str
    dst_path: str

    class Config:
        from_attributes = True

class DownloadSchema(BaseModel):
    id: int
    torrent_name: str
    original_path: str
    status: MediaStatus
    media_type: MediaType
    system_media_type: Optional[str]
    type_scores: Optional[str]
    detected_title: Optional[str]
    detected_year: Optional[str]
    metadata_source: Optional[str]
    source_id: Optional[str]
    created_at: datetime
    file_moves: List[FileMoveSchema]

    class Config:
        from_attributes = True
