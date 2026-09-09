"""Resolve the ordered BYOK provider chain from backend-only settings."""

from dataclasses import dataclass

from app.config import settings

SUPPORTED_PROVIDERS = frozenset(
    {"gemini", "mistral", "groq", "openai_compatible", "deterministic"}
)
DEFAULT_PROVIDER_ORDER = (
    "gemini",
    "mistral",
    "groq",
    "openai_compatible",
    "deterministic",
)


@dataclass(frozen=True, slots=True)
class ProviderConfiguration:
    """Non-persistent runtime configuration for one selected provider."""

    name: str
    api_key: str | None
    model: str | None
    base_url: str | None


def configured_provider(provider_name: str | None = None) -> ProviderConfiguration:
    """Return one provider's settings without exposing its key."""
    name = _clean(provider_name or settings.ai_provider).casefold()
    if name not in SUPPORTED_PROVIDERS:
        supported = ", ".join(sorted(SUPPORTED_PROVIDERS))
        raise ValueError(f"AI_PROVIDER must be one of: {supported}.")

    if name == "deterministic":
        return ProviderConfiguration(name=name, api_key=None, model=None, base_url=None)
    if name == "groq":
        return ProviderConfiguration(
            name=name,
            api_key=_optional(settings.groq_api_key),
            model=_optional(settings.groq_model),
            base_url=None,
        )
    if name == "gemini":
        return ProviderConfiguration(
            name=name,
            api_key=_optional(settings.gemini_api_key),
            model=_optional(settings.gemini_model),
            base_url=_optional(settings.gemini_base_url),
        )
    if name == "mistral":
        return ProviderConfiguration(
            name=name,
            api_key=_optional(settings.mistral_api_key),
            model=_optional(settings.mistral_model),
            base_url=_optional(settings.mistral_base_url),
        )
    return ProviderConfiguration(
        name=name,
        api_key=_optional(settings.openai_compatible_api_key),
        model=_optional(settings.openai_compatible_model),
        base_url=_optional(settings.openai_compatible_base_url),
    )


def configured_provider_order() -> tuple[ProviderConfiguration, ...]:
    """Return a validated, deduplicated chain ending in local fallback."""
    explicit_order = _optional(settings.ai_provider_order)
    selected = _clean(settings.ai_provider).casefold()

    if explicit_order is not None:
        names = tuple(
            name.strip().casefold()
            for name in explicit_order.split(",")
            if name.strip()
        )
        if not names:
            raise ValueError("AI_PROVIDER_ORDER must contain at least one provider.")
    elif selected == "deterministic":
        names = ("deterministic",)
    else:
        names = (selected, *DEFAULT_PROVIDER_ORDER)

    ordered_names: list[str] = []
    for name in names:
        if name not in SUPPORTED_PROVIDERS:
            supported = ", ".join(sorted(SUPPORTED_PROVIDERS))
            raise ValueError(
                f"AI provider order contains {name!r}; expected one of: {supported}."
            )
        if name not in ordered_names:
            ordered_names.append(name)

    if "deterministic" not in ordered_names:
        ordered_names.append("deterministic")
    else:
        ordered_names = [
            name for name in ordered_names if name != "deterministic"
        ] + ["deterministic"]
    return tuple(configured_provider(name) for name in ordered_names)


def _clean(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return "groq"
    return value.strip()


def _optional(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()
