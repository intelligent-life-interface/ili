"""Pydantic-Schemas für Board/Column/Card — Schnittstellen-Definition des Dashboard-APIs.

extra='allow': historische Board-JSONs haben zusätzliche Felder (z.B. desc UND description),
die dürfen beim Roundtrip Load→Save nicht verloren gehen.
"""
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class Card(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: Optional[str] = None
    title: Optional[str] = None
    desc: Optional[str] = None          # Legacy-Feld, parallel zu description
    description: Optional[str] = None
    label: Optional[str] = None
    priority: Optional[str] = None      # Ideen-Karten: hoch|mittel|niedrig (= label-Farbe)
    effort: Optional[str] = None        # Ideen-Karten: hoch|mittel|niedrig (Aufwand)
    category: Optional[str] = None
    status: Optional[str] = None
    rejected: Optional[bool] = None
    rejection_reason: Optional[str] = None
    rejected_at: Optional[str] = None


class Column(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: Optional[str] = None
    title: Optional[str] = None
    cards: List[Card] = Field(default_factory=list)


class Board(BaseModel):
    model_config = ConfigDict(extra="allow")

    columns: List[Column] = Field(default_factory=list)
