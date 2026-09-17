import { useRef, useState } from "react";
import type { CitationStyle, ContentTone, OutlineProposal, ReportSectionKey, ReportSectionSetting, ReportStructure, VisualTemplate, WizardSettings } from "../api/types";
import { readableSize, validPdf } from "../utils/files";
import { ArrowRightIcon, CheckIcon, FileIcon, PlusIcon, SparkIcon } from "./Icons";

type Props = {
  files: File[];
  onFilesChange: (files: File[]) => void;
  onProposeOutline: (settings: WizardSettings) => Promise<OutlineProposal | null>;
  onApproveOutline: (id: string, sections: ReportSectionSetting[]) => Promise<OutlineProposal | null>;
  onGenerate: (settings: WizardSettings) => void;
  busy: boolean;
};

const steps = ["Project information", "Upload sources", "Report structure", "Visual template", "Publication details", "Approve outline", "Review & generate"];
const structures: Array<{ id: ReportStructure; title: string; description: string }> = [
  { id: "professional", title: "Professional report", description: "Balanced depth for research, policy and business reports." },
  { id: "executive", title: "Executive brief", description: "A concise decision-focused report with fewer supporting sections." },
  { id: "technical", title: "Technical analysis", description: "More methods, evidence, metrics and implementation detail." },
  { id: "full", title: "Full research record", description: "The broadest structure with uncapped eligible supporting material." },
];
const templates: Array<{ id: VisualTemplate; title: string; description: string }> = [
  { id: "paperforge-classic", title: "Classic Academic", description: "Formal serif typography and an institutional publication system." },
  { id: "modern-research", title: "Modern Research", description: "Clean geometric hierarchy for contemporary reports." },
  { id: "ieee-inspired-technical", title: "IEEE-Inspired Technical", description: "Compact technical typography for engineering and computing reports." },
];
const reportSections: Array<{ key: ReportSectionKey; heading: string }> = [
  { key: "abstract", heading: "Abstract" },
  { key: "document-overview", heading: "Document Overview" },
  { key: "research-methodology", heading: "Report Guide" },
  { key: "executive-summary", heading: "Executive Summary" },
  { key: "key-insights", heading: "Major Findings" },
  { key: "technical-analysis", heading: "Technical Analysis" },
  { key: "historical-timeline", heading: "Historical Evolution" },
  { key: "important-concepts", heading: "Key Concepts" },
  { key: "evidence-summary", heading: "Evidence Summary" },
  { key: "appendix", heading: "Appendix" },
];
const sectionKeysByPreset: Record<ReportStructure, ReportSectionKey[]> = {
  executive: ["abstract", "executive-summary", "key-insights", "evidence-summary"],
  professional: ["abstract", "document-overview", "research-methodology", "executive-summary", "key-insights", "important-concepts", "evidence-summary", "appendix"],
  technical: ["abstract", "document-overview", "research-methodology", "executive-summary", "key-insights", "technical-analysis", "important-concepts", "evidence-summary", "appendix"],
  full: reportSections.map((section) => section.key),
};
const sectionsForPreset = (preset: ReportStructure) => reportSections.filter((section) => sectionKeysByPreset[preset].includes(section.key));

