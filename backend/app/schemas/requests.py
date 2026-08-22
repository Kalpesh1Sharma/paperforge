"""Request-schema markers for the synchronous PaperForge HTTP API.

Multipart uploads are described directly on route parameters because FastAPI
owns their request-body parsing. This module intentionally remains available
for future JSON request contracts without coupling routes to domain models.
"""

from typing import Literal


ReportOutputFormat = Literal["all", "json", "html", "markdown", "pdf"]
