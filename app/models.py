from datetime import datetime
import enum
from typing import List, Optional
from sqlalchemy import String, Integer, DateTime, ForeignKey, Enum, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

class MediaStatus(str, enum.Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    MANUAL_REQUIRED = "MANUAL_REQUIRED"
    ERROR = "ERROR"
    REVERTED = "REVERTED"

class MediaType(str, enum.Enum):
    MOVIE = "MOVIE"
    SERIES = "SERIES"
    GAME = "GAME"
    SOFTWARE = "SOFTWARE"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"

class Download(Base):
    __tablename__ = "downloads"

    id: Mapped[int] = mapped_column(primary_key=True)
    torrent_name: Mapped[str] = mapped_column(String(255))
    original_path: Mapped[str] = mapped_column(String(1024))
    status: Mapped[MediaStatus] = mapped_column(String(50), default=MediaStatus.PENDING)
    media_type: Mapped[MediaType] = mapped_column(String(50), default=MediaType.UNKNOWN)
    detected_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    detected_year: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    metadata_source: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    source_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    file_moves: Mapped[List["FileMove"]] = relationship(back_populates="download", cascade="all, delete-orphan")

class FileMove(Base):
    __tablename__ = "file_moves"

    id: Mapped[int] = mapped_column(primary_key=True)
    download_id: Mapped[int] = mapped_column(ForeignKey("downloads.id"))
    src_path: Mapped[str] = mapped_column(String(1024))
    dst_path: Mapped[str] = mapped_column(String(1024))
    
    download: Mapped["Download"] = relationship(back_populates="file_moves")

class Setting(Base):
    __tablename__ = "settings"
    
    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