export function NewReportWizard({ files, onFilesChange, onProposeOutline, onApproveOutline, onGenerate, busy }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [step, setStep] = useState(1);
  const [notice, setNotice] = useState("");
  const [projectTitle, setProjectTitle] = useState("");
  const [domain, setDomain] = useState("");
  const [purpose, setPurpose] = useState("");
  const [audience, setAudience] = useState("");
  const [structure, setStructure] = useState<ReportStructure>("professional");
  const [tone, setTone] = useState<ContentTone>("professional");
  const [citationStyle, setCitationStyle] = useState<CitationStyle>("source-linked");
  const [template, setTemplate] = useState<VisualTemplate>("paperforge-classic");
  const [reportTitle, setReportTitle] = useState("");
  const [subtitle, setSubtitle] = useState("");
  const [author, setAuthor] = useState("Kalpesh Sharma");
  const [organisation, setOrganisation] = useState("");
  const [university, setUniversity] = useState("");
  const [department, setDepartment] = useState("");
  const [publicationType, setPublicationType] = useState("Research report");
  const [outline, setOutline] = useState<OutlineProposal | null>(null);
  const [approvedSections, setApprovedSections] = useState<ReportSectionSetting[] | null>(null);
  const [outlineNotice, setOutlineNotice] = useState("");

  const settings = (sections = approvedSections ?? sectionsForPreset(structure), approval = outline): WizardSettings => ({
    schema_version: 2,
    project_title: projectTitle.trim(), research_domain: domain.trim(), purpose: purpose.trim() || null,
    report_structure: { preset: structure, sections },
    content: { tone, audience: audience.trim() || null, language: "en" },
    visual_theme: { template, page_size: "A4", density: "comfortable", accent_color: null },
    citations: { style: citationStyle, include_bibliography: true },
    outline_approval: { approved: approval?.status === "approved", proposal_id: approval?.proposal_id ?? null, revision: approval?.status === "approved" ? approval.revision : 0 },
    publication: { title: reportTitle.trim(), subtitle: subtitle.trim() || null, author: author.trim(), organisation: organisation.trim() || null, university: university.trim() || null, department: department.trim() || null, publication_type: publicationType.trim() || null },
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
  const next = async () => {
    if (!valid || step >= 7) return;
    if (step === 1 && !reportTitle.trim()) setReportTitle(projectTitle.trim());
    if (step === 5) {
      setOutlineNotice("");
      const proposed = await onProposeOutline(settings(sectionsForPreset(structure), null));
      if (!proposed) { setOutlineNotice("PaperForge could not prepare the outline. Check the message above and try again."); return; }
      setOutline(proposed);
      setApprovedSections(null);
    }
    setStep((current) => current + 1);
  };
  const approve = async (sections: ReportSectionSetting[]) => {
    if (!outline) return;
    setOutlineNotice("");
    const approved = await onApproveOutline(outline.proposal_id, sections);
    if (!approved) { setOutlineNotice("The outline could not be approved. Try again."); return; }
    setOutline(approved);
    setApprovedSections(approved.sections.map(({ key, heading }) => ({ key, heading })));
    setStep(7);
  };
  const back = () => {
    if (step === 6) { setOutline(null); setApprovedSections(null); }
    setStep((current) => current - 1);
  };

  return <div className="wizard-layout">
    <aside className="wizard-progress" aria-label="Report creation progress">
      <span className="section-label">REPORT SETUP</span>
      <ol>{steps.map((label, index) => { const number = index + 1; return <li key={label} className={number === step ? "active" : number < step ? "complete" : ""} aria-current={number === step ? "step" : undefined}><i>{number < step ? <CheckIcon /> : number}</i><span><small>Step {number}</small><b>{label}</b></span></li>; })}</ol>
      <div className="privacy-note"><CheckIcon /><span><b>Your API keys stay private.</b><small>Requests are sent only by your backend.</small></span></div>
    </aside>
    <section className="wizard-card">
      <header className="wizard-heading"><span className="step-number">{String(step).padStart(2, "0")}</span><div><span className="page-kicker">{steps[step - 1].toUpperCase()}</span><h2>{step === 1 ? "Tell us what you are building" : step === 2 ? "Add your research documents" : step === 3 ? "Choose the report depth" : step === 4 ? "Choose a professional format" : step === 5 ? "Complete the cover details" : step === 6 ? "Shape and approve the outline" : "Review your approved report"}</h2><p>{step === 6 ? "Evidence availability is estimated from your selected PDFs before generation." : step === 7 ? "Only the approved section order and headings will be generated." : "You can return to earlier steps before generation."}</p></div></header>

      {step === 1 && <div className="wizard-form"><label>Project name<span>Used in your PaperForge project library.</span><input autoFocus value={projectTitle} maxLength={100} onChange={(event) => setProjectTitle(event.target.value)} placeholder="e.g. Responsible AI policy review" /></label><label>Research domain<span>Used on the generated report cover.</span><input value={domain} maxLength={100} onChange={(event) => setDomain(event.target.value)} placeholder="e.g. Artificial Intelligence Governance" /></label><label>Purpose <em>Optional</em><span>What should this report accomplish?</span><textarea value={purpose} maxLength={500} onChange={(event) => setPurpose(event.target.value)} placeholder="Summarise the evidence for an academic review panel." /></label><label>Intended audience <em>Optional</em><span>Who will read the report?</span><input value={audience} maxLength={160} onChange={(event) => setAudience(event.target.value)} placeholder="e.g. Academic review panel" /></label></div>}

      {step === 2 && <div><button className="dropzone" type="button" onClick={() => input.current?.click()} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); addFiles(event.dataTransfer.files); }} aria-label="Choose PDF files"><span className="drop-icon"><PlusIcon /></span><strong>Drop your PDFs here</strong><span>or click to browse · up to 5 PDFs · 50 MB each</span></button><input ref={input} hidden aria-label="PDF files input" type="file" accept="application/pdf,.pdf" multiple onChange={(event) => event.target.files && addFiles(event.target.files)} />{notice && <p className="notice" role="status">{notice}</p>}{files.length > 0 && <div className="selected-files"><div className="row"><strong>{files.length} {files.length === 1 ? "document" : "documents"} ready</strong><button className="text-button" onClick={() => onFilesChange([])} type="button">Clear all</button></div>{files.map((file, index) => <div className="file-row" key={`${file.name}-${index}`}><span className="file-type"><FileIcon /></span><span><b>{file.name}</b><small>{readableSize(file.size)} · Source {index + 1}</small></span><button aria-label={`Remove ${file.name}`} onClick={() => onFilesChange(files.filter((_, current) => current !== index))}>Remove</button></div>)}</div>}</div>}

      {step === 3 && <div><div className="choice-grid structure-grid">{structures.map((item) => <button type="button" key={item.id} className={`choice-card ${structure === item.id ? "selected" : ""}`} onClick={() => setStructure(item.id)} aria-pressed={structure === item.id}><span>{structure === item.id && <CheckIcon />}</span><b>{item.title}</b><small>{item.description}</small></button>)}</div><div className="field-row wizard-form compact-options"><label>Writing tone<span>Controls the prose direction.</span><select value={tone} onChange={(event) => setTone(event.target.value as ContentTone)}><option value="professional">Professional</option><option value="academic">Academic</option><option value="executive">Executive</option><option value="technical">Technical</option></select></label><label>Citation style<span>Stored independently from content and theme.</span><select value={citationStyle} onChange={(event) => setCitationStyle(event.target.value as CitationStyle)}><option value="source-linked">Source-linked</option><option value="apa">APA</option><option value="ieee">IEEE</option><option value="harvard">Harvard</option></select></label></div></div>}
      {step === 4 && <div><div className="choice-grid template-grid">{templates.map((item) => <button type="button" key={item.id} className={`choice-card template-choice template-${item.id} ${template === item.id ? "selected" : ""}`} onClick={() => setTemplate(item.id)} aria-pressed={template === item.id}><i><u /><u /><u /></i><span>{template === item.id && <CheckIcon />}</span><b>{item.title}</b><small>{item.description}</small></button>)}</div><p className="placeholder-note"><SparkIcon /> Each format has its own screen and print typography, spacing and publication treatment.</p></div>}
      {step === 5 && <div className="wizard-form"><label>Report title<span>Printed as the main title on the cover.</span><input autoFocus value={reportTitle} maxLength={180} onChange={(event) => setReportTitle(event.target.value)} /></label><label>Subtitle <em>Optional</em><span>A supporting cover line.</span><input value={subtitle} maxLength={240} onChange={(event) => setSubtitle(event.target.value)} /></label><div className="field-row"><label>Author<span>Prepared by</span><input value={author} maxLength={100} onChange={(event) => setAuthor(event.target.value)} /></label><label>Publication type <em>Optional</em><span>Document classification</span><input value={publicationType} maxLength={100} onChange={(event) => setPublicationType(event.target.value)} /></label></div><div className="field-row"><label>University <em>Optional</em><span>Academic institution</span><input value={university} maxLength={160} onChange={(event) => setUniversity(event.target.value)} placeholder="e.g. MNIT Jaipur" /></label><label>Department <em>Optional</em><span>School, faculty or unit</span><input value={department} maxLength={160} onChange={(event) => setDepartment(event.target.value)} /></label></div><label>Organisation <em>Optional</em><span>Company, laboratory or institution</span><input value={organisation} maxLength={120} onChange={(event) => setOrganisation(event.target.value)} /></label></div>}
      {step === 6 && outline && <OutlineEditor proposal={outline} busy={busy} onApprove={approve} />}
      {outlineNotice && <p className="notice" role="alert">{outlineNotice}</p>}
      {step === 7 && <div><Review projectTitle={projectTitle} domain={domain} purpose={purpose} audience={audience} files={files} structure={structure} tone={tone} citationStyle={citationStyle} template={template} reportTitle={reportTitle} author={author} organisation={organisation} university={university} onEdit={(target) => { setOutline(null); setApprovedSections(null); setStep(target); }} /><div className="approved-outline-summary"><CheckIcon /><span><b>Outline approved</b><small>{approvedSections?.length ?? 0} sections · revision {outline?.revision}</small></span></div><div className="generate-ready compact"><button className="button button-primary button-large" type="button" disabled={busy || !approvedSections} onClick={() => onGenerate(settings())}>{busy ? "Starting report…" : "Generate approved report"}<ArrowRightIcon /></button></div></div>}

      <footer className="wizard-actions"><button className="button button-quiet" type="button" disabled={step === 1 || busy} onClick={back}>Back</button>{step < 6 && <button className="button button-primary" type="button" disabled={!valid || busy} onClick={() => void next()}>{busy && step === 5 ? "Scanning evidence…" : "Continue"} <ArrowRightIcon /></button>}</footer>
    </section>
  </div>;
}

