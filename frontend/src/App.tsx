import { useEffect, useState } from "react";
import { api, PaperForgeApiError } from "./api/client";
import type { ReportJob, ReportMetadata, ReviewState, WizardSettings } from "./api/types";
import { AppShell } from "./components/AppShell";
import { Dashboard } from "./components/Dashboard";
import { LandingPage } from "./components/LandingPage";
import { ProjectsPage } from "./components/ProjectsPage";
import { ReportWorkspace } from "./components/ReportWorkspace";
import { NewReportWizard } from "./components/NewReportWizard";
import { ProcessingPage } from "./components/ProcessingPage";
import { CheckIcon, SparkIcon } from "./components/Icons";
import { mergeProject, projectFromApi, type ProjectRecord } from "./projects";

type Connection = "checking" | "connected" | "unavailable";
type Route = "landing" | "dashboard" | "projects" | "new" | "processing" | "report";

const reportFromUrl = () => new URLSearchParams(window.location.search).get("report")?.trim() ?? "";
const jobFromUrl = () => new URLSearchParams(window.location.search).get("job")?.trim() ?? "";
const validReportId = (value: string) => /^[A-Za-z0-9-]+$/.test(value);

function routeFromLocation(): Route {
  if (reportFromUrl()) return "report";
  if (window.location.pathname === "/app/processing") return "processing";
  if (window.location.pathname === "/app/new") return "new";
  if (window.location.pathname === "/app/projects") return "projects";
  if (window.location.pathname.startsWith("/app")) return "dashboard";
  return "landing";
}

