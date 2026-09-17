"""Create, persist, edit, approve, and validate report outlines."""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import anyio
from fastapi import UploadFile

from app.models.parsed_document import ParsedDocument
from app.outlines.models import EvidenceAvailability, OutlineProposal, OutlineSection
from app.parsers import ParserFactory
from app.parsers.base import DocumentParsingError
from app.reports.generation_settings import (
    ReportGenerationSettings,
    ReportSectionConfiguration,
)
from app.reports.presentation_models import PRESENTATION_SECTION_SPECS
from app.services.report_service import InvalidReportUploadError
from app.services.upload_service import UploadService, UploadValidationError

_KEYWORDS: dict[str, tuple[str, ...]] = {
    "abstract": (),
    "document-overview": (),
    "research-methodology": ("method", "methodology", "approach", "sample", "procedure", "dataset"),
    "executive-summary": ("recommend", "priority", "decision", "conclusion", "impact"),
    "key-insights": ("finding", "result", "show", "indicate", "outcome", "conclude"),
    "technical-analysis": ("architecture", "system", "implementation", "algorithm", "model", "performance", "api"),
    "historical-timeline": ("history", "historical", "timeline", "year", "evolution", "developed"),
    "important-concepts": ("definition", "defined", "concept", "means", "terminology"),
    "evidence-summary": ("evidence", "source", "study", "data", "reference"),
    "appendix": (),
}


class OutlineService:
    """Evidence scan and durable approval boundary for schema-v2 reports."""

    def __init__(self, root_dir: Path, upload_service: UploadService) -> None:
        self._root_dir = Path(root_dir)
        self._proposal_dir = self._root_dir / "outline-proposals"
        self._upload_service = upload_service

    async def create(
        self,
        files: list[UploadFile],
        settings: ReportGenerationSettings,
    ) -> OutlineProposal:
        if not 1 <= len(files) <= 5:
            raise InvalidReportUploadError("Choose between one and five PDF sources.")
        if any(Path(file.filename or "").suffix.lower() != ".pdf" for file in files):
            raise InvalidReportUploadError("Outline proposals require PDF sources.")

        proposal_id = uuid4()
        try:
            upload = await self._upload_service.save_files(files, proposal_id)
        except UploadValidationError as exc:
            raise InvalidReportUploadError(str(exc)) from exc
        source_dir = self._root_dir / str(proposal_id)
        try:
            paths = tuple(sorted(source_dir.iterdir()))
            try:
                parsed_documents: list[ParsedDocument] = []
                for path in paths:
                    parsed_documents.append(
                        await anyio.to_thread.run_sync(ParserFactory.parse, path)
                    )
                documents = tuple(parsed_documents)
            except DocumentParsingError as exc:
                raise InvalidReportUploadError(
                    "A source PDF could not be scanned for outline evidence."
                ) from exc
            filenames = tuple(item.filename for item in upload.files)
            documents = tuple(
                document.model_copy(update={"filename": filename})
                for document, filename in zip(documents, filenames, strict=True)
            )
            proposal = self._build(proposal_id, filenames, documents, settings)
            await anyio.to_thread.run_sync(self._save, proposal)
            return proposal
        finally:
            await anyio.to_thread.run_sync(
                lambda: shutil.rmtree(source_dir, ignore_errors=True)
            )

    def approve(
        self,
        proposal_id: UUID,
        sections: tuple[ReportSectionConfiguration, ...],
    ) -> OutlineProposal:
        proposal = self.get(proposal_id)
        keys = [section.key for section in sections]
        if not sections or len(keys) != len(set(keys)):
            raise InvalidReportUploadError(
                "An approved outline needs at least one unique section."
            )
        catalog = {item.key: item for item in proposal.catalog}
        if any(section.key not in catalog for section in sections):
            raise InvalidReportUploadError("The outline contains an unknown section.")
        now = self._now()
        approved = proposal.model_copy(
            update={
                "status": "approved",
                "revision": proposal.revision + 1,
                "sections": tuple(
                    OutlineSection(
                        key=section.key,
                        heading=section.heading,
                        evidence=catalog[section.key],
                    )
                    for section in sections
                ),
                "updated_at": now,
                "approved_at": now,
            }
        )
        self._save(approved)
        return approved

    def get(self, proposal_id: UUID) -> OutlineProposal:
        try:
            return OutlineProposal.model_validate_json(
                self._path(proposal_id).read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise InvalidReportUploadError("The outline proposal was not found.") from exc

    def assert_generation_allowed(self, settings: ReportGenerationSettings | None) -> None:
        if settings is None:
            return
        approval = settings.outline_approval
        # Stored Phase 1/early Phase 2 reports have no proposal id and remain reusable.
        if approval.proposal_id is None:
            if approval.approved:
                return
            raise InvalidReportUploadError("Approve the proposed outline before generation.")
        try:
            proposal_id = UUID(approval.proposal_id)
        except ValueError as exc:
            raise InvalidReportUploadError("The outline approval is invalid.") from exc
        proposal = self.get(proposal_id)
        requested = tuple(
            (section.key, section.heading) for section in settings.report_structure.sections
        )
        approved = tuple((section.key, section.heading) for section in proposal.sections)
        if (
            not approval.approved
            or proposal.status != "approved"
            or approval.revision != proposal.revision
            or requested != approved
        ):
            raise InvalidReportUploadError(
                "The report outline changed after approval. Review and approve it again."
            )

    def _build(
        self,
        proposal_id: UUID,
        filenames: tuple[str, ...],
        documents: tuple[ParsedDocument, ...],
        settings: ReportGenerationSettings,
    ) -> OutlineProposal:
        texts = tuple(document.extracted_text.lower() for document in documents)
        total_words = sum(document.word_count for document in documents)
        catalog: list[EvidenceAvailability] = []
        for key, heading, _anchor in PRESENTATION_SECTION_SPECS:
            keywords = _KEYWORDS[key]
            if keywords:
                counts = tuple(
                    sum(len(re.findall(rf"\b{re.escape(word)}\w*\b", text)) for word in keywords)
                    for text in texts
                )
                evidence_count = sum(counts)
                source_count = sum(count > 0 for count in counts)
            else:
                evidence_count = max(1, total_words // 250)
                source_count = len(documents)
            level = (
                "strong"
                if source_count >= 2 or evidence_count >= 6
                else "moderate"
                if evidence_count >= 2
                else "limited"
            )
            catalog.append(
                EvidenceAvailability(
                    key=key,
                    heading=heading,
                    level=level,
                    evidence_count=evidence_count,
                    source_count=source_count,
                    reason=(
                        f"{evidence_count} relevant signals across {source_count} source"
                        f"{'s' if source_count != 1 else ''}."
                    ),
                )
            )
        by_key = {item.key: item for item in catalog}
        selected = tuple(
            OutlineSection(
                key=section.key,
                heading=section.heading,
                evidence=by_key[section.key],
            )
            for section in settings.report_structure.sections
        )
        now = self._now()
        return OutlineProposal(
            proposal_id=proposal_id,
            status="draft",
            revision=1,
            source_filenames=filenames,
            sections=selected,
            catalog=tuple(catalog),
            created_at=now,
            updated_at=now,
        )

    def _save(self, proposal: OutlineProposal) -> None:
        self._proposal_dir.mkdir(parents=True, exist_ok=True)
        destination = self._path(proposal.proposal_id)
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(proposal.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(destination)

    def _path(self, proposal_id: UUID) -> Path:
        return self._proposal_dir / f"{proposal_id}.json"

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)
