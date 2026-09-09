"""Small synchronous client for OpenAI-compatible chat endpoints."""

import logging
import time
from collections.abc import Callable, Sequence
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import httpx

from app.ai.configuration import ProviderConfiguration
from app.ai.exceptions import (
    CompatibleAIAuthenticationError,
    CompatibleAIConfigurationError,
    CompatibleAIMalformedResponseError,
    CompatibleAINetworkError,
    CompatibleAIRateLimitError,
    CompatibleAIRequestError,
    CompatibleAITemporaryServiceError,
    CompatibleAITimeoutError,
)

logger = logging.getLogger(__name__)


class CompatibleChatClient:
    """Send JSON-only chat requests without retaining or logging API keys."""

    def __init__(
        self,
        configuration: ProviderConfiguration,
        *,
        max_retries: int = 2,
        retry_base_seconds: float = 1.0,
        timeout_seconds: float = 60.0,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.provider = configuration.name
        self.model = self._required(configuration.model, "model")
        self._api_key = self._required(configuration.api_key, "API key")
        self._base_url = self._validated_base_url(configuration.base_url)
        self._max_retries = max(0, max_retries)
        self._retry_base_seconds = max(0.0, retry_base_seconds)
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._sleep = sleep

    def complete(self, messages: Sequence[dict[str, str]]) -> str:
        """Return non-empty assistant content or a normalized safe exception."""
        payload = {
            "model": self.model,
            "messages": list(messages),
            "temperature": 0,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        endpoint = f"{self._base_url}/chat/completions"

        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.post(
                    endpoint,
                    headers=self._request_headers(),
                    json=payload,
                )
            except httpx.TimeoutException as exc:
                if attempt < self._max_retries:
                    self._wait(attempt, None)
                    continue
                raise CompatibleAITimeoutError(
                    f"{self.provider} request timed out."
                ) from exc
            except httpx.NetworkError as exc:
                if attempt < self._max_retries:
                    self._wait(attempt, None)
                    continue
                raise CompatibleAINetworkError(
                    f"{self.provider} service could not be reached."
                ) from exc

            if response.status_code == 401:
                raise CompatibleAIAuthenticationError(
                    f"{self.provider} authentication failed."
                )
            if response.status_code == 403:
                raise CompatibleAIAuthenticationError(
                    f"{self.provider} permission was denied."
                )
            if response.status_code == 429:
                if attempt < self._max_retries:
                    self._wait(attempt, response.headers.get("Retry-After"))
                    continue
                raise CompatibleAIRateLimitError(
                    f"{self.provider} request was rate limited."
                )
            if 500 <= response.status_code <= 599:
                if attempt < self._max_retries:
                    self._wait(attempt, response.headers.get("Retry-After"))
                    continue
                raise CompatibleAITemporaryServiceError(
                    f"{self.provider} service returned a server error."
                )
            if response.is_error:
                raise CompatibleAIRequestError(
                    f"{self.provider} rejected the request with HTTP "
                    f"{response.status_code}."
                )

            try:
                body = response.json()
                content = body["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise CompatibleAIMalformedResponseError(
                    f"{self.provider} response contained no usable message content."
                ) from exc
            if not isinstance(content, str) or not content.strip():
                raise CompatibleAIMalformedResponseError(
                    f"{self.provider} response contained no usable message content."
                )
            return content

        raise CompatibleAITemporaryServiceError(
            f"{self.provider} request did not complete."
        )

    def _request_headers(self) -> dict[str, str]:
        """Authenticate OpenAI-compatible providers with a Bearer credential."""
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _wait(self, attempt: int, retry_after: str | None) -> None:
        delay = self._retry_after_seconds(retry_after)
        if delay is None:
            delay = self._retry_base_seconds * (2**attempt)
        delay = min(max(delay, 0.0), 30.0)
        logger.info(
            "AI request retry | provider=%s | attempt=%d | delay_seconds=%.2f",
            self.provider,
            attempt + 1,
            delay,
        )
        self._sleep(delay)

    @staticmethod
    def _retry_after_seconds(value: str | None) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except ValueError:
            try:
                return max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
            except (TypeError, ValueError, OverflowError):
                return None

    @staticmethod
    def _required(value: str | None, label: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise CompatibleAIConfigurationError(f"Provider {label} is required.")
        return value.strip()

    @staticmethod
    def _validated_base_url(value: str | None) -> str:
        base_url = CompatibleChatClient._required(value, "base URL").rstrip("/")
        parsed = urlsplit(base_url)
        local_hosts = {"localhost", "127.0.0.1", "::1"}
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise CompatibleAIConfigurationError(
                "Provider base URL must be an absolute HTTP(S) URL."
            )
        if parsed.scheme != "https" and parsed.hostname not in local_hosts:
            raise CompatibleAIConfigurationError(
                "Provider base URL must use HTTPS except for localhost."
            )
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise CompatibleAIConfigurationError(
                "Provider base URL must not contain credentials, a query, or fragment."
            )
        return base_url
