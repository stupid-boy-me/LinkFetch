"""Shared media models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class FormatOption:
    format_id: str
    label: str
    height: Optional[int] = None
    ext: str = ""
    vcodec: str = ""
    acodec: str = ""
    filesize: Optional[int] = None
    is_audio_only: bool = False
    direct_url: Optional[str] = None


@dataclass
class MediaInfo:
    url: str
    title: str
    extractor: str
    thumbnail: str = ""
    duration: Optional[float] = None
    is_playlist: bool = False
    playlist_count: int = 0
    entries: list[dict[str, Any]] = field(default_factory=list)
    formats: list[FormatOption] = field(default_factory=list)
    subtitles: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
