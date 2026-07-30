"""Deterministic, immutable presentation intelligence for enhanced reports.

The intelligence overlay derives quality metadata from an enhanced report and
its source knowledge objects.  It never alters the canonical report payload or
performs AI, I/O, or provider work.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from hashlib import sha256
import math
import re
from typing import TYPE_CHECKING, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    ValidationError,
    field_validator,
    model_validator,
)

from app.knowledge.models import KnowledgeObject
from app.reports.exceptions import InvalidResearchReportError, ReportSynthesisError
from app.reports.models import Finding

if TYPE_CHECKING:
    from app.reports.enhanced_models import EnhancedResearchReport


EntityCategory = Literal[
    "Organizations",
    "Technologies",
    "Standards",
    "Libraries",
    "Programming Languages",
    "Products",
    "People",
    "Locations",
    "File Formats",
    "Concepts",
    "Other",
]
Importance = Literal["HIGH", "MEDIUM", "LOW"]

_CATEGORY_ORDER: tuple[EntityCategory, ...] = (
    "Organizations",
    "Technologies",
    "Standards",
    "Libraries",
    "Programming Languages",
    "Products",
    "People",
    "Locations",
    "File Formats",
    "Concepts",
    "Other",
)
_CATEGORY_INDEX = {category: index for index, category in enumerate(_CATEGORY_ORDER)}
_SPACE_PATTERN = re.compile(r"\s+")
_TOKEN_PATTERN = re.compile(r"[\w+#/.-]+", re.UNICODE)
_SENTENCE_END_PATTERN = re.compile(r"(?<=[.!?])\s+")
_MILESTONE_PATTERN = re.compile(
    r"\b(?:introduced|published|released|adopted|approved|established|"
    r"standardized|ratified|announced|launched)\b",
    re.IGNORECASE,
)
_ISO_DATE_PATTERN = re.compile(r"^(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})$")
_MONTH_YEAR_PATTERN = re.compile(
    r"^(?P<month>January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+(?P<year>\d{4})$",
    re.IGNORECASE,
)
_YEAR_PATTERN = re.compile(r"^\d{4}$")
_YEAR_IN_TEXT_PATTERN = re.compile(r"(?<!\d)(?P<year>\d{4})(?!\d)")
_SPECIFIC_DATE_IN_FACT_PATTERN = re.compile(
    r"\b(?:\d{4}-\d{2}-\d{2}|(?:January|February|March|April|May|June|"
    r"July|August|September|October|November|December)\s+\d{4})\b",
    re.IGNORECASE,
)
_MONTH_NUMBERS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_MAX_RELATED_CONCEPTS_PER_SOURCE = 32

_ENTITY_ALIASES: dict[str, tuple[str, EntityCategory]] = {
    "pdf": ("PDF", "Technologies"),
    "portable document format": ("PDF", "Technologies"),
    "portable document formats": ("PDF", "Technologies"),
    "adobe reader": ("Adobe Reader", "Products"),
    "acrobat reader": ("Adobe Reader", "Products"),
    "adobe acrobat": ("Adobe Acrobat", "Products"),
}
_DEFINITION_CONCEPT_ALIASES: dict[str, str] = {
    "pdf": "PDF",
    "portable document format": "PDF",
    "portable document formats": "PDF",
}
_DISPLAY_NAMES = {
    "pdf": "PDF",
    "ocr": "OCR",
    "api": "API",
    "json": "JSON",
    "xml": "XML",
    "html": "HTML",
    "url": "URL",
    "mime": "MIME",
    "iso": "ISO",
    "ecma": "ECMA",
    "pypdf": "PyPDF",
    "pdfplumber": "pdfplumber",
    "apache pdfbox": "Apache PDFBox",
    "itext": "iText",
    "python": "Python",
    "java": "Java",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "c": "C",
    "c++": "C++",
    "c#": "C#",
    "go": "Go",
    "rust": "Rust",
    "openai": "OpenAI",
    "microsoft": "Microsoft",
    "google": "Google",
    "apache": "Apache",
    "acrobat": "Acrobat",
    "chrome": "Chrome",
    "safari": "Safari",
    "north america": "North America",
    "south america": "South America",
    "asia pacific": "Asia Pacific",
    "latin america": "Latin America",
    "middle east": "Middle East",
    "digital signature": "Digital Signature",
    "embedded font": "Embedded Font",
    "content stream": "Content Stream",
    "text formatting": "Text Formatting",
    "docx": "DOCX",
    "txt": "TXT",
    "markdown": "Markdown",
    "adobe": "Adobe",
    "adobe reader": "Adobe Reader",
    "adobe acrobat": "Adobe Acrobat",
}
_ORGANIZATIONS = frozenset({"adobe", "microsoft", "google", "openai", "apache"})
_TECHNOLOGIES = frozenset({"pdf", "ocr", "api", "json", "xml", "html"})
_LIBRARIES = frozenset({"pypdf", "pdfplumber", "apache pdfbox", "itext"})
_PROGRAMMING_LANGUAGES = frozenset(
    {"python", "java", "javascript", "typescript", "c", "c++", "c#", "go", "rust"}
)
_PRODUCTS = frozenset(
    {"acrobat", "chrome", "safari", "adobe reader", "adobe acrobat"}
)
_LOCATIONS = frozenset(
    {
        "north america",
        "south america",
        "europe",
        "asia",
        "asia pacific",
        "latin america",
        "middle east",
        "africa",
    }
)
_FILE_FORMATS = frozenset({"docx", "txt", "markdown", "csv", "zip", "mpeg", "jpeg"})
_CONCEPTS = frozenset(
    {
        "digital signature",
        "embedded font",
        "content stream",
        "bookmark",
        "annotation",
        "typography",
        "text formatting",
    }
)
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "with",
    }
)
_LOW_INFORMATION_ENTITY_PHRASES = frozenset(
    {
        "upload form",
        "upload forms",
        "parser",
        "parsers",
        "pdf parser",
        "pdf parsers",
        "pdf reader",
        "pdf readers",
        "pdf document",
        "pdf documents",
        "document",
        "documents",
        "document processing",
        "document processing workflow",
        "document processing workflows",
        "workflow",
        "workflows",
        "government agency",
        "government agencies",
        "financial institution",
        "financial institutions",
        "healthcare organization",
        "healthcare organizations",
        "industry",
        "industries",
        "organization",
        "organizations",
        "role",
        "roles",
        "professional",
        "professionals",
        "system",
        "systems",
        "feature",
        "features",
        "process",
        "processes",
        "service",
        "services",
        "application",
        "applications",
        "technology",
        "technologies",
        "standard",
        "standards",
        "format",
        "formats",
        "platform",
        "platforms",
        "performance",
        "security",
        "accessibility",
    }
)
_LOW_INFORMATION_ENTITY_TOKENS = frozenset(
    {
        "upload",
        "form",
        "forms",
        "parser",
        "parsers",
        "reader",
        "readers",
        "document",
        "documents",
        "processing",
        "workflow",
        "workflows",
        "government",
        "agency",
        "agencies",
        "financial",
        "institution",
        "institutions",
        "healthcare",
        "organization",
        "organizations",
        "industry",
        "industries",
        "role",
        "roles",
        "generic",
        "common",
        "improved",
        "improve",
        "improving",
        "created",
        "create",
        "processing",
    }
)
_RELATION_CONCEPT_EXCLUSIONS = frozenset(
    {"it", "this", "that", "they", "these", "those", "there", "the document"}
)
_TRACKING_QUERY_PARAMETERS = frozenset(
    {
        "fbclid",
        "gclid",
        "dclid",
        "msclkid",
        "mc_cid",
        "mc_eid",
        "_hsenc",
        "_hsmi",
    }
)


class _IntelligenceModel(BaseModel):
    """Shared strict, immutable configuration for intelligence values."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        allow_inf_nan=False,
    )


