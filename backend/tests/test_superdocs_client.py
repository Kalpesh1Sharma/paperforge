"""Offline contract tests for the narrow SuperDocs HTTP client."""

import httpx
import pytest

from app.integrations.superdocs.client import SuperDocsClient
from app.integrations.superdocs.exceptions import SuperDocsNotConfiguredError
from app.services.review_service import REVIEW_MESSAGE


def test_client_uses_official_routes_payloads_and_bearer_auth() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/documents/export":
            return httpx.Response(200, content=b"docx", request=request)
        return httpx.Response(200, json={"job_id": "job-1", "status": "pending"}, request=request)

    client = SuperDocsClient(
        api_key="test-key", base_url="https://api.superdocs.app",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    client.start_review(message=REVIEW_MESSAGE, session_id="session-1", document_html="<p>report</p>")
    client.get_job("job-1")
    client.decide_change(session_id="session-1", job_id="job-1", change_id="ch-1", approved=False, feedback="Keep wording.")
    assert client.export_docx(session_id="session-1", filename="paperforge-1-reviewed") == b"docx"

    assert [request.url.path for request in requests] == [
        "/v1/chat/async", "/v1/jobs/job-1", "/v1/chat/session-1/approve", "/v1/documents/export",
    ]
    assert all(request.headers["authorization"] == "Bearer test-key" for request in requests)
    assert requests[0].json() if False else True
    import json
    assert json.loads(requests[0].content) == {
        "message": REVIEW_MESSAGE, "session_id": "session-1", "document_html": "<p>report</p>", "approval_mode": "ask_every_time",
    }
    assert json.loads(requests[2].content) == {
        "job_id": "job-1", "change_id": "ch-1", "approved": False, "feedback": "Keep wording.",
    }


def test_client_defers_missing_configuration_until_review_use() -> None:
    client = SuperDocsClient(api_key=None, base_url="https://api.superdocs.app")
    with pytest.raises(SuperDocsNotConfiguredError):
        client.start_review(message="message", session_id="session", document_html="<p>x</p>")
