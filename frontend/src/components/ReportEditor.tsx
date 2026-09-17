import { useEffect, useState } from "react";
import { api, PaperForgeApiError } from "../api/client";
import type { ReportEditingState, ReportTransformAction, VisualTemplate } from "../api/types";

type Props = {
  reportId: string;
  open: boolean;
  onClose: () => void;
  onChanged: (state: ReportEditingState) => void;
};

const templates: Array<{ key: VisualTemplate; label: string }> = [
  { key: "paperforge-classic", label: "Classic Academic" },
  { key: "modern-research", label: "Modern Research" },
  { key: "ieee-inspired-technical", label: "IEEE-Inspired Technical" },
];

export function ReportEditor({ reportId, open, onClose, onChanged }: Props) {
  const [state, setState] = useState<ReportEditingState | null>(null);
  const [selectedKey, setSelectedKey] = useState("");
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let active = true;
    setError(null);
    api.editingState(reportId).then((value) => {
      if (!active) return;
      setState(value);
      const first = value.sections[0];
      setSelectedKey((current) => value.sections.some((section) => section.key === current) ? current : first.key);
    }).catch((caught) => {
      if (active) setError(caught instanceof PaperForgeApiError ? caught.message : "The report editor could not be loaded.");
    });
    return () => { active = false; };
  }, [open, reportId]);

  const selected = state?.sections.find((section) => section.key === selectedKey) ?? null;
  useEffect(() => { if (selected) setDraft(selected.content); }, [selected?.key, selected?.content]);

  const apply = (next: ReportEditingState, message: string) => {
    setState(next);
    setNotice(message);
    setError(null);
    onChanged(next);
  };

  const run = async (work: () => Promise<ReportEditingState>, message: string) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try { apply(await work(), message); }
    catch (caught) { setError(caught instanceof PaperForgeApiError ? caught.message : "PaperForge could not save that change."); }
    finally { setBusy(false); }
  };

  if (!open) return null;
  return <div className="report-editor-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose(); }}>
    <section className="report-editor" role="dialog" aria-modal="true" aria-labelledby="report-editor-title">
      <header><div><span className="eyebrow">Report editing</span><h2 id="report-editor-title">Shape the finished report</h2><p>Revision {state?.revision ?? "…"}. Content changes rerender exports without rereading your sources.</p></div><button type="button" className="editor-close" disabled={busy} onClick={onClose} aria-label="Close report editor">×</button></header>
      {error && <div className="editor-alert editor-alert-error" role="alert">{error}</div>}
      {notice && <div className="editor-alert editor-alert-success" role="status">{notice}</div>}
      {!state ? <div className="editor-loading" role="status">Loading report sections…</div> : <>
        <div className="editor-template"><label htmlFor="editor-template">Visual template</label><select id="editor-template" value={state.template_key} disabled={busy} onChange={(event) => void run(() => api.switchTemplate(reportId, event.target.value as VisualTemplate), "Template switched. Report content was preserved.")}>{templates.map((template) => <option key={template.key} value={template.key}>{template.label}</option>)}</select></div>
        <div className="editor-layout">
          <nav aria-label="Editable report sections">{state.sections.map((section, index) => <button type="button" key={section.key} className={selectedKey === section.key ? "active" : ""} onClick={() => setSelectedKey(section.key)}><span>{String(index + 1).padStart(2, "0")}</span><strong>{section.heading}</strong><small>{section.locked ? "Locked" : section.edited ? "Edited" : "Generated"}</small></button>)}</nav>
          {selected && <div className="editor-workspace">
            <div className="editor-section-heading"><div><label htmlFor="section-content">{selected.heading}</label><small>{selected.locked ? "Approved and protected from changes" : "Edit directly or use an assisted action"}</small></div><button type="button" className={selected.locked ? "editor-lock locked" : "editor-lock"} disabled={busy} onClick={() => void run(() => api.setSectionLock(reportId, selected.key, !selected.locked), selected.locked ? "Section unlocked." : "Section locked and approved.")}>{selected.locked ? "Unlock section" : "Lock section"}</button></div>
            <textarea id="section-content" value={draft} disabled={busy || selected.locked} onChange={(event) => setDraft(event.target.value)} />
            <div className="editor-actions"><div>{(["rewrite", "shorten", "expand"] as ReportTransformAction[]).map((action) => <button type="button" className="secondary" key={action} disabled={busy || selected.locked} onClick={() => void run(() => api.transformSection(reportId, selected.key, action), `${action.charAt(0).toUpperCase() + action.slice(1)} complete.`)}>{action.charAt(0).toUpperCase() + action.slice(1)}</button>)}</div><button type="button" className="primary" disabled={busy || selected.locked || !draft.trim() || draft.trim() === selected.content} onClick={() => void run(() => api.editSection(reportId, selected.key, draft), "Section saved and exports updated.")}>{busy ? "Saving…" : "Save section"}</button></div>
            {state.last_transform && <p className="editor-provider">Last assisted edit: {state.last_transform.provider}{state.last_transform.fallback ? " fallback" : ""}</p>}
          </div>}
        </div>
      </>}
    </section>
  </div>;
}