def _validate_non_blank(value: str, field_name: str) -> str:
    """Reject whitespace-only model text without rewriting evidence."""
    if not value.strip():
        raise ValueError(f"{field_name} must not be blank.")
    return value


def _validate_string_tuple(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    """Require nonblank unique tuple text when a model records a collection."""
    if any(not value.strip() for value in values):
        raise ValueError(f"{field_name} must not contain blank text.")
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} must not contain duplicate values.")
    return values


def _validate_source_ids(values: tuple[UUID, ...], field_name: str) -> tuple[UUID, ...]:
    """Require ordered, nonempty, nonduplicated provenance identifiers."""
    if not values:
        raise ValueError(f"{field_name} must not be empty.")
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} must not contain duplicate UUIDs.")
    return values


class NormalizedEntity(_IntelligenceModel):
    """One canonical entity with its retained aliases and source evidence."""

    name: str = Field(min_length=1)
    aliases: tuple[str, ...] = Field(default_factory=tuple)
    supporting_chunk_ids: tuple[UUID, ...] = Field(min_length=1)
    references: tuple[str, ...] = Field(default_factory=tuple)
    confidence: StrictFloat = Field(..., ge=0.0, le=1.0)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """Require a readable canonical entity name."""
        return _validate_non_blank(value, "Entity name")

    @field_validator("aliases", "references")
    @classmethod
    def validate_text_collections(
        cls,
        value: tuple[str, ...],
        info: object,
    ) -> tuple[str, ...]:
        """Keep text evidence immutable and duplicate-free."""
        field_name = getattr(info, "field_name", "Entity collection")
        return _validate_string_tuple(value, field_name)

    @field_validator("supporting_chunk_ids")
    @classmethod
    def validate_sources(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        """Require entity provenance."""
        return _validate_source_ids(value, "Entity supporting_chunk_ids")

    @field_validator("confidence", mode="before")
    @classmethod
    def validate_confidence_type(cls, value: object) -> object:
        """Keep confidence strictly float-valued."""
        if isinstance(value, bool) or not isinstance(value, float):
            raise ValueError("Entity confidence must be a float.")
        return value


class EntityGroup(_IntelligenceModel):
    """Entities grouped under one deterministic category."""

    category: EntityCategory
    entities: tuple[NormalizedEntity, ...] = Field(min_length=1)

    @field_validator("entities")
    @classmethod
    def validate_entities(
        cls,
        value: tuple[NormalizedEntity, ...],
    ) -> tuple[NormalizedEntity, ...]:
        """Forbid duplicate canonical names within a category."""
        names = tuple(entity.name.casefold() for entity in value)
        if len(set(names)) != len(names):
            raise ValueError("EntityGroup entities must have unique names.")
        return value


class ConsolidatedDefinition(_IntelligenceModel):
    """One best-evidence definition for a normalized concept."""

    concept: str = Field(min_length=1)
    definition: str = Field(min_length=1)
    related_concepts: tuple[str, ...] = Field(default_factory=tuple)
    supporting_chunk_ids: tuple[UUID, ...] = Field(min_length=1)
    references: tuple[str, ...] = Field(default_factory=tuple)
    confidence: StrictFloat = Field(..., ge=0.0, le=1.0)

    @field_validator("concept", "definition")
    @classmethod
    def validate_text(cls, value: str, info: object) -> str:
        """Reject blank definition content."""
        return _validate_non_blank(value, getattr(info, "field_name", "Definition"))

    @field_validator("related_concepts", "references")
    @classmethod
    def validate_text_collections(
        cls,
        value: tuple[str, ...],
        info: object,
    ) -> tuple[str, ...]:
        """Keep related concepts and citations stable."""
        return _validate_string_tuple(value, getattr(info, "field_name", "Definition collection"))

    @field_validator("supporting_chunk_ids")
    @classmethod
    def validate_sources(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        """Require definition provenance."""
        return _validate_source_ids(value, "Definition supporting_chunk_ids")

    @field_validator("confidence", mode="before")
    @classmethod
    def validate_confidence_type(cls, value: object) -> object:
        """Keep confidence strictly float-valued."""
        if isinstance(value, bool) or not isinstance(value, float):
            raise ValueError("Definition confidence must be a float.")
        return value


class IntelligentTimelineEvent(_IntelligenceModel):
    """A source-backed historical event retained by timeline intelligence."""

    date: str = Field(min_length=1)
    description: str = Field(min_length=1)
    supporting_chunk_ids: tuple[UUID, ...] = Field(min_length=1)
    references: tuple[str, ...] = Field(default_factory=tuple)
    confidence: StrictFloat = Field(..., ge=0.0, le=1.0)

    @field_validator("date", "description")
    @classmethod
    def validate_text(cls, value: str, info: object) -> str:
        """Reject blank timeline content."""
        return _validate_non_blank(value, getattr(info, "field_name", "Timeline value"))

    @field_validator("references")
    @classmethod
    def validate_references(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Keep event references stable."""
        return _validate_string_tuple(value, "Timeline references")

    @field_validator("supporting_chunk_ids")
    @classmethod
    def validate_sources(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        """Require event provenance."""
        return _validate_source_ids(value, "Timeline supporting_chunk_ids")

    @field_validator("confidence", mode="before")
    @classmethod
    def validate_confidence_type(cls, value: object) -> object:
        """Keep confidence strictly float-valued."""
        if isinstance(value, bool) or not isinstance(value, float):
            raise ValueError("Timeline confidence must be a float.")
        return value


class EnrichedFinding(_IntelligenceModel):
    """Derived display metadata for one authoritative finding."""

    source_kind: Literal["finding", "appendix"]
    source_index: int = Field(ge=0)
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    supporting_chunk_ids: tuple[UUID, ...] = Field(min_length=1)
    references: tuple[str, ...] = Field(default_factory=tuple)
    confidence: StrictFloat = Field(..., ge=0.0, le=1.0)
    importance: Importance

    @field_validator("importance", mode="before")
    @classmethod
    def normalize_importance(cls, value: object) -> object:
        """Accept legacy casing while storing the canonical public label."""
        if not isinstance(value, str):
            raise ValueError("Finding importance must be text.")
        normalized = value.upper()
        if normalized not in {"HIGH", "MEDIUM", "LOW"}:
            raise ValueError("Finding importance must be HIGH, MEDIUM, or LOW.")
        return normalized

    @field_validator("title", "summary")
    @classmethod
    def validate_text(cls, value: str, info: object) -> str:
        """Reject blank finding display content."""
        return _validate_non_blank(value, getattr(info, "field_name", "Finding value"))

    @field_validator("references")
    @classmethod
    def validate_references(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Keep citation display deterministic."""
        return _validate_string_tuple(value, "Finding references")

    @field_validator("supporting_chunk_ids")
    @classmethod
    def validate_sources(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        """Require finding provenance."""
        return _validate_source_ids(value, "Finding supporting_chunk_ids")

    @field_validator("confidence", mode="before")
    @classmethod
    def validate_confidence_type(cls, value: object) -> object:
        """Keep confidence strictly float-valued."""
        if isinstance(value, bool) or not isinstance(value, float):
            raise ValueError("Finding confidence must be a float.")
        return value


class ConsolidatedReference(_IntelligenceModel):
    """One globally deduplicated reference with its supporting sources."""

    reference: str = Field(min_length=1)
    supporting_chunk_ids: tuple[UUID, ...] = Field(min_length=1)

    @field_validator("reference")
    @classmethod
    def validate_reference(cls, value: str) -> str:
        """Reject blank reference values."""
        return _validate_non_blank(value, "Reference")

    @field_validator("supporting_chunk_ids")
    @classmethod
    def validate_sources(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        """Require reference provenance."""
        return _validate_source_ids(value, "Reference supporting_chunk_ids")


class ReportIntelligence(_IntelligenceModel):
    """Read-only deterministic quality metadata for an enhanced report."""

    entity_groups: tuple[EntityGroup, ...] = Field(default_factory=tuple)
    definitions: tuple[ConsolidatedDefinition, ...] = Field(default_factory=tuple)
    timeline: tuple[IntelligentTimelineEvent, ...] = Field(default_factory=tuple)
    findings: tuple[EnrichedFinding, ...] = Field(default_factory=tuple)
    references: tuple[ConsolidatedReference, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_unique_overlay_values(self) -> "ReportIntelligence":
        """Reject duplicate entries that would make presentation ambiguous."""
        categories = tuple(group.category for group in self.entity_groups)
        if len(set(categories)) != len(categories):
            raise ValueError("ReportIntelligence entity groups must be unique.")

        concepts = tuple(definition.concept.casefold() for definition in self.definitions)
        if len(set(concepts)) != len(concepts):
            raise ValueError("ReportIntelligence definitions must be unique by concept.")

        source_keys = tuple(
            (finding.source_kind, finding.source_index) for finding in self.findings
        )
        if len(set(source_keys)) != len(source_keys):
            raise ValueError("ReportIntelligence findings must map each source once.")

        references = tuple(reference.reference.casefold() for reference in self.references)
        if len(set(references)) != len(references):
            raise ValueError("ReportIntelligence references must be unique.")
        return self


@dataclass
class _EvidenceAccumulator:
    """Mutable build-only source ledger converted to immutable model tuples."""

    supporting_chunk_ids: list[UUID] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    _seen_chunk_ids: set[UUID] = field(default_factory=set)
    _seen_references: set[str] = field(default_factory=set)

    def add_source(self, knowledge_object: KnowledgeObject) -> None:
        """Append one source and its references in first-seen order."""
        if knowledge_object.chunk_id not in self._seen_chunk_ids:
            self._seen_chunk_ids.add(knowledge_object.chunk_id)
            self.supporting_chunk_ids.append(knowledge_object.chunk_id)

        for reference in knowledge_object.references:
            normalized = _normalize_reference(reference)
            normalized_key = normalized.casefold()
            if normalized and normalized_key not in self._seen_references:
                self._seen_references.add(normalized_key)
                self.references.append(normalized)


@dataclass
class _EntityAccumulator:
    """Mutable entity build state with retained aliases."""

    name: str
    category: EntityCategory
    evidence: _EvidenceAccumulator = field(default_factory=_EvidenceAccumulator)
    aliases: list[str] = field(default_factory=list)
    _seen_aliases: set[str] = field(default_factory=set)

    def add(self, raw_value: str, knowledge_object: KnowledgeObject) -> None:
        """Retain only genuine alternate names and source evidence once."""
        alias_key = raw_value.casefold()
        if (
            alias_key != self.name.casefold()
            and alias_key not in self._seen_aliases
        ):
            self._seen_aliases.add(alias_key)
            self.aliases.append(raw_value)
        self.evidence.add_source(knowledge_object)


@dataclass
class _DefinitionCandidate:
    """One parsed definition candidate and its original source order."""

    definition: str
    knowledge_object: KnowledgeObject
    source_index: int


@dataclass
class _DefinitionAccumulator:
    """Mutable definition grouping state."""

    concept: str
    is_opaque: bool
    candidates: list[_DefinitionCandidate] = field(default_factory=list)
    evidence: _EvidenceAccumulator = field(default_factory=_EvidenceAccumulator)


@dataclass
class _TimelineAccumulator:
    """Mutable timeline grouping state."""

    date_text: str
    sort_key: tuple[int, int, int, str]
    description: str
    evidence: _EvidenceAccumulator = field(default_factory=_EvidenceAccumulator)


@dataclass(frozen=True)
class _FindingScore:
    """Private numerical score retained only while constructing importance labels."""

    value: int
    importance: Importance


class ReportIntelligenceBuilder:
    """Build a deterministic presentation overlay without changing report truth."""

    def build(
        self,
        report: EnhancedResearchReport,
        knowledge_objects: tuple[KnowledgeObject, ...],
    ) -> EnhancedResearchReport:
        """Return a new enhanced report whose only changed field is intelligence."""
        self._validate_report(report)
        knowledge_by_id = self._validate_knowledge_objects(knowledge_objects)
        self._validate_authoritative_provenance(report, knowledge_by_id)

        entity_groups = self._build_entity_groups(
            report,
            knowledge_objects,
            knowledge_by_id,
        )
        definitions = self._build_definitions(knowledge_objects, knowledge_by_id)
        timeline = self._build_timeline(knowledge_objects, knowledge_by_id)
        findings = self._build_findings(report, knowledge_by_id, entity_groups)
        used_chunk_ids = self._used_chunk_ids(
            entity_groups,
            definitions,
            timeline,
            findings,
        )
        references = self._build_references(knowledge_objects, used_chunk_ids)

        try:
            intelligence = ReportIntelligence(
                entity_groups=entity_groups,
                definitions=definitions,
                timeline=timeline,
                findings=findings,
                references=references,
            )
            return report.model_copy(update={"report_intelligence": intelligence})
        except (TypeError, ValidationError, ValueError) as exc:
            raise ReportSynthesisError(
                "Unable to construct deterministic report intelligence."
            ) from exc

    @staticmethod
    def _validate_report(report: object) -> None:
        """Defensively validate an immutable enhanced report without copying it."""
        from app.reports.enhanced_models import EnhancedResearchReport

        if not isinstance(report, EnhancedResearchReport):
            raise InvalidResearchReportError(
                "Input must be an EnhancedResearchReport instance."
            )
        if getattr(report, "__pydantic_extra__", None):
            raise InvalidResearchReportError(
                "EnhancedResearchReport must not contain extra fields."
            )

        try:
            payload = report.model_dump(mode="python", warnings="error")
            EnhancedResearchReport.model_validate(payload)
        except (AttributeError, TypeError, ValidationError, ValueError) as exc:
            raise InvalidResearchReportError(
                "EnhancedResearchReport failed structural validation."
            ) from exc
        except Exception as exc:
            raise InvalidResearchReportError(
                "EnhancedResearchReport could not be validated safely."
            ) from exc

    @staticmethod
    def _validate_knowledge_objects(
        knowledge_objects: object,
    ) -> dict[UUID, KnowledgeObject]:
        """Validate source objects and return their deterministic UUID index."""
        if not isinstance(knowledge_objects, tuple):
            raise ReportSynthesisError(
                "Knowledge objects must be provided as a tuple."
            )

        knowledge_by_id: dict[UUID, KnowledgeObject] = {}
        for knowledge_object in knowledge_objects:
            if not isinstance(knowledge_object, KnowledgeObject):
                raise ReportSynthesisError(
                    "Each input item must be a KnowledgeObject instance."
                )
            if getattr(knowledge_object, "__pydantic_extra__", None):
                raise ReportSynthesisError(
                    "KnowledgeObject must not contain extra fields."
                )
            try:
                payload = knowledge_object.model_dump(mode="python", warnings="error")
                KnowledgeObject.model_validate(payload)
            except (AttributeError, TypeError, ValidationError, ValueError) as exc:
                raise ReportSynthesisError(
                    "KnowledgeObject failed structural validation."
                ) from exc
            if knowledge_object.chunk_id in knowledge_by_id:
                raise ReportSynthesisError(
                    "Knowledge objects must not reuse a chunk_id."
                )
            knowledge_by_id[knowledge_object.chunk_id] = knowledge_object

        return knowledge_by_id

    @staticmethod
    def _validate_authoritative_provenance(
        report: EnhancedResearchReport,
        knowledge_by_id: dict[UUID, KnowledgeObject],
    ) -> None:
        """Require every canonical claim to remain source-addressable."""
        statements = (
            *(report.base_report.findings),
            *(report.findings),
            *(report.appendix_findings),
            *(report.base_report.timeline),
        )
        for statement in statements:
            supporting_chunk_ids = statement.supporting_chunk_ids
            if not supporting_chunk_ids:
                raise ReportSynthesisError(
                    "Canonical report claims must include source provenance."
                )
            if not set(supporting_chunk_ids).issubset(knowledge_by_id):
                raise ReportSynthesisError(
                    "Canonical report provenance must reference supplied knowledge "
                    "objects."
                )

        source_evidence = report.synthesis_metadata.source_evidence
        evidence_ids = tuple(evidence.chunk_id for evidence in source_evidence)
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ReportSynthesisError(
                "Synthesis source evidence must not reuse a chunk_id."
            )
        if not set(evidence_ids).issubset(knowledge_by_id):
            raise ReportSynthesisError(
                "Synthesis source evidence must reference supplied knowledge objects."
            )

    @classmethod
    def _build_entity_groups(
        cls,
        report: EnhancedResearchReport,
        knowledge_objects: tuple[KnowledgeObject, ...],
        knowledge_by_id: dict[UUID, KnowledgeObject],
    ) -> tuple[EntityGroup, ...]:
        """Filter, normalize, and rank every retained entity with evidence."""
        accumulators: dict[str, _EntityAccumulator] = {}
        raw_entity_frequency = Counter(
            cls._normalized_key(raw_entity)
            for knowledge_object in knowledge_objects
            for raw_entity in knowledge_object.entities
            if _normalize_whitespace(raw_entity)
        )
        for knowledge_object in knowledge_objects:
            for raw_entity in knowledge_object.entities:
                entity = _normalize_whitespace(raw_entity)
                if not entity:
                    continue
                if not cls._should_retain_entity(
                    entity,
                    raw_entity_frequency[cls._normalized_key(entity)],
                ):
                    continue
                canonical_name, category = cls._classify_entity(entity)
                entity_key = canonical_name.casefold()
                accumulator = accumulators.get(entity_key)
                if accumulator is None:
                    accumulator = _EntityAccumulator(canonical_name, category)
                    accumulators[entity_key] = accumulator
                accumulator.add(entity, knowledge_object)

        finding_participation = cls._entity_finding_participation(
            accumulators,
            report,
        )
        grouped: dict[
            EntityCategory,
            list[tuple[NormalizedEntity, tuple[float, int, int, int]]],
        ] = {}
        for entity_key, accumulator in accumulators.items():
            source_ids = tuple(accumulator.evidence.supporting_chunk_ids)
            entity = NormalizedEntity(
                name=accumulator.name,
                aliases=tuple(accumulator.aliases),
                supporting_chunk_ids=source_ids,
                references=tuple(accumulator.evidence.references),
                confidence=cls._mean_confidence(source_ids, knowledge_by_id),
            )
            grouped.setdefault(accumulator.category, []).append(
                (
                    entity,
                    cls._entity_rank_key(
                        entity,
                        finding_participation.get(entity_key, 0),
                    ),
                )
            )

        return tuple(
            EntityGroup(
                category=category,
                entities=tuple(
                    entity
                    for entity, _ in sorted(
                        entities,
                        key=lambda item: (
                            -item[1][0],
                            -item[1][1],
                            -item[1][2],
                            -item[1][3],
                            item[0].name.casefold(),
                            item[0].name,
                        ),
                    )
                ),
            )
            for category, entities in sorted(
                grouped.items(),
                key=lambda item: _CATEGORY_INDEX[item[0]],
            )
        )

    @classmethod
    def _should_retain_entity(cls, value: str, occurrence_count: int) -> bool:
        """Reject generic extracted phrases while retaining curated named values."""
        key = cls._normalized_key(value)
        if not key or key in _LOW_INFORMATION_ENTITY_PHRASES:
            return False
        if cls._is_curated_entity_key(key):
            return True

        tokens = tuple(_TOKEN_PATTERN.findall(value))
        content_tokens = tuple(token.casefold() for token in tokens if token)
        if not content_tokens:
            return False
        if all(token in _LOW_INFORMATION_ENTITY_TOKENS for token in content_tokens):
            return False
        if cls._looks_like_named_entity(tokens):
            return True
        if any(
            token in _LOW_INFORMATION_ENTITY_TOKENS
            for token in content_tokens
        ) and len(content_tokens) <= 3:
            return False

        # A repeated lower-case phrase remains eligible only when it contains
        # an identifier-like token.  This keeps recurring product identifiers
        # without promoting generic workflow language.
        return occurrence_count >= 2 and any(
            any(character.isdigit() for character in token)
            or "+" in token
            or "#" in token
            for token in tokens
        )

    @staticmethod
    def _is_curated_entity_key(key: str) -> bool:
        """Identify taxonomy values before applying conservative heuristics."""
        return (
            key in _ENTITY_ALIASES
            or key in _DISPLAY_NAMES
            or key in _ORGANIZATIONS
            or key in _TECHNOLOGIES
            or key in _LIBRARIES
            or key in _PROGRAMMING_LANGUAGES
            or key in _PRODUCTS
            or key in _LOCATIONS
            or key in _FILE_FORMATS
            or key in _CONCEPTS
            or key.startswith(("iso ", "pdf/", "ecma"))
        )

    @staticmethod
    def _looks_like_named_entity(tokens: tuple[str, ...]) -> bool:
        """Use a deliberately narrow proper-name heuristic for unknown terms."""
        alphabetic = tuple(token for token in tokens if any(char.isalpha() for char in token))
        if not alphabetic:
            return False
        if any(
            token.isupper() and len(token) >= 2
            for token in alphabetic
        ):
            return True
        if any(
            len(token) >= 3
            and token[0].islower()
            and any(character.isupper() for character in token[1:])
            for token in alphabetic
        ):
            return True
        return all(
            token[0].isupper() or token.isupper()
            for token in alphabetic
        )

    @staticmethod
    def _entity_rank_key(
        entity: NormalizedEntity,
        finding_participation: int,
    ) -> tuple[float, int, int, int]:
        """Score all retained entities without imposing a presentation limit."""
        source_count = len(entity.supporting_chunk_ids)
        reference_count = len(entity.references)
        score = (
            entity.confidence
            * (1 + source_count)
            * (1 + reference_count)
            * (1 + finding_participation)
        )
        return score, source_count, reference_count, finding_participation

    @classmethod
    def _entity_finding_participation(
        cls,
        accumulators: dict[str, _EntityAccumulator],
        report: EnhancedResearchReport,
    ) -> dict[str, int]:
        """Index authoritative findings once for deterministic entity ranking.

        The previous per-entity scan repeatedly tokenized every finding.  This
        index keeps temporary state proportional to the finding vocabulary and
        checks only the least-frequent entity-token candidates for each entity.
        It preserves the exact participation rule used for ranking.
        """
        findings = (
            *(report.base_report.findings),
            *(report.findings),
            *(report.appendix_findings),
        )
        finding_tokens: list[frozenset[str]] = []
        finding_source_ids: list[frozenset[UUID]] = []
        token_index: dict[str, list[int]] = {}

        for index, finding in enumerate(findings):
            tokens = _content_tokens(f"{finding.title} {finding.description}")
            finding_tokens.append(tokens)
            finding_source_ids.append(frozenset(finding.supporting_chunk_ids))
            for token in tokens:
                token_index.setdefault(token, []).append(index)

        participation: dict[str, int] = {}
        for entity_key, accumulator in accumulators.items():
            entity_tokens = _content_tokens(accumulator.name)
            if not entity_tokens:
                participation[entity_key] = 0
                continue

            candidate_lists = tuple(
                token_index.get(token, ()) for token in entity_tokens
            )
            if not candidate_lists or any(not values for values in candidate_lists):
                participation[entity_key] = 0
                continue

            candidates = min(candidate_lists, key=len)
            source_ids = frozenset(accumulator.evidence.supporting_chunk_ids)
            participation[entity_key] = sum(
                1
                for index in candidates
                if source_ids.intersection(finding_source_ids[index])
                and entity_tokens.issubset(finding_tokens[index])
            )

        return participation

    @staticmethod
    def _classify_entity(value: str) -> tuple[str, EntityCategory]:
        """Return a curated canonical entity label and conservative category."""
        normalized_value = _normalize_whitespace(value)
        key = normalized_value.casefold()
        alias = _ENTITY_ALIASES.get(key)
        if alias is not None:
            return alias

        name = _DISPLAY_NAMES.get(key, normalized_value)
        if key in _ORGANIZATIONS:
            return name, "Organizations"
        if key.startswith("iso "):
            return "ISO " + normalized_value[4:].strip(), "Standards"
        if key.startswith("pdf/"):
            return "PDF/" + normalized_value.split("/", maxsplit=1)[1].upper(), "Standards"
        if key.startswith("ecma"):
            return normalized_value.upper(), "Standards"
        if key in _LIBRARIES:
            return name, "Libraries"
        if key in _PROGRAMMING_LANGUAGES:
            return name, "Programming Languages"
        if key in _PRODUCTS:
            return name, "Products"
        if key in _LOCATIONS:
            return name, "Locations"
        if key in _FILE_FORMATS:
            return name, "File Formats"
        if key in _TECHNOLOGIES:
            return name, "Technologies"
        if key in _CONCEPTS:
            return name, "Concepts"
        return name, "Other"

    @classmethod
    def _build_definitions(
        cls,
        knowledge_objects: tuple[KnowledgeObject, ...],
        knowledge_by_id: dict[UUID, KnowledgeObject],
    ) -> tuple[ConsolidatedDefinition, ...]:
        """Consolidate reliably parsed definitions and retain opaque definitions."""
        groups: dict[str, _DefinitionAccumulator] = {}
        source_to_keys: dict[UUID, list[str]] = {}
        source_index = 0
        for knowledge_object in knowledge_objects:
            for raw_definition in knowledge_object.definitions:
                concept, definition, key = cls._parse_definition(raw_definition)
                is_opaque = key.startswith("opaque:")
                accumulator = groups.get(key)
                if accumulator is None:
                    accumulator = _DefinitionAccumulator(
                        concept=concept,
                        is_opaque=is_opaque,
                    )
                    groups[key] = accumulator
                accumulator.candidates.append(
                    _DefinitionCandidate(
                        definition=definition,
                        knowledge_object=knowledge_object,
                        source_index=source_index,
                    )
                )
                accumulator.evidence.add_source(knowledge_object)
                source_to_keys.setdefault(knowledge_object.chunk_id, []).append(key)
                source_index += 1

        cls._make_opaque_definition_concepts_unique(groups)
        related_by_key = cls._related_definition_keys(source_to_keys)
        definitions: list[ConsolidatedDefinition] = []
        for key, accumulator in groups.items():
            best = min(
                accumulator.candidates,
                key=cls._definition_quality_key,
            )
            source_ids = tuple(accumulator.evidence.supporting_chunk_ids)
            related_concepts = tuple(
                sorted(
                    (
                        groups[related_key].concept
                        for related_key in related_by_key.get(key, ())
                        if not related_key.startswith("opaque:")
                    ),
                    key=lambda concept: (concept.casefold(), concept),
                )
            )
            definitions.append(
                ConsolidatedDefinition(
                    concept=accumulator.concept,
                    definition=best.definition,
                    related_concepts=related_concepts,
                    supporting_chunk_ids=source_ids,
                    references=tuple(accumulator.evidence.references),
                    confidence=cls._mean_confidence(source_ids, knowledge_by_id),
                )
            )

        return tuple(
            sorted(
                definitions,
                key=lambda definition: (
                    definition.concept.casefold(),
                    definition.concept,
                ),
            )
        )

    @classmethod
    def _parse_definition(cls, raw_definition: str) -> tuple[str, str, str]:
        """Extract a reliable concept or retain one opaque definition unchanged."""
        definition = _normalize_whitespace(raw_definition)
        delimiter_match = re.match(
            r"^(?P<concept>[^:=—]{1,80}?)\s*(?::|=|—|\s-\s)\s*"
            r"(?P<body>.+)$",
            definition,
        )
        relation_match = re.match(
            r"^(?P<concept>.{1,80}?)\s+(?:is|means|refers to|describes)\s+"
            r"(?P<body>.+)$",
            definition,
            flags=re.IGNORECASE,
        )
        match = delimiter_match or relation_match
        if match is None or not cls._is_reliable_definition_concept(
            match.group("concept")
        ):
            digest = sha256(definition.encode("utf-8")).hexdigest()
            concept = cls._opaque_definition_concept(definition)
            return concept, definition, f"opaque:{digest}"

        concept = cls._normalize_definition_concept(match.group("concept"))
        body = _normalize_whitespace(match.group("body"))
        if not body:
            digest = sha256(definition.encode("utf-8")).hexdigest()
            return (
                cls._opaque_definition_concept(definition),
                definition,
                f"opaque:{digest}",
            )
        return concept, body, f"concept:{concept.casefold()}"

    @staticmethod
    def _is_reliable_definition_concept(value: str) -> bool:
        """Require a compact named concept rather than a sentence fragment."""
        concept = _normalize_whitespace(value).strip("-—:=. ")
        key = concept.casefold()
        tokens = _TOKEN_PATTERN.findall(concept)
        return bool(
            concept
            and key not in _RELATION_CONCEPT_EXCLUSIONS
            and 1 <= len(tokens) <= 10
            and not concept.endswith((".", "!", "?"))
        )

    @classmethod
    def _normalize_definition_concept(cls, value: str) -> str:
        """Apply entity alias normalization before definition grouping."""
        normalized = _normalize_whitespace(value).strip("-—:=. ")
        canonical_alias = _DEFINITION_CONCEPT_ALIASES.get(normalized.casefold())
        if canonical_alias is not None:
            return canonical_alias
        canonical, _ = cls._classify_entity(normalized)
        return canonical

    @staticmethod
    def _opaque_definition_concept(definition: str) -> str:
        """Derive a readable deterministic concept label for opaque evidence."""
        candidate = _normalize_whitespace(definition)
        if not candidate:
            return "Unknown Concept"
        candidate = re.split(r"[.!?;]", candidate, maxsplit=1)[0]
        candidate = re.split(r"\s*(?::|=|—|\s-\s)\s*", candidate, maxsplit=1)[0]
        words = tuple(_TOKEN_PATTERN.findall(candidate))
        if not words:
            return "Unknown Concept"
        readable_words = words[:8]
        label = " ".join(readable_words).strip()
        if not label:
            return "Unknown Concept"
        if len(words) > len(readable_words):
            return label + "…"
        return label

    @staticmethod
    def _make_opaque_definition_concepts_unique(
        groups: dict[str, _DefinitionAccumulator],
    ) -> None:
        """Keep opaque display keys separate from every parsed concept label."""
        used_concepts = {
            accumulator.concept.casefold()
            for accumulator in groups.values()
            if not accumulator.is_opaque
        }
        for key, accumulator in groups.items():
            if not accumulator.is_opaque:
                continue
            base = accumulator.concept
            if base.casefold() in used_concepts:
                # A bare or malformed value that repeats a parsed concept is
                # not a meaningful display concept in its own right.
                base = "Unknown Concept"
            candidate = base
            suffix = 2
            while candidate.casefold() in used_concepts:
                candidate = f"{base} ({suffix})"
                suffix += 1
            accumulator.concept = candidate
            used_concepts.add(candidate.casefold())

    @staticmethod
    def _definition_quality_key(
        candidate: _DefinitionCandidate,
    ) -> tuple[int, int, int, float, int]:
        """Prefer complete, evidence-rich definition wording deterministically."""
        definition = candidate.definition.rstrip()
        complete = int(definition.endswith((".", "!", "?")))
        reference_count = len(candidate.knowledge_object.references)
        return (
            -len(definition),
            -complete,
            -reference_count,
            -candidate.knowledge_object.confidence,
            candidate.source_index,
        )

    @staticmethod
    def _related_definition_keys(
        source_to_keys: dict[UUID, list[str]],
    ) -> dict[str, set[str]]:
        """Build bounded co-occurrence edges without quadratic global scans."""
        related: dict[str, set[str]] = {}
        for keys in source_to_keys.values():
            unique_keys = tuple(dict.fromkeys(keys))[:_MAX_RELATED_CONCEPTS_PER_SOURCE]
            for key in unique_keys:
                related.setdefault(key, set()).update(
                    other_key for other_key in unique_keys if other_key != key
                )
        return related

    @classmethod
    def _build_timeline(
        cls,
        knowledge_objects: tuple[KnowledgeObject, ...],
        knowledge_by_id: dict[UUID, KnowledgeObject],
    ) -> tuple[IntelligentTimelineEvent, ...]:
        """Retain source-backed historical milestones in chronological order."""
        events: dict[tuple[str, int], _TimelineAccumulator] = {}
        for knowledge_object in knowledge_objects:
            dates_by_year, specific_dates = cls._timeline_date_index(
                knowledge_object.dates
            )
            if not dates_by_year:
                continue

            for raw_fact in knowledge_object.facts:
                fact = _normalize_whitespace(raw_fact)
                if not fact or not _MILESTONE_PATTERN.search(fact):
                    continue

                for year in _years_in_text(fact):
                    parsed = cls._date_for_fact(
                        fact,
                        year,
                        dates_by_year,
                        specific_dates,
                    )
                    if parsed is None:
                        continue
                    date_text, sort_key = parsed
                    event_key = (cls._normalized_key(fact), sort_key[0])
                    accumulator = events.get(event_key)
                    if accumulator is None:
                        accumulator = _TimelineAccumulator(
                            date_text=date_text,
                            sort_key=sort_key,
                            description=fact,
                        )
                        events[event_key] = accumulator
                    elif _date_specificity(sort_key) > _date_specificity(
                        accumulator.sort_key
                    ):
                        # An exact date or month-year is more useful than the
                        # matching generic year. The event text and evidence
                        # stay canonical; only the derived display date becomes
                        # more specific.
                        accumulator.date_text = date_text
                        accumulator.sort_key = sort_key
                    accumulator.evidence.add_source(knowledge_object)

        timeline = tuple(
            IntelligentTimelineEvent(
                date=accumulator.date_text,
                description=accumulator.description,
                supporting_chunk_ids=tuple(accumulator.evidence.supporting_chunk_ids),
                references=tuple(accumulator.evidence.references),
                confidence=cls._mean_confidence(
                    tuple(accumulator.evidence.supporting_chunk_ids),
                    knowledge_by_id,
                ),
            )
            for accumulator in sorted(
                events.values(),
                key=lambda event: (event.sort_key, cls._normalized_key(event.description)),
            )
        )
        return timeline

    @classmethod
    def _timeline_date_index(
        cls,
        dates: tuple[str, ...],
    ) -> tuple[
        dict[int, tuple[str, tuple[int, int, int, str]]],
        dict[str, tuple[str, tuple[int, int, int, str]]],
    ]:
        """Index supported source dates once, preferring the most specific form."""
        dates_by_year: dict[int, tuple[str, tuple[int, int, int, str]]] = {}
        specific_dates: dict[str, tuple[str, tuple[int, int, int, str]]] = {}
        for raw_date in dates:
            parsed = cls._parse_timeline_date(raw_date)
            if parsed is None:
                continue
            date_text, sort_key = parsed
            year = sort_key[0]
            prior = dates_by_year.get(year)
            if prior is None or _date_specificity(sort_key) > _date_specificity(
                prior[1]
            ):
                dates_by_year[year] = parsed
            if _date_specificity(sort_key) > 1:
                specific_dates.setdefault(date_text.casefold(), parsed)
        return dates_by_year, specific_dates

    @staticmethod
    def _date_for_fact(
        fact: str,
        year: int,
        dates_by_year: dict[int, tuple[str, tuple[int, int, int, str]]],
        specific_dates: dict[str, tuple[str, tuple[int, int, int, str]]],
    ) -> tuple[str, tuple[int, int, int, str]] | None:
        """Choose an exact source date when present, otherwise its best year."""
        for match in _SPECIFIC_DATE_IN_FACT_PATTERN.finditer(fact):
            specific_date = specific_dates.get(
                _normalize_whitespace(match.group(0)).casefold()
            )
            if specific_date is not None and specific_date[1][0] == year:
                return specific_date
        return dates_by_year.get(year)

    @staticmethod
    def _parse_timeline_date(value: str) -> tuple[str, tuple[int, int, int, str]] | None:
        """Parse only date forms that can be sorted without ambiguity."""
        normalized = _normalize_whitespace(value)
        iso_match = _ISO_DATE_PATTERN.fullmatch(normalized)
        if iso_match is not None:
            year = int(iso_match.group("year"))
            month = int(iso_match.group("month"))
            day = int(iso_match.group("day"))
            try:
                date(year, month, day)
            except ValueError:
                return None
            return normalized, (year, month, day, normalized.casefold())

        month_year_match = _MONTH_YEAR_PATTERN.fullmatch(normalized)
        if month_year_match is not None:
            year = int(month_year_match.group("year"))
            month_name = month_year_match.group("month").casefold()
            month = _MONTH_NUMBERS[month_name]
            return (
                f"{month_name.title()} {year}",
                (year, month, 0, normalized.casefold()),
            )

        if _YEAR_PATTERN.fullmatch(normalized):
            year = int(normalized)
            return normalized, (year, 0, 0, normalized)
        return None

    @classmethod
    def _build_findings(
        cls,
        report: EnhancedResearchReport,
        knowledge_by_id: dict[UUID, KnowledgeObject],
        entity_groups: tuple[EntityGroup, ...],
    ) -> tuple[EnrichedFinding, ...]:
        """Attach display metadata to authoritative findings without reordering them."""
        source_findings = (
            tuple(
                ("finding", index, finding)
                for index, finding in enumerate(report.findings)
            )
            + tuple(
                ("appendix", index, finding)
                for index, finding in enumerate(report.appendix_findings)
            )
        )
        prepared = tuple(
            (
                source_kind,
                source_index,
                finding,
                _content_tokens(f"{finding.title} {finding.description}"),
            )
            for source_kind, source_index, finding in source_findings
        )
        token_frequency: Counter[str] = Counter(
            token for _, _, _, tokens in prepared for token in tokens
        )
        summary_tokens = _content_tokens(report.executive_summary)
        entity_frequency = cls._entity_token_frequency(entity_groups)

        enriched: list[EnrichedFinding] = []
        for source_kind, source_index, finding, tokens in prepared:
            source_ids = finding.supporting_chunk_ids
            confidence = cls._mean_confidence(source_ids, knowledge_by_id)
            references = cls._references_for_sources(source_ids, knowledge_by_id)
            score = cls._score_finding(
                confidence=confidence,
                source_count=len(source_ids),
                tokens=tokens,
                token_frequency=token_frequency,
                entity_frequency=entity_frequency,
                summary_tokens=summary_tokens,
            )
            enriched.append(
                EnrichedFinding(
                    source_kind=source_kind,
                    source_index=source_index,
                    title=cls._display_finding_title(finding),
                    summary=finding.description,
                    supporting_chunk_ids=source_ids,
                    references=references,
                    confidence=confidence,
                    importance=score.importance,
                )
            )
        return tuple(enriched)

    @staticmethod
    def _entity_token_frequency(
        entity_groups: tuple[EntityGroup, ...],
    ) -> Counter[str]:
        """Count source-backed canonical entity tokens for importance signals."""
        return Counter(
            token
            for group in entity_groups
            for entity in group.entities
            for _ in entity.supporting_chunk_ids
            for token in _content_tokens(entity.name)
        )

    @staticmethod
    def _score_finding(
        *,
        confidence: float,
        source_count: int,
        tokens: frozenset[str],
        token_frequency: Counter[str],
        entity_frequency: Counter[str],
        summary_tokens: frozenset[str],
    ) -> _FindingScore:
        """Compute a private fixed-weight score and its visible importance band."""
        confidence_points = _round_half_up(confidence * 40)
        citation_points = min(20, source_count * 5)
        entity_signal = sum(entity_frequency.get(token, 0) for token in tokens)
        entity_points = _round_half_up(15 * min(1.0, entity_signal / 5.0))
        shared_tokens = sum(
            max(0, token_frequency.get(token, 0) - 1) for token in tokens
        )
        centrality_points = _round_half_up(
            15 * min(1.0, shared_tokens / max(1, len(tokens)))
        )
        summary_overlap = len(tokens.intersection(summary_tokens)) / max(1, len(tokens))
        summary_points = _round_half_up(10 * summary_overlap)
        value = min(
            100,
            confidence_points
            + citation_points
            + entity_points
            + centrality_points
            + summary_points,
        )
        importance: Importance
        if value >= 70:
            importance = "HIGH"
        elif value >= 40:
            importance = "MEDIUM"
        else:
            importance = "LOW"
        return _FindingScore(value=value, importance=importance)

    @staticmethod
    def _display_finding_title(finding: Finding) -> str:
        """Shorten only titles that repeat their authoritative source sentence."""
        if _normalized_text(finding.title) != _normalized_text(finding.description):
            return finding.title
        sentence = _SENTENCE_END_PATTERN.split(finding.description.strip(), maxsplit=1)[0]
        words = sentence.rstrip(".?! ").split()
        if len(words) <= 8:
            return " ".join(words) or finding.title
        return " ".join(words[:8]) + "…"

    @staticmethod
    def _used_chunk_ids(
        entity_groups: tuple[EntityGroup, ...],
        definitions: tuple[ConsolidatedDefinition, ...],
        timeline: tuple[IntelligentTimelineEvent, ...],
        findings: tuple[EnrichedFinding, ...],
    ) -> tuple[UUID, ...]:
        """Return all retained source IDs in deterministic first-seen order."""
        used: list[UUID] = []
        seen: set[UUID] = set()

        def add(source_ids: tuple[UUID, ...]) -> None:
            for chunk_id in source_ids:
                if chunk_id not in seen:
                    seen.add(chunk_id)
                    used.append(chunk_id)

        for group in entity_groups:
            for entity in group.entities:
                add(entity.supporting_chunk_ids)
        for definition in definitions:
            add(definition.supporting_chunk_ids)
        for event in timeline:
            add(event.supporting_chunk_ids)
        for finding in findings:
            add(finding.supporting_chunk_ids)
        return tuple(used)

    @staticmethod
    def _build_references(
        knowledge_objects: tuple[KnowledgeObject, ...],
        used_chunk_ids: tuple[UUID, ...],
    ) -> tuple[ConsolidatedReference, ...]:
        """Consolidate only references backed by retained intelligence evidence."""
        used = set(used_chunk_ids)
        references: dict[str, tuple[str, list[UUID], set[UUID]]] = {}
        for knowledge_object in knowledge_objects:
            if knowledge_object.chunk_id not in used:
                continue
            for raw_reference in knowledge_object.references:
                reference = _normalize_reference(raw_reference)
                if not reference:
                    continue
                key = reference.casefold()
                current = references.get(key)
                if current is None:
                    source_ids: list[UUID] = []
                    seen_source_ids: set[UUID] = set()
                    references[key] = (reference, source_ids, seen_source_ids)
                    current = references[key]
                _, source_ids, seen_source_ids = current
                if knowledge_object.chunk_id not in seen_source_ids:
                    seen_source_ids.add(knowledge_object.chunk_id)
                    source_ids.append(knowledge_object.chunk_id)

        return tuple(
            ConsolidatedReference(
                reference=reference,
                supporting_chunk_ids=tuple(source_ids),
            )
            for reference, source_ids, _ in sorted(
                references.values(),
                key=lambda item: (item[0].casefold(), item[0]),
            )
        )

    @staticmethod
    def _mean_confidence(
        source_ids: tuple[UUID, ...],
        knowledge_by_id: dict[UUID, KnowledgeObject],
    ) -> float:
        """Return an exact mean source confidence for one retained item."""
        confidences = tuple(knowledge_by_id[source_id].confidence for source_id in source_ids)
        return sum(confidences) / len(confidences) if confidences else 0.0

    @staticmethod
    def _references_for_sources(
        source_ids: tuple[UUID, ...],
        knowledge_by_id: dict[UUID, KnowledgeObject],
    ) -> tuple[str, ...]:
        """Union source references in support-ID order without copying text twice."""
        references: list[str] = []
        seen: set[str] = set()
        for source_id in source_ids:
            for raw_reference in knowledge_by_id[source_id].references:
                reference = _normalize_reference(raw_reference)
                key = reference.casefold()
                if reference and key not in seen:
                    seen.add(key)
                    references.append(reference)
        return tuple(references)

    @staticmethod
    def _normalized_key(value: str) -> str:
        """Return a compact case-insensitive key for deterministic deduplication."""
        return _normalize_whitespace(value).casefold()


def _normalize_whitespace(value: str) -> str:
    """Collapse arbitrary whitespace without changing meaningful source wording."""
    return _SPACE_PATTERN.sub(" ", value).strip()


def _normalize_reference(value: str) -> str:
    """Normalize citation text and safe HTTP(S) URL variations deterministically."""
    normalized = _normalize_whitespace(value)
    if not normalized:
        return ""
    try:
        parsed = urlsplit(normalized)
    except ValueError:
        return normalized
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
        return normalized
    try:
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return normalized
    if hostname is None:
        return normalized

    host = hostname.casefold()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    userinfo = ""
    if "@" in parsed.netloc:
        userinfo = parsed.netloc.rsplit("@", maxsplit=1)[0] + "@"
    include_port = port is not None and not (
        (parsed.scheme.casefold() == "http" and port == 80)
        or (parsed.scheme.casefold() == "https" and port == 443)
    )
    netloc = userinfo + host + (f":{port}" if include_port else "")
    path = parsed.path
    if path == "/":
        path = ""
    query = urlencode(
        tuple(
            (name, item)
            for name, item in parse_qsl(parsed.query, keep_blank_values=True)
            if not _is_tracking_query_parameter(name)
        ),
        doseq=True,
    )
    return urlunsplit(
        (parsed.scheme.casefold(), netloc, path, query, parsed.fragment)
    )


def _is_tracking_query_parameter(name: str) -> bool:
    """Recognize only well-known non-semantic URL tracking parameters."""
    normalized = name.casefold()
    return normalized.startswith("utm_") or normalized in _TRACKING_QUERY_PARAMETERS


def _normalized_text(value: str) -> str:
    """Normalize lexical text for equality without changing rendered evidence."""
    return " ".join(_TOKEN_PATTERN.findall(value.casefold()))


def _content_tokens(value: str) -> frozenset[str]:
    """Return cached-quality lexical tokens with common stop words removed."""
    return frozenset(
        token
        for token in _TOKEN_PATTERN.findall(value.casefold())
        if token and token not in _STOP_WORDS
    )


def _years_in_text(value: str) -> tuple[int, ...]:
    """Return date years in source order without repeated fact/date scans."""
    return tuple(
        dict.fromkeys(
            int(match.group("year"))
            for match in _YEAR_IN_TEXT_PATTERN.finditer(value)
        )
    )


def _date_specificity(sort_key: tuple[int, int, int, str]) -> int:
    """Rank parsed dates so duplicate milestones retain the best source date."""
    _, month, day, _ = sort_key
    if day:
        return 3
    if month:
        return 2
    return 1


def _round_half_up(value: float) -> int:
    """Produce stable non-banker rounding for deterministic score thresholds."""
    return int(math.floor(value + 0.5))
