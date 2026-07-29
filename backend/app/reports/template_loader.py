"""Private Jinja helpers for standalone PaperForge HTML reports."""

from functools import lru_cache
from pathlib import Path

from jinja2 import (
    Environment,
    FileSystemLoader,
    StrictUndefined,
    Template,
    TemplateError,
    TemplateNotFound,
    select_autoescape,
)

from app.reports.exceptions import ReportRenderingError

_TEMPLATE_DIRECTORY = (
    Path(__file__).resolve().parent.parent / "templates" / "html"
)


@lru_cache(maxsize=1)
def get_html_template_environment() -> Environment:
    """Create the cached, deterministic Jinja environment for report templates."""
    try:
        if not _TEMPLATE_DIRECTORY.is_dir():
            raise FileNotFoundError(
                "The PaperForge HTML template directory is unavailable."
            )

        return Environment(
            loader=FileSystemLoader(str(_TEMPLATE_DIRECTORY), encoding="utf-8"),
            autoescape=select_autoescape(
                enabled_extensions=("html", "xml", "j2"),
                default_for_string=True,
            ),
            undefined=StrictUndefined,
            auto_reload=False,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
            newline_sequence="\n",
        )
    except OSError as exc:
        raise ReportRenderingError(
            "Unable to initialize the HTML report templates."
        ) from exc


def get_html_template(template_name: str) -> Template:
    """Load one named report template while hiding filesystem implementation details."""
    _validate_resource_name(template_name, "template")

    try:
        return get_html_template_environment().get_template(template_name)
    except (OSError, TemplateNotFound, TemplateError) as exc:
        raise ReportRenderingError("Unable to load the HTML report template.") from exc


def load_html_asset(asset_name: str) -> str:
    """Return a UTF-8 static report asset from the package-local template tree."""
    _validate_resource_name(asset_name, "asset")
    asset_path = _TEMPLATE_DIRECTORY / "assets" / asset_name

    try:
        return asset_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ReportRenderingError("Unable to load the HTML report asset.") from exc


def _validate_resource_name(resource_name: object, resource_type: str) -> None:
    """Prevent templates or assets from resolving outside the report package."""
    if not isinstance(resource_name, str) or not resource_name:
        raise ReportRenderingError(f"HTML {resource_type} name must be non-empty text.")

    resource_path = Path(resource_name)
    if resource_path.is_absolute() or len(resource_path.parts) != 1:
        raise ReportRenderingError(f"Invalid HTML {resource_type} name.")
