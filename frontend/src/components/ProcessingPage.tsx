import type { ReportJob, ReportJobStage } from "../api/types";
import { CheckIcon, SparkIcon } from "./Icons";

type Props = {
  job: ReportJob | null;
  onLeave: () => void;
  onNewReport: () => void;
};

const phases: Array<{ stage: ReportJobStage; label: string }> = [
  { stage: "queued", label: "Sources secured" },
  { stage: "parsing", label: "Read documents" },
  { stage: "extracting", label: "Extract evidence" },
  { stage: "synthesizing", label: "Build grounded synthesis" },
  { stage: "reviewing", label: "Verify report structure" },
  { stage: "rendering", label: "Prepare publication files" },
];

const stageRank: Record<ReportJobStage, number> = {
  queued: 0,
  parsing: 1,
  chunking: 1,
  extracting: 2,
  researching: 2,
  synthesizing: 3,
  reviewing: 4,
  composing: 4,
  rendering: 5,
  completed: 6,
  failed: -1,
};

export function ProcessingPage({ job, onLeave, onNewReport }: Props) {
  if (!job) return <main className="processing-page"><div className="processing-card loading"><span className="loading-mark"><SparkIcon /></span><span className="page-kicker">RESTORING JOB</span><h1>Finding your report progress</h1><p>The job identifier is stored locally, so this page can be reopened safely.</p></div></main>;
  const failed = job.status === "failed";
  const rank = stageRank[job.stage];
  return <main className="processing-page page-enter">
    <section className={`processing-card ${failed ? "failed" : ""}`} aria-live="polite">
      <div className="processing-copy">
        <span className="page-kicker">{failed ? "GENERATION NEEDS ATTENTION" : "BACKGROUND REPORT JOB"}</span>
        <h1>{failed ? "This report could not complete." : job.message}</h1>
        <p>{failed ? job.error?.message : "You can leave this page or close the tab. PaperForge will preserve this job and its latest progress."}</p>
        <div className="job-progress" role="progressbar" aria-label="Report generation progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={job.progress}><i style={{ width: `${job.progress}%` }} /></div>
        <div className="job-progress-meta"><strong>{job.progress}%</strong><span>{job.source_filenames.length} {job.source_filenames.length === 1 ? "source" : "sources"}</span></div>
        <div className="processing-actions">{failed ? <button className="button button-primary" onClick={onNewReport}>Start a new report</button> : <button className="button button-quiet" onClick={onLeave}>Work on something else</button>}</div>
      </div>
      <ol className="job-phases">
        {phases.map((phase, index) => {
          const complete = !failed && rank > index;
          const active = !failed && rank === index;
          return <li className={complete ? "complete" : active ? "active" : ""} key={phase.stage}><span>{complete ? <CheckIcon /> : String(index + 1).padStart(2, "0")}</span><div><strong>{phase.label}</strong><small>{active ? job.message : complete ? "Complete" : "Waiting"}</small></div></li>;
        })}
      </ol>
    </section>
  </main>;
}
