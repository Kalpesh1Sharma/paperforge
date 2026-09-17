import { useState } from "react";
import type { ProjectRecord } from "../projects";
import { ArrowRightIcon, ClockIcon, FileIcon, PencilIcon, TrashIcon } from "./Icons";

type Props = {
  projects: ProjectRecord[];
  onOpen: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
};

const formatDate = (value: string) => new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
}).format(new Date(value));

export function ProjectCollection({ projects, onOpen, onRename, onDelete }: Props) {
  const [renaming, setRenaming] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [draftTitle, setDraftTitle] = useState("");

  const beginRename = (project: ProjectRecord) => {
    setDeleting(null);
    setRenaming(project.id);
    setDraftTitle(project.title);
  };

  const saveRename = (project: ProjectRecord) => {
    const title = draftTitle.trim();
    if (!title) return;
    onRename(project.id, title);
    setRenaming(null);
  };

  return <div className="project-grid">
    {projects.map((project) => <article className="project-card" key={project.id}>
      <div className="project-card-top">
        <span className="project-file"><FileIcon /></span>
        <span className="project-status"><i />{project.status === "ready" ? "Ready" : "Draft"}</span>
      </div>
      {renaming === project.id ? <div className="rename-form">
        <label htmlFor={`rename-${project.id}`}>Report name</label>
        <input id={`rename-${project.id}`} value={draftTitle} maxLength={100} autoFocus onChange={(event) => setDraftTitle(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") saveRename(project); if (event.key === "Escape") setRenaming(null); }} />
        <div><button className="small-button primary" onClick={() => saveRename(project)}>Save</button><button className="small-button" onClick={() => setRenaming(null)}>Cancel</button></div>
      </div> : <>
        <h3>{project.title}</h3>
        <p className="project-sources">{project.sourceNames.length ? project.sourceNames.join(", ") : "Source details unavailable"}</p>
      </>}
      <div className="project-meta"><span><ClockIcon />{formatDate(project.updatedAt)}</span><span>{project.sourceNames.length} {project.sourceNames.length === 1 ? "source" : "sources"} · {project.wordCount.toLocaleString()} words</span></div>
      {deleting === project.id ? <div className="delete-confirm" role="alert"><p>Permanently delete this project, its sources, reports and exports?</p><div><button className="small-button danger" onClick={() => onDelete(project.id)}>Delete permanently</button><button className="small-button" onClick={() => setDeleting(null)}>Cancel</button></div></div> : <div className="project-actions">
        <button className="open-project" disabled={!project.reportId} onClick={() => project.reportId && onOpen(project.reportId)}>{project.reportId ? "Open report" : "Draft project"} <ArrowRightIcon /></button>
        <button aria-label={`Rename ${project.title}`} onClick={() => beginRename(project)}><PencilIcon /></button>
        <button aria-label={`Delete ${project.title}`} onClick={() => { setRenaming(null); setDeleting(project.id); }}><TrashIcon /></button>
      </div>}
    </article>)}
  </div>;
}
