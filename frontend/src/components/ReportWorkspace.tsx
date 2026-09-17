import { useEffect, useState } from "react";
import { api, PaperForgeApiError, reportUrl } from "../api/client";
import type { ReportEditingState, ReportMetadata, ReportPresentation, ReviewState, VisualTemplate } from "../api/types";
import { DownloadIcon, FileIcon, RefreshIcon } from "./Icons";
import { ReportPreview } from "./ReportPreview";
import { ReportEditor } from "./ReportEditor";
import { ReviewPanel } from "./ReviewPanel";

type Props = { id: string; metadata: ReportMetadata; review: ReviewState | null; busy: boolean; onStart: () => void; onApprove: (id: string) => void; onReject: (id: string, feedback?: string) => void; onRefresh: () => void; onNewReport: () => void; onRegenerate: () => void; onBack: () => void };

const titleCase = (value: string) => value.split("-").map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(" ");

export function ReportWorkspace({ id, metadata, review, busy, onStart, onApprove, onReject, onRefresh, onNewReport, onRegenerate, onBack }: Props) {
  const sources = metadata.documents ?? (metadata.document ? [metadata.document] : []);
  const [presentation, setPresentation] = useState<ReportPresentation | null>(null);
  const [presentationError, setPresentationError] = useState<string | null>(null);
  const [activeAnchor, setActiveAnchor] = useState<string | null>(null);
  const [confirmRegenerate, setConfirmRegenerate] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [artifactRevision, setArtifactRevision] = useState(1);
  const [editingTemplate, setEditingTemplate] = useState<VisualTemplate | null>(null);
  const savedSettings = metadata.settings;
  const versionTwoSettings = savedSettings && "schema_version" in savedSettings ? savedSettings : null;
  const legacySettings = savedSettings && "structure" in savedSettings ? savedSettings : null;

  useEffect(() => {
    let active = true;
    setPresentation(null);
    setPresentationError(null);
    setActiveAnchor(null);
    api.presentation(id).then((value) => {
      if (active) setPresentation(value);
    }).catch((caught) => {
      if (active) setPresentationError(caught instanceof PaperForgeApiError ? caught.message : "Report navigation could not be loaded.");
    });
    return () => { active = false; };
  }, [id, artifactRevision]);

  const reportTitle = versionTwoSettings?.publication.title ?? legacySettings?.report_title ?? presentation?.cover.title ?? "Grounded report";
  const generatedOn = presentation?.cover.generated_on ? new Date(`${presentation.cover.generated_on}T00:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "Date unavailable";
  const confidence = presentation?.cover.mean_confidence == null ? null : Math.round(presentation.cover.mean_confidence * 100);

  return <main className="workspace-page page-enter">
    <header className="workspace-header">
      <div><button aria-label="Back to projects" className="workspace-back" onClick={onBack}>Projects</button><span aria-hidden="true">/</span><span>Report workspace</span><h1>{reportTitle}</h1><p>{savedSettings?.research_domain ?? presentation?.cover.domain ?? "Research report"} · {sources.length} {sources.length === 1 ? "source" : "sources"}</p></div>
      <div className="workspace-header-actions"><span className="ready-pill"><i /> Report ready</span><button className="button button-primary" onClick={() => setEditorOpen(true)}>Edit report</button><button className="button button-quiet" onClick={onNewReport}>New report</button></div>
    </header>

    <div className="workspace-grid">
      <aside className="workspace-outline">
        <div className="panel-heading"><span className="eyebrow">Document outline</span><strong>{presentation?.table_of_contents.entries.length ?? 0} sections</strong></div>
        {presentationError ? <div className="panel-error" role="alert"><strong>Outline unavailable</strong><small>{presentationError}</small></div> : !presentation ? <div className="outline-loading"><i /><i /><i /><i /></div> : <nav aria-label="Report sections"><button className={activeAnchor === null ? "active" : ""} onClick={() => setActiveAnchor(null)}><span>00</span>Cover</button>{presentation.table_of_contents.entries.map((entry, index) => <button className={activeAnchor === entry.anchor_id ? "active" : ""} key={entry.anchor_id} onClick={() => setActiveAnchor(entry.anchor_id)}><span>{String(index + 1).padStart(2, "0")}</span>{entry.heading}</button>)}</nav>}
        {confidence !== null && <div className="workspace-confidence"><div><span>Evidence confidence</span><strong>{confidence}%</strong></div><i><b style={{ width: `${confidence}%` }} /></i></div>}
      </aside>

      <ReportPreview reportId={id} anchor={activeAnchor} title={reportTitle} artifactRevision={artifactRevision} />

      <aside className="workspace-inspector">
        <section>
          <div className="panel-heading"><span className="eyebrow">Evidence inputs</span><strong>{sources.length}</strong></div>
          <div className="source-list">{sources.map((source, index) => <article className="workspace-source" key={`${source.filename}-${index}`}><span><FileIcon /></span><div><strong>{source.filename}</strong><small>{source.page_count ? `${source.page_count} pages · ` : ""}{source.word_count.toLocaleString()} words</small><em>Source {index + 1}</em></div></article>)}</div>
          <p className="source-note">Findings retain source-level provenance inside the report.</p>
        </section>

        <section>
          <div className="panel-heading"><span className="eyebrow">Export report</span><strong>{metadata.available_formats.length - (metadata.available_formats.includes("json") ? 1 : 0)} formats</strong></div>
          <div className="workspace-downloads"><a href={reportUrl(id, "pdf")} target="_blank" rel="noopener noreferrer"><DownloadIcon /><span><strong>PDF document</strong><small>Publication-ready</small></span></a><a href={reportUrl(id, "editable-docx")} target="_blank" rel="noopener noreferrer"><DownloadIcon /><span><strong>Editable DOCX</strong><small>Normal Word document</small></span></a><a href={reportUrl(id, "markdown")} target="_blank" rel="noopener noreferrer"><DownloadIcon /><span><strong>Markdown</strong><small>Editable source</small></span></a><a href={reportUrl(id, "html")} target="_blank" rel="noopener noreferrer"><DownloadIcon /><span><strong>HTML page</strong><small>Standalone report</small></span></a></div>
        </section>

        {presentation?.quality && <section className={`quality-panel quality-${presentation.quality.status}`}><div className="panel-heading"><span className="eyebrow">Quality checks</span><strong>{presentation.quality.status === "passed" ? "Passed" : `${presentation.quality.issues.length} ${presentation.quality.issues.length === 1 ? "issue" : "issues"}`}</strong></div><p>{presentation.quality.supported_claims} of {presentation.quality.checked_claims} checked claims link to source evidence.</p>{presentation.quality.issues.length > 0 && <ul>{presentation.quality.issues.slice(0, 5).map((issue, index) => <li key={`${issue.code}-${issue.section_key ?? "report"}-${index}`}><b>{titleCase(issue.code)}</b><span>{issue.message}</span></li>)}</ul>}</section>}

        <section className="version-panel">
          <div className="panel-heading"><span className="eyebrow">Version information</span><strong>v{presentation?.revision ?? artifactRevision}</strong></div>
          <dl><div><dt>Created</dt><dd>{generatedOn}</dd></div><div><dt>Structure</dt><dd>{titleCase(versionTwoSettings?.report_structure.preset ?? legacySettings?.structure ?? presentation?.mode ?? "professional")}</dd></div><div><dt>Template</dt><dd>{titleCase(editingTemplate ?? versionTwoSettings?.visual_theme.template ?? legacySettings?.visual_template ?? presentation?.template_key ?? "paperforge-classic")}</dd></div><div><dt>Citations</dt><dd>{titleCase(versionTwoSettings?.citations.style ?? presentation?.citation_style ?? "source-linked")}</dd></div><div><dt>Synthesis</dt><dd>{metadata.generation.provider}{metadata.generation.model ? ` · ${metadata.generation.model}` : ""}</dd></div><div><dt>Report ID</dt><dd title={id}>{id.slice(0, 8)}…</dd></div></dl>
          {!confirmRegenerate ? <button className="regenerate-button" disabled={busy} onClick={() => setConfirmRegenerate(true)}><RefreshIcon /> Regenerate from saved sources</button> : <div className="regenerate-confirm"><p>This creates a new report. The current version stays unchanged.</p><div><button className="secondary" onClick={() => setConfirmRegenerate(false)}>Cancel</button><button className="primary" disabled={busy} onClick={onRegenerate}>{busy ? "Starting…" : "Regenerate"}</button></div></div>}
        </section>

        <section><ReviewPanel review={review} busy={busy} onStart={onStart} onApprove={onApprove} onReject={onReject} onRefresh={onRefresh} docxUrl={reportUrl(id, "docx")} /></section>
      </aside>
    </div>
    <ReportEditor reportId={id} open={editorOpen} onClose={() => setEditorOpen(false)} onChanged={(next: ReportEditingState) => { setArtifactRevision(next.revision); setEditingTemplate(next.template_key); }} />
  </main>;
}
