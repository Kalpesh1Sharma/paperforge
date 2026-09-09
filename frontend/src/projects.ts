import type { ProjectApiRecord } from "./api/types";

export type ProjectRecord = {
  id: string;
  reportId: string | null;
  title: string;
  sourceNames: string[];
  pageCount: number;
  wordCount: number;
  formats: string[];
  status: "draft" | "ready";
  createdAt: string;
  updatedAt: string;
};

export function projectFromApi(project: ProjectApiRecord): ProjectRecord {
  return {
    id: project.id,
    reportId: project.report_id,
    title: project.title,
    sourceNames: project.sources.map((source) => source.filename),
    pageCount: project.sources.reduce((total, source) => total + (source.page_count ?? 0), 0),
    wordCount: project.sources.reduce((total, source) => total + source.word_count, 0),
    formats: project.available_formats,
    status: project.status,
    createdAt: project.created_at,
    updatedAt: project.updated_at,
  };
}

export function mergeProject(projects: ProjectRecord[], project: ProjectRecord) {
  return [project, ...projects.filter((item) => item.id !== project.id)]
    .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
}
