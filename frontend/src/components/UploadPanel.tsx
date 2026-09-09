import { useRef, useState } from "react";
import { readableSize, validPdf } from "../utils/files";
import { FileIcon, PlusIcon, SparkIcon } from "./Icons";

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
  return <section className="upload-card"><div className="upload-heading"><span className="step-number">01</span><div><span className="page-kicker">SOURCE MATERIAL</span><h1>Add your research documents</h1><p>Choose up to five PDFs. Their order will be preserved throughout the report.</p></div></div>
    <button className="dropzone" type="button" onClick={() => input.current?.click()} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); add(event.dataTransfer.files); }} aria-label="Choose PDF files"><span className="drop-icon"><PlusIcon /></span><strong>Drop your PDFs here</strong><span>or click to browse · PDF up to 50 MB each</span></button>
    <input ref={input} hidden aria-label="PDF files input" type="file" accept="application/pdf,.pdf" multiple onChange={(event) => event.target.files && add(event.target.files)} />
    {notice && <p className="notice" role="status">{notice}</p>}
    {files.length > 0 && <div className="selected-files"><div className="row"><strong>{files.length} {files.length === 1 ? "document" : "documents"} ready</strong><button className="text-button" onClick={() => onChange([])} type="button">Clear all</button></div>{files.map((file, index) => <div className="file-row" key={`${file.name}-${index}`}><span className="file-type"><FileIcon /></span><span><b>{file.name}</b><small>{readableSize(file.size)} · Source {index + 1}</small></span><button aria-label={`Remove ${file.name}`} onClick={() => onChange(files.filter((_, current) => current !== index))}>Remove</button></div>)}</div>}
    <div className="upload-footer"><span><SparkIcon />Evidence remains linked to its source</span><button className="button button-primary" type="button" disabled={busy || files.length === 0} onClick={onGenerate}>{busy ? "Generating report…" : "Generate report"}</button></div>
  </section>;
}
