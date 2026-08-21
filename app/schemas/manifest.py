"""Pydantic-Schemas für manifest.json — zentrale Board-Metadaten."""
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ManifestEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    description: Optional[str] = None
    description_updated: Optional[str] = None
    category: Optional[str] = None
    color: Optional[str] = None
    icon: Optional[str] = None
    type: Optional[str] = None
    cover_photo: Optional[str] = None
    parent_ids: List[str] = Field(default_factory=list)
    child_order: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)


class Manifest(BaseModel):
    model_config = ConfigDict(extra="allow")

    boards: List[ManifestEntry] = Field(default_factory=list)
