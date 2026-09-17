"""Safe registry for report-format assets and compatibility aliases."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ReportTemplate:
    key: str
    name: str
    asset: str


_TEMPLATES = {
    "paperforge-classic": ReportTemplate(
        "paperforge-classic", "Classic Academic", "classic-academic.css"
    ),
    "modern-research": ReportTemplate(
        "modern-research", "Modern Research", "modern-research.css"
    ),
    "ieee-inspired-technical": ReportTemplate(
        "ieee-inspired-technical",
        "IEEE-Inspired Technical",
        "ieee-inspired-technical.css",
    ),
    # Stored Phase 1 reports remain renderable through explicit aliases.
    "editorial": ReportTemplate("editorial", "Editorial", "classic-academic.css"),
    "minimal": ReportTemplate("minimal", "Minimal", "modern-research.css"),
}


def get_report_template(key: str) -> ReportTemplate:
    """Resolve only registered assets; never accept a filesystem path."""
    return _TEMPLATES.get(key, _TEMPLATES["paperforge-classic"])
