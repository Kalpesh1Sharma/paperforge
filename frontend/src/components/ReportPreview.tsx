import { useEffect, useState } from "react";
import { ExternalIcon, RefreshIcon } from "./Icons";

type Props = { reportId: string; anchor: string | null; title: string; artifactRevision?: number };

export function ReportPreview({ reportId, anchor, title, artifactRevision = 0 }: Props) {
  const base = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";
  const htmlUrl = `${base}/reports/${reportId}/html`;
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const versionedUrl = artifactRevision > 1 ? `${htmlUrl}?revision=${artifactRevision}` : htmlUrl;
  const src = `${versionedUrl}${anchor ? `#${encodeURIComponent(anchor)}` : ""}`;

  useEffect(() => { setLoading(true); setFailed(false); }, [src, revision]);

  return <section className="preview workspace-preview">
    <div className="preview-toolbar">
      <div><span className="eyebrow">Publication preview</span><h2>{title}</h2></div>
      <div className="preview-actions">
        <button type="button" title="Reload preview" aria-label="Reload preview" onClick={() => setRevision((value) => value + 1)}><RefreshIcon /></button>
        <a href={htmlUrl} target="_blank" rel="noopener noreferrer"><ExternalIcon /> Open full page</a>
      </div>
    </div>
    <div className="preview-frame">
      {loading && !failed && <div className="preview-loading" role="status"><i /><span>Loading publication preview…</span></div>}
      {failed && <div className="preview-failure" role="alert"><strong>Preview unavailable</strong><p>The saved report is still available through the export controls.</p><button className="secondary" onClick={() => setRevision((value) => value + 1)}>Try again</button></div>}
      <iframe key={`${src}-${revision}`} title="PaperForge report preview" src={src} onLoad={() => setLoading(false)} onError={() => { setLoading(false); setFailed(true); }} />
    </div>
  </section>;
}
