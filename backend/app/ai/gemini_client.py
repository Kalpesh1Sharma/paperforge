"""Native Gemini transport for current AQ authorization keys."""

from collections.abc import Sequence
import logging
from urllib.parse import quote

import httpx

from app.ai.compatible_client import CompatibleChatClient
from app.ai.configuration import ProviderConfiguration
from app.ai.exceptions import (
    CompatibleAIAuthenticationError,
    CompatibleAIMalformedResponseError,
    CompatibleAINetworkError,
    CompatibleAIRateLimitError,
    CompatibleAIRequestError,
    CompatibleAITemporaryServiceError,
    CompatibleAITimeoutError,
)

logger = logging.getLogger(__name__)


class GeminiNativeChatClient(CompatibleChatClient):
    """Adapt PaperForge chat prompts to Gemini's native generateContent API."""

    def __init__(self, configuration: ProviderConfiguration, **kwargs: object) -> None:
        super().__init__(configuration, **kwargs)  # type: ignore[arg-type]
        self._native_base_url = self._base_url.removesuffix("/openai")

    def complete(self, messages: Sequence[dict[str, str]]) -> str:
        """Return JSON text using Gemini's API-key-native endpoint."""
        system_parts = [
            {"text": message["content"]}
            for message in messages
            if message.get("role") == "system"
        ]
        contents = [
            {
                "role": "model" if message.get("role") == "assistant" else "user",
                "parts": [{"text": message["content"]}],
            }
            for message in messages
            if message.get("role") != "system"
        ]
        payload: dict[str, object] = {
            "contents": contents,
            "generationConfig": {"responseMimeType": "application/json"},
        }
        if system_parts:
            payload["system_instruction"] = {"parts": system_parts}

        model = quote(self.model, safe="-._")
        endpoint = f"{self._native_base_url}/models/{model}:generateContent"
        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.post(
                    endpoint,
                    headers={
                        "x-goog-api-key": self._api_key,
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            except httpx.TimeoutException as exc:
                if attempt < self._max_retries:
                    self._wait(attempt, None)
                    continue
                raise CompatibleAITimeoutError("gemini request timed out.") from exc
            except httpx.NetworkError as exc:
                if attempt < self._max_retries:
                    self._wait(attempt, None)
                    continue
                raise CompatibleAINetworkError(
                    "gemini service could not be reached."
                ) from exc

            if response.status_code in {401, 403} or self._is_invalid_key(response):
                self._log_rejection(response)
                raise CompatibleAIAuthenticationError(
                    "Gemini authentication failed. Check GEMINI_API_KEY."
                )
            if response.status_code == 429:
                if attempt < self._max_retries:
                    self._wait(attempt, response.headers.get("Retry-After"))
                    continue
                self._log_rejection(response)
                raise CompatibleAIRateLimitError("gemini request was rate limited.")
            if 500 <= response.status_code <= 599:
                if attempt < self._max_retries:
                    self._wait(attempt, response.headers.get("Retry-After"))
                    continue
                self._log_rejection(response)
                raise CompatibleAITemporaryServiceError(
                    "gemini service returned a server error."
                )
            if response.is_error:
                self._log_rejection(response)
                raise CompatibleAIRequestError(
                    f"gemini rejected the request with HTTP {response.status_code}."
                )

            try:
                body = response.json()
                parts = body["candidates"][0]["content"]["parts"]
                content = "".join(
                    part.get("text", "") for part in parts if isinstance(part, dict)
                )
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise CompatibleAIMalformedResponseError(
                    "gemini response contained no usable content."
                ) from exc
            if not content.strip():
                raise CompatibleAIMalformedResponseError(
                    "gemini response contained no usable content."
                )
            return content

        raise CompatibleAITemporaryServiceError("gemini request did not complete.")

    def _log_rejection(self, response: httpx.Response) -> None:
        """Log only non-secret Gemini status fields, never bodies or prompts."""
        provider_status, provider_code = self._safe_error_details(response)
        logger.warning(
            "Gemini request rejected | http_status=%s | provider_status=%s | "
            "provider_code=%s | model=%s",
            response.status_code,
            provider_status or "unknown",
            provider_code or "unknown",
            self.model,
        )

    @staticmethod
    def _safe_error_details(response: httpx.Response) -> tuple[str | None, str | None]:
        try:
            body = response.json()
        except ValueError:
            return None, None
        if isinstance(body, list) and body:
            body = body[0]
        if not isinstance(body, dict):
            return None, None
        error = body.get("error", body)
        if not isinstance(error, dict):
            return None, None
        status = error.get("status")
        code = error.get("code")
        return (
            status if isinstance(status, str) else None,
            str(code) if isinstance(code, (str, int)) and not isinstance(code, bool) else None,
        )

    @staticmethod
    def _is_invalid_key(response: httpx.Response) -> bool:
        if response.status_code != 400:
            return False
        try:
            body = response.json()
        except ValueError:
            return False
        if isinstance(body, list) and body:
            body = body[0]
        if not isinstance(body, dict):
            return False
        error = body.get("error", body)
        if not isinstance(error, dict):
            return False
        message = error.get("message")
        return isinstance(message, str) and "valid api key" in message.casefold()
