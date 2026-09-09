import { ArrowRightIcon, CheckIcon, FileIcon, SparkIcon } from "./Icons";
import { Brand } from "./Brand";

type Props = { onOpenApp: () => void; connection: "checking" | "connected" | "unavailable" };

const workflow = ["Add your sources", "Shape the outline", "Review every claim", "Export with confidence"];

export function LandingPage({ onOpenApp, connection }: Props) {
  return (
    <div className="marketing-page">
      <nav className="marketing-nav" aria-label="Primary navigation">
        <Brand />
        <div className="marketing-links">
          <a href="#workflow">Workflow</a>
          <a href="#evidence">Evidence</a>
          <button className="button button-quiet nav-workspace-button" type="button" aria-label="Open workspace" onClick={onOpenApp}><span className="desktop-cta">Open workspace</span><span className="mobile-cta">Open app</span></button>
        </div>
      </nav>

      <main>
        <section className="hero">
          <div className="hero-copy">
            <div className="signal-pill"><SparkIcon /> Built for source-grounded work</div>
            <h1>From scattered reading to a report worth submitting.</h1>
            <p className="hero-lede">PaperForge transforms your PDFs into a structured research report while keeping the evidence close enough to inspect.</p>
            <div className="hero-actions">
              <button className="button button-primary button-large" onClick={onOpenApp}>Create a report <ArrowRightIcon /></button>
              <span className={`service-note service-note--${connection}`}><i />{connection === "connected" ? "Workspace ready" : connection === "checking" ? "Checking workspace" : "Local workspace offline"}</span>
            </div>
          </div>

          <div className="hero-product" aria-label="PaperForge report workspace preview">
            <div className="preview-glow" />
            <div className="product-window">
              <div className="window-bar"><span /><span /><span /><b>Research workspace</b></div>
              <div className="window-body">
                <aside className="mini-outline">
                  <strong>REPORT OUTLINE</strong>
                  <span className="active">01&nbsp;&nbsp;Abstract</span>
                  <span>02&nbsp;&nbsp;Background</span>
                  <span>03&nbsp;&nbsp;Methodology</span>
                  <span>04&nbsp;&nbsp;Findings</span>
                  <span>05&nbsp;&nbsp;References</span>
                </aside>
                <article className="mini-document">
                  <div className="document-kicker">RESEARCH REPORT · 2026</div>
                  <h2>Responsible AI in public research</h2>
                  <p className="document-deck">An evidence-led review of adoption, governance, and emerging practice.</p>
                  <div className="document-rule" />
                  <h3>Abstract</h3>
                  <p>Recent studies point to a widening gap between experimentation and institutional readiness.<sup>1</sup></p>
                  <div className="evidence-callout"><CheckIcon /><span><strong>Supported claim</strong>3 source passages linked</span></div>
                </article>
                <aside className="mini-evidence">
                  <strong>EVIDENCE</strong>
                  <div><FileIcon /><span><b>policy-review.pdf</b><small>Page 14</small></span></div>
                  <div><FileIcon /><span><b>field-notes.pdf</b><small>Page 6</small></span></div>
                  <div className="confidence"><span>Coverage</span><b>92%</b></div>
                </aside>
              </div>
            </div>
          </div>
        </section>

        <section className="workflow-section" id="workflow">
          <div className="section-intro"><span>THE WORKFLOW</span><h2>Research stays rigorous.<br />The busywork disappears.</h2></div>
          <ol className="workflow-grid">
            {workflow.map((item, index) => <li key={item}><span>0{index + 1}</span><h3>{item}</h3><p>{[
              "Upload an ordered set of research PDFs without losing source identity.",
              "Turn extracted knowledge into a clear, inspectable report structure.",
              "Trace important findings back to the documents that support them.",
              "Download a publication-ready report and keep an editable record."
            ][index]}</p></li>)}
          </ol>
        </section>

        <section className="evidence-section" id="evidence">
          <div><span className="section-label">EVIDENCE, NOT JUST ANSWERS</span><h2>Every useful finding should have somewhere to point.</h2></div>
          <p>PaperForge preserves document identity through extraction, synthesis, and publication—so the final report remains connected to the material behind it.</p>
          <button className="button button-inverse" onClick={onOpenApp}>Open PaperForge <ArrowRightIcon /></button>
        </section>
      </main>

      <footer className="marketing-footer"><Brand compact /><span>Grounded document intelligence.</span><span>Built by Kalpesh Sharma</span></footer>
    </div>
  );
}
