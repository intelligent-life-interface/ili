"""API-Router: Manager-Frontend (manager.html) — Status, Strategie, Tagesberichte.

Read-only Proxy auf ~/manager/{state.md,STRATEGIE.md,berichte/} via manager_service.
"""
import logging

from fastapi import APIRouter, Query

from app.services import manager_service

log = logging.getLogger("dashboard.api.manager")
router = APIRouter(tags=["manager"])


@router.get("/api/manager/status")
def get_status():
    """Aktueller Zustand aus state.md (jeder collect.sh-Lauf überschreibt sie)."""
    return manager_service.get_status()


@router.get("/api/manager/strategie")
def get_strategie():
    """STRATEGIE.md — Dokument des Betreibers, read-only."""
    return manager_service.get_strategie()


@router.get("/api/manager/reports")
def get_reports(limit: int = Query(default=60, ge=1, le=365)):
    """Verlauf der Tagesberichte, neueste zuerst."""
    return {"reports": manager_service.get_reports(limit)}