function OutlineEditor({ proposal, busy, onApprove }: { proposal: OutlineProposal; busy: boolean; onApprove: (sections: ReportSectionSetting[]) => Promise<void> }) {
  const [sections, setSections] = useState<ReportSectionSetting[]>(proposal.sections.map(({ key, heading }) => ({ key, heading })));
  const [addKey, setAddKey] = useState<ReportSectionKey | "">("");
  const evidence = new Map(proposal.catalog.map((item) => [item.key, item]));
  const available = proposal.catalog.filter((item) => !sections.some((section) => section.key === item.key));
  const move = (index: number, direction: -1 | 1) => { const target = index + direction; if (target < 0 || target >= sections.length) return; const next = [...sections]; [next[index], next[target]] = [next[target], next[index]]; setSections(next); };
  const add = () => { if (!addKey) return; const item = evidence.get(addKey); if (item) setSections((current) => [...current, { key: item.key, heading: item.heading }]); setAddKey(""); };
  return <div className="outline-editor">
    <div className="outline-legend"><span><i className="strong" />Strong</span><span><i className="moderate" />Moderate</span><span><i className="limited" />Limited</span><small>{proposal.source_filenames.length} source {proposal.source_filenames.length === 1 ? "document" : "documents"} scanned</small></div>
    <ol className="outline-section-list">{sections.map((section, index) => { const item = evidence.get(section.key)!; return <li key={section.key}>
      <span className="outline-handle">{String(index + 1).padStart(2, "0")}</span>
      <label><span>Section heading</span><input aria-label={`${section.key} heading`} maxLength={120} value={section.heading} onChange={(event) => setSections((current) => current.map((value) => value.key === section.key ? { ...value, heading: event.target.value } : value))} /></label>
      <div className={`evidence-badge ${item.level}`} title={item.reason}><b>{item.level}</b><small>{item.evidence_count} signals · {item.source_count} supporting {item.source_count === 1 ? "source" : "sources"}</small></div>
      <div className="outline-controls"><button type="button" aria-label={`Move ${section.heading} up`} disabled={index === 0} onClick={() => move(index, -1)}>↑</button><button type="button" aria-label={`Move ${section.heading} down`} disabled={index === sections.length - 1} onClick={() => move(index, 1)}>↓</button><button type="button" aria-label={`Remove ${section.heading}`} disabled={sections.length === 1} onClick={() => setSections((current) => current.filter((value) => value.key !== section.key))}>Remove</button></div>
    </li>; })}</ol>
    <div className="outline-add"><label>Add another section<select value={addKey} onChange={(event) => setAddKey(event.target.value as ReportSectionKey | "")}><option value="">Choose a section</option>{available.map((item) => <option key={item.key} value={item.key}>{item.heading} · {item.level}</option>)}</select></label><button className="button button-quiet" type="button" disabled={!addKey} onClick={add}>Add section</button></div>
    <div className="outline-approve"><p>Approval locks this exact order and these headings for generation.</p><button className="button button-primary" type="button" disabled={busy || sections.some((section) => !section.heading.trim())} onClick={() => void onApprove(sections.map((section) => ({ ...section, heading: section.heading.trim() })))}>{busy ? "Saving approval…" : "Approve outline & continue"}<ArrowRightIcon /></button></div>
  </div>;
}

