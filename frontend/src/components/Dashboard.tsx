import { useMemo, useState } from "react";
import type { ProjectRecord } from "../projects";
import { ArrowRightIcon, ClockIcon, FileIcon, PlusIcon, SearchIcon } from "./Icons";
import { ProjectCollection } from "./ProjectCollection";

type Props = { projects: ProjectRecord[]; onNewReport: () => void; onOpen: (id: string) => void; onRename: (id: string, title: string) => void; onDelete: (id: string) => void; onViewAll: () => void };

export function Dashboard({ projects, onNewReport, onOpen, onRename, onDelete, onViewAll }: Props) {
  const [query, setQuery] = useState("");
  const recent = useMemo(() => {
    const term = query.trim().toLowerCase();
    const matching = term ? projects.filter((project) => project.title.toLowerCase().includes(term) || project.sourceNames.some((name) => name.toLowerCase().includes(term))) : projects;
    return matching.slice(0, 3);
  }, [projects, query]);
  return (
    <main className="dashboard page-enter">
      <header className="dashboard-header">
        <div><span className="page-kicker">PERSONAL WORKSPACE</span><h1>Good evening, Kalpesh.</h1><p>What are you researching today?</p></div>
        <button className="button button-primary" onClick={onNewReport}><PlusIcon />New report</button>
      </header>

      <section className="quick-start">
        <div className="quick-copy"><span className="section-label">QUICK START</span><h2>Turn your source documents into a grounded report.</h2><p>Add up to five PDFs. PaperForge will preserve their order, extract the evidence, and build a report you can inspect.</p><button className="button button-light" onClick={onNewReport}>{projects.length ? "Create another report" : "Create your first report"} <ArrowRightIcon /></button></div>
        <div className="paper-stack" aria-hidden="true"><div /><div /><div><FileIcon /><span>YOUR NEXT<br />RESEARCH REPORT</span><i /></div></div>
      </section>

      <section className="projects-section">
        <div className="section-toolbar"><div><h2>Recent projects</h2><p>{projects.length ? `${projects.length} saved ${projects.length === 1 ? "report" : "reports"}` : "Your reports will appear here."}</p></div><div className="toolbar-actions">{projects.length > 3 && <button className="text-button" onClick={onViewAll}>View all</button>}<label className="search-field"><SearchIcon /><span className="visually-hidden">Search projects</span><input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search projects" /></label></div></div>
        {recent.length ? <ProjectCollection projects={recent} onOpen={onOpen} onRename={onRename} onDelete={onDelete} /> : <div className="empty-projects">
          <div className="empty-icon"><ClockIcon /></div>
          <h3>{projects.length ? "No matching projects" : "No reports yet"}</h3>
          <p>{projects.length ? "Try a different report or source name." : "Start with the papers, notes, or documents already sitting in your research folder."}</p>
          {!projects.length && <button className="text-action" onClick={onNewReport}>Create a report <ArrowRightIcon /></button>}
        </div>}
      </section>
    </main>
  );
}
