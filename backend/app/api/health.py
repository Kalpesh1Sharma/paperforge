"""Backward-compatible import surface for the health router."""

from app.api.routes.health import router

__all__ = ["router"]
