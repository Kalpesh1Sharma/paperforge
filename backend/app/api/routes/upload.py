"""Compatibility export for the existing versioned temporary-upload router."""

from app.api.upload import router

__all__ = ["router"]
