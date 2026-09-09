import { useRef, useState } from "react";
import type { ReportStructure, VisualTemplate, WizardSettings } from "../api/types";
import { readableSize, validPdf } from "../utils/files";
import { ArrowRightIcon, CheckIcon, FileIcon, PlusIcon, SparkIcon } from "./Icons";

type Props = {
  files: File[];
  onFilesChange: (files: File[]) => void;
  onGenerate: (settings: WizardSettings) => void;
  busy: boolean;
};

const steps = ["Project information", "Upload sources", "Report structure", "Visual template", "Publication details", "Review settings", "Generate"];
const structures: Array<{ id: ReportStructure; title: string; description: string }> = [
  { id: "professional", title: "Professional report", description: "Balanced depth for research, policy and business reports." },
  { id: "executive", title: "Executive brief", description: "A concise decision-focused report with fewer supporting sections." },
  { id: "technical", title: "Technical analysis", description: "More methods, evidence, metrics and implementation detail." },
  { id: "full", title: "Full research record", description: "The broadest structure with uncapped eligible supporting material." },
];
const templates: Array<{ id: VisualTemplate; title: string; description: string }> = [
  { id: "paperforge-classic", title: "PaperForge Classic", description: "Editorial serif styling with restrained research colours." },
  { id: "modern-research", title: "Modern Research", description: "Clean geometric hierarchy for contemporary reports." },
  { id: "editorial", title: "Editorial", description: "High-contrast typography for long-form institutional reading." },
  { id: "minimal", title: "Minimal", description: "A quiet, compact layout that keeps attention on the evidence." },
];

