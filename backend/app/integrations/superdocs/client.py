"""Small synchronous client for the official SuperDocs review API."""

from __future__ import annotations

from typing import Any

import httpx

from app.integrations.superdocs.exceptions import (
    SuperDocsNotConfiguredError,
    SuperDocsProtocolError,
    SuperDocsUnavailableError,
)


class SuperDocsClient:
    """Perform only the four SuperDocs operations PaperForge requires."""

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str,
        timeout_seconds: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key.strip() if isinstance(api_key, str) else ""
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._client = client

    def start_review(
        self, *, message: str, session_id: str, document_html: str
    ) -> dict[str, object]:
        """Start one approval-gated asynchronous document editing job."""
        return self._json_request(
            "POST",
            "/v1/chat/async",
            {
                "message": message,
                "session_id": session_id,
                "document_html": document_html,
                "approval_mode": "ask_every_time",
            },
        )

    def get_job(self, job_id: str) -> dict[str, object]:
        """Retrieve a provider job without interpreting workflow state."""
        return self._json_request("GET", f"/v1/jobs/{job_id}", None)

    def decide_change(
        self,
        *,
        session_id: str,
        job_id: str,
        change_id: str,
        approved: bool,
        feedback: str | None = None,
    ) -> dict[str, object]:
        """Submit exactly one explicit human decision to the same session."""
        payload: dict[str, object] = {
            "job_id": job_id,
            "change_id": change_id,
            "approved": approved,
        }
        if feedback is not None:
            payload["feedback"] = feedback
        return self._json_request(
            "POST", f"/v1/chat/{session_id}/approve", payload
        )

    def export_docx(self, *, session_id: str, filename: str) -> bytes:
        """Export the active approved session as binary DOCX."""
        response = self._request(
            "POST",
            "/v1/documents/export",
            {"session_id": session_id, "format": "docx", "options": {"filename": filename}},
        )
        if not response.content:
            raise SuperDocsProtocolError("SuperDocs returned an empty DOCX export.")
        return response.content

    def _json_request(
        self, method: str, path: str, payload: dict[str, object] | None
    ) -> dict[str, object]:
        response = self._request(method, path, payload)
        try:
            value = response.json()
        except ValueError as exc:
            raise SuperDocsProtocolError("SuperDocs returned an invalid JSON response.") from exc
        if not isinstance(value, dict):
            raise SuperDocsProtocolError("SuperDocs returned an unexpected response.")
        return value

    def _request(
        self, method: str, path: str, payload: dict[str, object] | None
    ) -> httpx.Response:
        if not self._api_key:
            raise SuperDocsNotConfiguredError("SuperDocs review is not configured.")
        try:
            if self._client is not None:
                response = self._client.request(
                    method,
                    f"{self._base_url}{path}",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=payload,
                    timeout=self._timeout_seconds,
                )
            else:
                with httpx.Client(timeout=self._timeout_seconds) as client:
                    response = client.request(
                        method,
                        f"{self._base_url}{path}",
                        headers={"Authorization": f"Bearer {self._api_key}"},
                        json=payload,
                    )
        except httpx.HTTPError as exc:
            raise SuperDocsUnavailableError("SuperDocs is temporarily unavailable.") from exc
        if response.status_code >= 500:
            raise SuperDocsUnavailableError("SuperDocs is temporarily unavailable.")
        if response.status_code >= 400:
            raise SuperDocsProtocolError("SuperDocs rejected the review request.")
        return response
