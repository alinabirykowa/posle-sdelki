"""Vercel's FastAPI entrypoint; frontend files are served by its CDN."""

from backend.app import app

__all__ = ["app"]