export function NewReportWizard({ files, onFilesChange, onGenerate, busy }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [step, setStep] = useState(1);
  const [notice, setNotice] = useState("");
  const [projectTitle, setProjectTitle] = useState("");
  const [domain, setDomain] = useState("");
  const [purpose, setPurpose] = useState("");
  const [structure, setStructure] = useState<ReportStructure>("professional");
  const [template, setTemplate] = useState<VisualTemplate>("paperforge-classic");
  const [reportTitle, setReportTitle] = useState("");
  const [author, setAuthor] = useState("Kalpesh Sharma");
  const [organisation, setOrganisation] = useState("");

  const settings = (): WizardSettings => ({
    project_title: projectTitle.trim(), research_domain: domain.trim(), purpose: purpose.trim() || null,
    structure, visual_template: template, report_title: reportTitle.trim(), author: author.trim(), organisation: organisation.trim() || null,
  });
  const valid = step === 1 ? Boolean(projectTitle.trim() && domain.trim()) : step === 2 ? files.length > 0 : step === 5 ? Boolean(reportTitle.trim() && author.trim()) : true;
  const addFiles = (incoming: FileList | File[]) => {
    const next = [...files]; setNotice("");
    for (const file of Array.from(incoming)) {
      if (!validPdf(file)) { setNotice("Only PDF files can be selected."); continue; }
      if (next.some((item) => item.name.toLowerCase() === file.name.toLowerCase())) { setNotice(`Duplicate filename: ${file.name}`); continue; }
      if (next.length === 5) { setNotice("You can upload a maximum of five PDFs."); break; }
      next.push(file);
    }
    onFilesChange(next);
  };
  const next = () => {
    if (!valid || step >= 7) return;
    if (step === 1 && !reportTitle.trim()) setReportTitle(projectTitle.trim());
    setStep((current) => current + 1);
  };

  return <div className="wizard-layout">
    <aside className="wizard-progress" aria-label="Report creation progress">
      <span className="section-label">REPORT SETUP</span>
      <ol>{steps.map((label, index) => { const number = index + 1; return <li key={label} className={number === step ? "active" : number < step ? "complete" : ""} aria-current={number === step ? "step" : undefined}><i>{number < step ? <CheckIcon /> : number}</i><span><small>Step {number}</small><b>{label}</b></span></li>; })}</ol>
      <div className="privacy-note"><CheckIcon /><span><b>Your API keys stay private.</b><small>Requests are sent only by your backend.</small></span></div>
    </aside>
    <section className="wizard-card">
      <header className="wizard-heading"><span className="step-number">{String(step).padStart(2, "0")}</span><div><span className="page-kicker">{steps[step - 1].toUpperCase()}</span><h2>{step === 1 ? "Tell us what you are building" : step === 2 ? "Add your research documents" : step === 3 ? "Choose the report depth" : step === 4 ? "Choose a visual direction" : step === 5 ? "Complete the cover details" : step === 6 ? "Review your choices" : "Ready to build your report"}</h2><p>{step === 7 ? "PaperForge will preserve the source order, apply your structure and save the finished report to Projects." : "You can return to earlier steps before generation."}</p></div></header>

      {step === 1 && <div className="wizard-form"><label>Project name<span>Used in your PaperForge project library.</span><input autoFocus value={projectTitle} maxLength={100} onChange={(event) => setProjectTitle(event.target.value)} placeholder="e.g. Responsible AI policy review" /></label><label>Research domain<span>Used on the generated report cover.</span><input value={domain} maxLength={100} onChange={(event) => setDomain(event.target.value)} placeholder="e.g. Artificial Intelligence Governance" /></label><label>Purpose <em>Optional</em><span>A short note about the goal or intended reader.</span><textarea value={purpose} maxLength={500} onChange={(event) => setPurpose(event.target.value)} placeholder="Summarise the evidence for an academic review panel." /></label></div>}

      {step === 2 && <div><button className="dropzone" type="button" onClick={() => input.current?.click()} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); addFiles(event.dataTransfer.files); }} aria-label="Choose PDF files"><span className="drop-icon"><PlusIcon /></span><strong>Drop your PDFs here</strong><span>or click to browse · up to 5 PDFs · 50 MB each</span></button><input ref={input} hidden aria-label="PDF files input" type="file" accept="application/pdf,.pdf" multiple onChange={(event) => event.target.files && addFiles(event.target.files)} />{notice && <p className="notice" role="status">{notice}</p>}{files.length > 0 && <div className="selected-files"><div className="row"><strong>{files.length} {files.length === 1 ? "document" : "documents"} ready</strong><button className="text-button" onClick={() => onFilesChange([])} type="button">Clear all</button></div>{files.map((file, index) => <div className="file-row" key={`${file.name}-${index}`}><span className="file-type"><FileIcon /></span><span><b>{file.name}</b><small>{readableSize(file.size)} · Source {index + 1}</small></span><button aria-label={`Remove ${file.name}`} onClick={() => onFilesChange(files.filter((_, current) => current !== index))}>Remove</button></div>)}</div>}</div>}

      {step === 3 && <div className="choice-grid structure-grid">{structures.map((item) => <button type="button" key={item.id} className={`choice-card ${structure === item.id ? "selected" : ""}`} onClick={() => setStructure(item.id)} aria-pressed={structure === item.id}><span>{structure === item.id && <CheckIcon />}</span><b>{item.title}</b><small>{item.description}</small></button>)}</div>}
      {step === 4 && <div><div className="choice-grid template-grid">{templates.map((item) => <button type="button" key={item.id} className={`choice-card template-choice template-${item.id} ${template === item.id ? "selected" : ""}`} onClick={() => setTemplate(item.id)} aria-pressed={template === item.id}><i><u /><u /><u /></i><span>{template === item.id && <CheckIcon />}</span><b>{item.title}</b><small>{item.description}</small></button>)}</div><p className="placeholder-note"><SparkIcon /> Template previews are placeholders in Phase 1. Full template-specific rendering arrives in Phase 2.</p></div>}
      {step === 5 && <div className="wizard-form"><label>Report title<span>Printed as the main title on the cover.</span><input autoFocus value={reportTitle} maxLength={180} onChange={(event) => setReportTitle(event.target.value)} /></label><div className="field-row"><label>Author<span>Prepared by</span><input value={author} maxLength={100} onChange={(event) => setAuthor(event.target.value)} /></label><label>Organisation <em>Optional</em><span>University, company or institution</span><input value={organisation} maxLength={120} onChange={(event) => setOrganisation(event.target.value)} placeholder="e.g. MNIT Jaipur" /></label></div></div>}
      {step === 6 && <Review projectTitle={projectTitle} domain={domain} purpose={purpose} files={files} structure={structure} template={template} reportTitle={reportTitle} author={author} organisation={organisation} onEdit={setStep} />}
      {step === 7 && <div className="generate-ready"><span><SparkIcon /></span><h3>{reportTitle}</h3><p>{files.length} {files.length === 1 ? "source" : "sources"} · {structures.find((item) => item.id === structure)?.title} · {templates.find((item) => item.id === template)?.title}</p><button className="button button-primary button-large" type="button" disabled={busy} onClick={() => onGenerate(settings())}>{busy ? "Generating report…" : "Generate report"}<ArrowRightIcon /></button></div>}

      <footer className="wizard-actions"><button className="button button-quiet" type="button" disabled={step === 1 || busy} onClick={() => setStep((current) => current - 1)}>Back</button>{step < 7 && <button className="button button-primary" type="button" disabled={!valid || busy} onClick={next}>Continue <ArrowRightIcon /></button>}</footer>
    </section>
  </div>;
}

function Review({ projectTitle, domain, purpose, files, structure, template, reportTitle, author, organisation, onEdit }: { projectTitle: string; domain: string; purpose: string; files: File[]; structure: ReportStructure; template: VisualTemplate; reportTitle: string; author: string; organisation: string; onEdit: (step: number) => void }) {
  const rows = [
    ["Project", projectTitle, 1], ["Research domain", domain, 1], ["Sources", files.map((file) => file.name).join(", "), 2],
    ["Structure", structures.find((item) => item.id === structure)?.title ?? structure, 3], ["Template", templates.find((item) => item.id === template)?.title ?? template, 4],
    ["Report title", reportTitle, 5], ["Author", author, 5], ["Organisation", organisation || "Not specified", 5],
  ] as const;
  return <div className="review-settings">{rows.map(([label, value, target]) => <div key={label}><span><small>{label}</small><b>{value}</b></span><button type="button" onClick={() => onEdit(target)}>Edit</button></div>)}{purpose && <aside><small>Purpose</small><p>{purpose}</p></aside>}</div>;
}
