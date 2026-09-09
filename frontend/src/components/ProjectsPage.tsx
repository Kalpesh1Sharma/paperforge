import { useMemo, useState } from "react";
import type { ProjectRecord } from "../projects";
import { PlusIcon, SearchIcon } from "./Icons";
import { ProjectCollection } from "./ProjectCollection";

type Props = {
  projects: ProjectRecord[];
  onNewReport: () => void;
  onOpen: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
};

export function ProjectsPage({ projects, onNewReport, onOpen, onRename, onDelete }: Props) {
  const [query, setQuery] = useState("");
  const filtered = useMemo(() => {
    const term = query.trim().toLowerCase();
    if (!term) return projects;
    return projects.filter((project) => project.title.toLowerCase().includes(term) || project.sourceNames.some((name) => name.toLowerCase().includes(term)));
  }, [projects, query]);

  return <main className="projects-page page-enter">
    <header className="dashboard-header projects-header"><div><span className="page-kicker">PROJECT LIBRARY</span><h1>Your research, organised.</h1><p>Return to any generated report saved in your local workspace.</p></div><button className="button button-primary" onClick={onNewReport}><PlusIcon />New report</button></header>
    <section className="projects-panel">
      <div className="section-toolbar"><div><h2>All projects</h2><p>{projects.length} {projects.length === 1 ? "report" : "reports"} in this workspace</p></div><label className="search-field"><SearchIcon /><span className="visually-hidden">Search projects</span><input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search reports or sources" /></label></div>
      {filtered.length ? <ProjectCollection projects={filtered} onOpen={onOpen} onRename={onRename} onDelete={onDelete} /> : <div className="empty-projects compact"><h3>{projects.length ? "No matching projects" : "No reports yet"}</h3><p>{projects.length ? "Try a different report or source name." : "Create your first report from the PDFs already in your research folder."}</p>{!projects.length && <button className="text-action" onClick={onNewReport}>Create a report</button>}</div>}
    </section>
  </main>;
}
