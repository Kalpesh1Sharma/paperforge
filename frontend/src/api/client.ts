import type { ApiError, CreationResponse, Health, ProjectApiRecord, ReportJob, ReportMetadata, ReportPresentation, ReviewState, WizardSettings } from "./types";

const baseUrl = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";
export const reportUrl = (id: string, format: "html" | "pdf" | "markdown" | "docx") => `${baseUrl}/reports/${id}/${format}`;

export class PaperForgeApiError extends Error { constructor(public readonly detail: ApiError, public readonly status: number) { super(detail.message); } }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, init);
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    const detail = typeof body === "object" && body !== null && "error" in body ? (body as { error: ApiError }).error : { code: "request_failed", message: "PaperForge could not complete the request.", request_id: "unavailable" };
    throw new PaperForgeApiError(detail, response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<Health>("/health"),
  createReport: (file: File, settings?: WizardSettings) => { const form = new FormData(); form.append("file", file); if (settings) form.append("settings", JSON.stringify(settings)); return request<CreationResponse>("/reports", { method: "POST", body: form }); },
  createMultiReport: (files: File[], settings?: WizardSettings) => { const form = new FormData(); files.forEach((file) => form.append("files", file)); if (settings) form.append("settings", JSON.stringify(settings)); return request<CreationResponse>("/reports/multi", { method: "POST", body: form }); },
  createReportJob: (file: File, settings: WizardSettings) => { const form = new FormData(); form.append("file", file); form.append("settings", JSON.stringify(settings)); return request<ReportJob>("/reports/jobs", { method: "POST", body: form }); },
  createMultiReportJob: (files: File[], settings: WizardSettings) => { const form = new FormData(); files.forEach((file) => form.append("files", file)); form.append("settings", JSON.stringify(settings)); return request<ReportJob>("/reports/jobs/multi", { method: "POST", body: form }); },
  reportJob: (id: string) => request<ReportJob>(`/reports/jobs/${id}`),
  regenerateReport: (id: string) => request<ReportJob>(`/reports/${id}/regenerate`, { method: "POST" }),
  presentation: (id: string) => request<ReportPresentation>(`/reports/${id}`),
  metadata: (id: string) => request<ReportMetadata>(`/reports/${id}/metadata`),
  projects: () => request<ProjectApiRecord[]>("/projects"),
  project: (id: string) => request<ProjectApiRecord>(`/projects/${id}`),
  createProject: (title: string) => request<ProjectApiRecord>("/projects", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title }) }),
  renameProject: (id: string, title: string) => request<ProjectApiRecord>(`/projects/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title }) }),
  deleteProject: (id: string) => request<void>(`/projects/${id}`, { method: "DELETE" }),
  getReview: (id: string) => request<ReviewState>(`/reports/${id}/review`),
  startReview: (id: string) => request<ReviewState>(`/reports/${id}/review`, { method: "POST" }),
  approve: (id: string, changeId: string) => request<ReviewState>(`/reports/${id}/review/approve`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ change_id: changeId }) }),
  reject: (id: string, changeId: string, feedback?: string) => request<ReviewState>(`/reports/${id}/review/reject`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(feedback ? { change_id: changeId, feedback } : { change_id: changeId }) })
};
