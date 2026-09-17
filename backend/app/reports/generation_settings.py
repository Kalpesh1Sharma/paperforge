"""Versioned configuration collected by the new-report wizard."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.reports.presentation_models import (
    PRESENTATION_SECTION_SPECS,
    PresentationSectionKey,
    ReportMode,
)


VisualTemplate = Literal[
    "paperforge-classic",
    "modern-research",
    "ieee-inspired-technical",
    "editorial",
    "minimal",
]
CitationStyle = Literal["source-linked", "apa", "ieee", "harvard"]
ContentTone = Literal["academic", "professional", "executive", "technical"]
PageSize = Literal["A4", "letter"]
ContentDensity = Literal["comfortable", "compact"]


class _SettingsModel(BaseModel):
    # This is an HTTP/JSON input contract: enum strings and JSON arrays must be
    # accepted, while explicit field types and ``extra=forbid`` remain strict.
    model_config = ConfigDict(extra="forbid", frozen=True)


def _normalize_required(value: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError("Required report settings must not be blank.")
    return normalized


def _normalize_optional(value: str | None) -> str | None:
    if value is None:
        return None
    return " ".join(value.split()) or None


class ReportSectionConfiguration(_SettingsModel):
    """One enabled section and its user-facing heading."""

    key: PresentationSectionKey
    heading: str = Field(min_length=1, max_length=120)

    @field_validator("heading")
    @classmethod
    def normalize_heading(cls, value: str) -> str:
        return _normalize_required(value)


def default_report_sections() -> tuple[ReportSectionConfiguration, ...]:
    return tuple(
        ReportSectionConfiguration(key=key, heading=heading)
        for key, heading, _anchor in PRESENTATION_SECTION_SPECS
    )


class ReportStructureConfiguration(_SettingsModel):
    """Content-independent section selection and order."""

    preset: ReportMode = ReportMode.PROFESSIONAL
    sections: tuple[ReportSectionConfiguration, ...] = Field(
        default_factory=default_report_sections,
        min_length=1,
    )

    @field_validator("sections")
    @classmethod
    def validate_unique_sections(
        cls,
        value: tuple[ReportSectionConfiguration, ...],
    ) -> tuple[ReportSectionConfiguration, ...]:
        keys = [section.key for section in value]
        if len(keys) != len(set(keys)):
            raise ValueError("Report sections must not contain duplicate keys.")
        return value


class ReportContentConfiguration(_SettingsModel):
    """Instructions that influence report prose independently of layout."""

    tone: ContentTone = "professional"
    audience: str | None = Field(default=None, max_length=160)
    language: str = Field(default="en", min_length=2, max_length=12)

    @field_validator("audience")
    @classmethod
    def normalize_audience(cls, value: str | None) -> str | None:
        return _normalize_optional(value)

    @field_validator("language")
    @classmethod
    def normalize_language(cls, value: str) -> str:
        return _normalize_required(value).lower()


class VisualThemeConfiguration(_SettingsModel):
    """Presentation choices that do not alter synthesized content."""

    template: VisualTemplate = "paperforge-classic"
    page_size: PageSize = "A4"
    density: ContentDensity = "comfortable"
    accent_color: str | None = None

    @field_validator("accent_color")
    @classmethod
    def validate_accent_color(cls, value: str | None) -> str | None:
        value = _normalize_optional(value)
        if value is not None and (
            len(value) != 7
            or not value.startswith("#")
            or any(character not in "0123456789abcdefABCDEF" for character in value[1:])
        ):
            raise ValueError("accent_color must be a six-digit hexadecimal colour.")
        return value.lower() if value else None


class CitationConfiguration(_SettingsModel):
    """Citation policy, kept separate from report structure and visuals."""

    style: CitationStyle = "source-linked"
    include_bibliography: bool = True


class OutlineApprovalConfiguration(_SettingsModel):
    """Server-issued outline approval attached to a generation request."""

    approved: bool = True
    proposal_id: str | None = None
    revision: int = Field(default=0, ge=0)


class PublicationMetadata(_SettingsModel):
    """User-supplied cover and institutional metadata."""

    title: str = Field(min_length=1, max_length=180)
    subtitle: str | None = Field(default=None, max_length=240)
    author: str = Field(min_length=1, max_length=100)
    organisation: str | None = Field(default=None, max_length=120)
    university: str | None = Field(default=None, max_length=160)
    department: str | None = Field(default=None, max_length=160)
    publication_type: str | None = Field(default=None, max_length=100)

    @field_validator("title", "author")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        return _normalize_required(value)

    @field_validator(
        "subtitle",
        "organisation",
        "university",
        "department",
        "publication_type",
    )
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return _normalize_optional(value)


class ReportGenerationSettings(_SettingsModel):
    """Canonical Phase 2 report configuration with Phase 1 migration."""

    schema_version: Literal[2] = 2
    project_title: str = Field(min_length=1, max_length=100)
    research_domain: str = Field(min_length=1, max_length=100)
    purpose: str | None = Field(default=None, max_length=500)
    report_structure: ReportStructureConfiguration
    content: ReportContentConfiguration = Field(default_factory=ReportContentConfiguration)
    visual_theme: VisualThemeConfiguration = Field(default_factory=VisualThemeConfiguration)
    citations: CitationConfiguration = Field(default_factory=CitationConfiguration)
    outline_approval: OutlineApprovalConfiguration = Field(
        default_factory=OutlineApprovalConfiguration
    )
    publication: PublicationMetadata

    @model_validator(mode="before")
    @classmethod
    def migrate_phase_one_payload(cls, value: object) -> object:
        """Accept stored Phase 1 settings while persisting only schema v2."""
        if not isinstance(value, dict) or "report_structure" in value:
            return value
        migrated = dict(value)
        structure = migrated.pop("structure", ReportMode.PROFESSIONAL.value)
        visual_template = migrated.pop("visual_template", "paperforge-classic")
        report_title = migrated.pop("report_title", None)
        author = migrated.pop("author", None)
        organisation = migrated.pop("organisation", None)
        migrated["schema_version"] = 2
        migrated["report_structure"] = {
            "preset": structure,
            "sections": [
                {"key": key, "heading": heading}
                for key, heading, _anchor in PRESENTATION_SECTION_SPECS
            ],
        }
        migrated["content"] = {}
        migrated["visual_theme"] = {"template": visual_template}
        migrated["citations"] = {}
        if report_title is not None or author is not None:
            migrated["publication"] = {
                "title": report_title,
                "author": author,
                "organisation": organisation,
            }
        return migrated

    @field_validator("project_title", "research_domain")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        return _normalize_required(value)

    @field_validator("purpose")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return _normalize_optional(value)

    # Compatibility accessors keep existing pipeline call sites and old reports safe.
    @property
    def structure(self) -> ReportMode:
        return self.report_structure.preset

    @property
    def visual_template(self) -> VisualTemplate:
        return self.visual_theme.template

    @property
    def report_title(self) -> str:
        return self.publication.title

    @property
    def author(self) -> str:
        return self.publication.author

    @property
    def organisation(self) -> str | None:
        return self.publication.organisation