function Review({ projectTitle, domain, purpose, audience, files, structure, tone, citationStyle, template, reportTitle, author, organisation, university, onEdit }: { projectTitle: string; domain: string; purpose: string; audience: string; files: File[]; structure: ReportStructure; tone: ContentTone; citationStyle: CitationStyle; template: VisualTemplate; reportTitle: string; author: string; organisation: string; university: string; onEdit: (step: number) => void }) {
  const rows = [
    ["Project", projectTitle, 1], ["Research domain", domain, 1], ["Sources", files.map((file) => file.name).join(", "), 2],
    ["Structure", structures.find((item) => item.id === structure)?.title ?? structure, 3], ["Writing tone", tone, 3], ["Citation style", citationStyle, 3], ["Template", templates.find((item) => item.id === template)?.title ?? template, 4],
    ["Report title", reportTitle, 5], ["Author", author, 5], ["University", university || "Not specified", 5], ["Organisation", organisation || "Not specified", 5],
  ] as const;
  return <div className="review-settings">{rows.map(([label, value, target]) => <div key={label}><span><small>{label}</small><b>{value}</b></span><button type="button" onClick={() => onEdit(target)}>Edit</button></div>)}{(purpose || audience) && <aside><small>Brief</small>{purpose && <p>{purpose}</p>}{audience && <p>Audience: {audience}</p>}</aside>}</div>;
}