export default function App() {
  const [initialReportId] = useState(reportFromUrl);
  const [initialJobId] = useState(() => jobFromUrl() || window.localStorage.getItem("paperforge.activeJob") || "");
  const [route, setRoute] = useState<Route>(routeFromLocation);
  const [files, setFiles] = useState<File[]>([]);
  const [reportId, setReportId] = useState<string | null>(null);
  const [metadata, setMetadata] = useState<ReportMetadata | null>(null);
  const [review, setReview] = useState<ReviewState | null>(null);
  const [busy, setBusy] = useState(false);
  const [restoring, setRestoring] = useState(Boolean(initialReportId));
  const [connection, setConnection] = useState<Connection>("checking");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [projects, setProjects] = useState<ProjectRecord[]>([]);
  const [requestId, setRequestId] = useState<string | null>(null);
  const [jobId, setJobId] = useState(initialJobId);
  const [job, setJob] = useState<ReportJob | null>(null);

  useEffect(() => {
    api.health().then(() => setConnection("connected")).catch(() => setConnection("unavailable"));
    api.projects().then((records) => setProjects(records.map(projectFromApi))).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 3200);
    return () => window.clearTimeout(timer);
  }, [notice]);

  useEffect(() => {
    const handlePopState = () => setRoute(routeFromLocation());
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  useEffect(() => {
    if (!initialReportId) {
      setRestoring(false);
      return;
    }
    if (!validReportId(initialReportId)) {
      window.history.replaceState(null, "", "/app");
      setRoute("dashboard");
      setError("That report is no longer available.");
      setRestoring(false);
      return;
    }
    let active = true;
    const restore = async () => {
      try {
        const restoredMetadata = await api.metadata(initialReportId);
        if (!active) return;
        setReportId(initialReportId);
        setMetadata(restoredMetadata);
        const restoredProject = await api.project(initialReportId).catch(() => null);
        if (active && restoredProject) setProjects((current) => mergeProject(current, projectFromApi(restoredProject)));
        try {
          const restoredReview = await api.getReview(initialReportId);
          if (active) setReview(restoredReview);
        } catch (caught) {
          if (!(caught instanceof PaperForgeApiError) || caught.status !== 404) throw caught;
        }
      } catch (caught) {
        if (!active) return;
        window.history.replaceState(null, "", "/app");
        setRoute("dashboard");
        if (caught instanceof PaperForgeApiError && caught.status === 404) setError("That report is no longer available.");
        else if (caught instanceof PaperForgeApiError) {
          setError(caught.message);
          setRequestId(caught.detail.request_id);
        } else setError("PaperForge is unavailable. Please check the backend connection.");
      } finally {
        if (active) setRestoring(false);
      }
    };
    void restore();
    return () => { active = false; };
  }, [initialReportId]);

  useEffect(() => {
    if (!jobId) return;
    if (!validReportId(jobId)) {
      window.localStorage.removeItem("paperforge.activeJob");
      setJobId("");
      setError("That background job is no longer available.");
      if (window.location.pathname === "/app/processing") {
        window.history.replaceState(null, "", "/app");
        setRoute("dashboard");
      }
      return;
    }
    let active = true;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const next = await api.reportJob(jobId);
        if (!active) return;
        setJob(next);
        if (next.status === "completed") {
          window.localStorage.removeItem("paperforge.activeJob");
          setJobId("");
          const loaded = await api.metadata(next.report_id);
          if (!active) return;
          setReportId(next.report_id);
          setMetadata(loaded);
          setReview(null);
          setFiles([]);
          const savedProject = await api.project(next.report_id).catch(() => null);
          if (!active) return;
          if (savedProject) setProjects((current) => mergeProject(current, projectFromApi(savedProject)));
          setNotice("Report saved to your project library.");
          if (window.location.pathname === "/app/processing") {
            window.history.replaceState(null, "", `/app/report?report=${encodeURIComponent(next.report_id)}`);
            setRoute("report");
          }
          return;
        }
        if (next.status === "failed") {
          window.localStorage.removeItem("paperforge.activeJob");
          setJobId("");
          return;
        }
        timer = window.setTimeout(poll, 900);
      } catch (caught) {
        if (!active) return;
        if (caught instanceof PaperForgeApiError) {
          setError(caught.status === 404 ? "That background job is no longer available." : caught.message);
          setRequestId(caught.detail.request_id);
          if (caught.status === 404) {
            window.localStorage.removeItem("paperforge.activeJob");
            setJobId("");
          } else timer = window.setTimeout(poll, 1800);
        } else {
          setError("PaperForge is unavailable. Your background job is still safely stored.");
          timer = window.setTimeout(poll, 1800);
        }
      }
    };
    void poll();
    return () => { active = false; if (timer !== undefined) window.clearTimeout(timer); };
  }, [jobId]);

  const navigate = (path: string) => {
    window.history.pushState(null, "", path);
    setRoute(routeFromLocation());
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const safe = async <T,>(work: () => Promise<T>): Promise<T | null> => {
    setError(null);
    setRequestId(null);
    try {
      return await work();
    } catch (caught) {
      if (caught instanceof PaperForgeApiError) {
        setError(caught.message);
        setRequestId(caught.detail.request_id);
      } else setError("PaperForge is unavailable. Please check the backend connection.");
      return null;
    }
  };

  const activateJob = (created: ReportJob) => {
    window.localStorage.setItem("paperforge.activeJob", created.job_id);
    window.history.replaceState(null, "", `/app/processing?job=${encodeURIComponent(created.job_id)}`);
    setJob(created);
    setJobId(created.job_id);
    setRoute("processing");
  };

  const generate = async (settings: WizardSettings) => {
    if (!files.length) return;
    setBusy(true);
    const created = await safe(() => files.length === 1 ? api.createReportJob(files[0], settings) : api.createMultiReportJob(files, settings));
    if (created) activateJob(created);
    setBusy(false);
  };

  const regenerate = async () => {
    if (!reportId) return;
    setBusy(true);
    const created = await safe(() => api.regenerateReport(reportId));
    if (created) activateJob(created);
    setBusy(false);
  };

  const updateReview = async (work: () => Promise<ReviewState>) => {
    setBusy(true);
    const next = await safe(work);
    if (next) setReview(next);
    setBusy(false);
  };

  const startNewReport = () => {
    window.localStorage.removeItem("paperforge.activeJob");
    setJobId("");
    setJob(null);
    setFiles([]);
    setReportId(null);
    setMetadata(null);
    setReview(null);
    setError(null);
    setRequestId(null);
    navigate("/app/new");
  };

  const openProject = async (id: string) => {
    navigate(`/app/report?report=${encodeURIComponent(id)}`);
    setRestoring(true);
    setReportId(null);
    setMetadata(null);
    setReview(null);
    const loaded = await safe(() => api.metadata(id));
    if (!loaded) {
      setRestoring(false);
      navigate("/app/projects");
      return;
    }
    setReportId(id);
    setMetadata(loaded);
    const openedProject = await api.project(id).catch(() => null);
    if (openedProject) setProjects((current) => mergeProject(current, projectFromApi(openedProject)));
    try {
      const loadedReview = await api.getReview(id);
      setReview(loadedReview);
    } catch (caught) {
      if (!(caught instanceof PaperForgeApiError) || caught.status !== 404) {
        if (caught instanceof PaperForgeApiError) setError(caught.message);
        else setError("The report opened, but its review history could not be loaded.");
      }
    }
    setRestoring(false);
  };
  const renameProject = async (id: string, title: string) => {
    const updated = await safe(() => api.renameProject(id, title));
    if (!updated) return;
    setProjects((current) => mergeProject(current, projectFromApi(updated)));
    setNotice("Project renamed.");
  };
  const deleteProject = async (id: string) => {
    const deleted = await safe(async () => { await api.deleteProject(id); return true; });
    if (!deleted) return;
    setProjects((current) => current.filter((project) => project.id !== id));
    setNotice("Project removed from this workspace.");
  };

  if (route === "landing") return <LandingPage onOpenApp={() => navigate("/app")} connection={connection} />;

  const current = route === "report" ? "report" : route === "new" || route === "processing" ? "new" : route === "projects" ? "projects" : "dashboard";
  return (
    <AppShell current={current} connection={connection} onNavigate={navigate}>
      {error && <div className="app-error" role="alert"><strong>We couldn’t complete that request.</strong><span>{error}</span>{requestId && <small>Request ID: {requestId}</small>}</div>}
      {notice && <div className="app-toast" role="status"><CheckIcon /><span>{notice}</span><button aria-label="Dismiss notification" onClick={() => setNotice(null)}>×</button></div>}
      {job && (job.status === "queued" || job.status === "running") && route !== "processing" && <button className="active-job-banner" onClick={() => navigate(`/app/processing?job=${encodeURIComponent(job.job_id)}`)}><span><SparkIcon /><strong>Report generation in progress</strong><small>{job.message}</small></span><b>{job.progress}% · View progress →</b></button>}
      {restoring ? (
        <main className="restore-view"><span className="loading-mark"><SparkIcon /></span><span className="page-kicker">RESTORING REPORT</span><h1>Opening your research workspace</h1><p>Loading the saved report and its review history.</p></main>
      ) : route === "dashboard" ? (
        <Dashboard projects={projects} onNewReport={() => navigate("/app/new")} onOpen={openProject} onRename={renameProject} onDelete={deleteProject} onViewAll={() => navigate("/app/projects")} />
      ) : route === "projects" ? (
        <ProjectsPage projects={projects} onNewReport={() => navigate("/app/new")} onOpen={openProject} onRename={renameProject} onDelete={deleteProject} />
      ) : route === "processing" ? (
        <ProcessingPage job={job} onLeave={() => navigate("/app/projects")} onNewReport={startNewReport} />
      ) : route === "new" ? (
        <main className="new-report-page page-enter">
          <header className="page-header"><div><span className="page-kicker">NEW REPORT</span><h1>Build from evidence.</h1><p>Start with the documents you trust. You’ll review the structure before anything is published.</p></div><div className="draft-state"><span>Draft</span><small>Not saved</small></div></header>
          <NewReportWizard files={files} onFilesChange={setFiles} onGenerate={generate} busy={busy} />
        </main>
      ) : reportId && metadata ? (
        <ReportWorkspace id={reportId} metadata={metadata} review={review} busy={busy} onStart={() => updateReview(() => api.startReview(reportId))} onApprove={(changeId) => updateReview(() => api.approve(reportId, changeId))} onReject={(changeId, feedback) => updateReview(() => api.reject(reportId, changeId, feedback))} onRefresh={() => updateReview(() => api.getReview(reportId))} onNewReport={startNewReport} onRegenerate={regenerate} onBack={() => navigate("/app/projects")} />
      ) : (
        <main className="restore-view"><span className="loading-mark"><SparkIcon /></span><span className="page-kicker">REPORT UNAVAILABLE</span><h1>Choose a report from your projects</h1><p>The current report could not be restored.</p></main>
      )}
    </AppShell>
  );
}
