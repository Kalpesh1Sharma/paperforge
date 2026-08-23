import type { ApiError, CreationResponse, Health, ReportMetadata, ReviewState } from "./types";

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
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<Health>("/health"),
  createReport: (file: File) => { const form = new FormData(); form.append("file", file); return request<CreationResponse>("/reports", { method: "POST", body: form }); },
  createMultiReport: (files: File[]) => { const form = new FormData(); files.forEach((file) => form.append("files", file)); return request<CreationResponse>("/reports/multi", { method: "POST", body: form }); },
  metadata: (id: string) => request<ReportMetadata>(`/reports/${id}/metadata`),
  getReview: (id: string) => request<ReviewState>(`/reports/${id}/review`),
  startReview: (id: string) => request<ReviewState>(`/reports/${id}/review`, { method: "POST" }),
  approve: (id: string, changeId: string) => request<ReviewState>(`/reports/${id}/review/approve`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ change_id: changeId }) }),
  reject: (id: string, changeId: string, feedback?: string) => request<ReviewState>(`/reports/${id}/review/reject`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(feedback ? { change_id: changeId, feedback } : { change_id: changeId }) })
};
