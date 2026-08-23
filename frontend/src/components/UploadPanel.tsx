import { useRef, useState } from "react";
import { readableSize, validPdf } from "../utils/files";

type Props = { files: File[]; onChange: (files: File[]) => void; onGenerate: () => void; busy: boolean };
export function UploadPanel({ files, onChange, onGenerate, busy }: Props) {
  const input = useRef<HTMLInputElement>(null); const [notice, setNotice] = useState<string>("");
  const add = (incoming: FileList | File[]) => {
    const next = [...files]; for (const file of Array.from(incoming)) {
      if (!validPdf(file)) { setNotice("Only PDF files can be selected."); continue; }
      if (next.some((item) => item.name.toLowerCase() === file.name.toLowerCase())) { setNotice(`Duplicate filename: ${file.name}`); continue; }
      if (next.length === 5) { setNotice("You can upload a maximum of five PDFs."); break; } next.push(file);
    } onChange(next);
  };
  return <section className="upload-card"><span className="eyebrow">New research report</span><h1>Turn source documents into a grounded research report.</h1><p>Upload up to five PDFs. PaperForge keeps source provenance visible and lets you review consequential edits before they are committed.</p>
    <button className="dropzone" type="button" onClick={() => input.current?.click()} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); add(event.dataTransfer.files); }} aria-label="Choose PDF files"><strong>Drop PDFs here</strong><span>or browse your computer</span></button>
    <input ref={input} hidden aria-label="PDF files input" type="file" accept="application/pdf,.pdf" multiple onChange={(event) => event.target.files && add(event.target.files)} />
    {notice && <p className="notice" role="status">{notice}</p>}
    {files.length > 0 && <div className="selected-files"><div className="row"><strong>{files.length} selected</strong><button className="text-button" onClick={() => onChange([])} type="button">Clear all</button></div>{files.map((file, index) => <div className="file-row" key={`${file.name}-${index}`}><span>{file.name}</span><small>{readableSize(file.size)}</small><button aria-label={`Remove ${file.name}`} onClick={() => onChange(files.filter((_, current) => current !== index))}>Remove</button></div>)}</div>}
    <button className="primary" type="button" disabled={busy || files.length === 0} onClick={onGenerate}>{busy ? "Generating report…" : "Generate Report"}</button>
  </section>;
}
