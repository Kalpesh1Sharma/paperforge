# PaperForge Roadmap

Version: 1.0

Author: Kalpesh Sharma

Date: July 2026

---

# Vision

PaperForge aims to become an AI-powered research workspace that transforms scattered documents into professional, editable reports through autonomous AI agents and SuperDocs.

Development is organized into iterative phases, with each phase delivering a complete, usable improvement.

---

# Phase 1 — MVP

**Goal:** Build a complete end-to-end research-to-report workflow.

## Core Infrastructure

- Repository setup
- Documentation
- Docker environment
- Environment configuration
- Logging

## Backend

- FastAPI project
- File upload API
- Document parser
- Agent orchestration
- Report generation pipeline

## Supported Documents

- PDF
- DOCX
- Markdown
- TXT

## AI

- Planner Agent
- Knowledge Extraction Agent
- Research Synthesizer
- Report Writer

## SuperDocs

- REST API integration
- Professional document formatting
- DOCX export

## Frontend

- React application
- Folder upload
- Progress tracking
- Report download

---

# Phase 2 — Professional Templates and Polished Reports

**Goal:** Make report content, structure and visual presentation independently configurable.

## Batch 6 — Configurable report model (implemented)

- Versioned schema-v2 report settings
- Independent structure, content, visual theme, citation and publication models
- Configurable ordered sections and headings
- Title, subtitle, author, organisation, university, department and publication type
- Automatic migration for Phase 1 settings and reports

## Batch 7 — Three initial formats

**Status: complete.** Classic Academic, Modern Research, and IEEE-Inspired
Technical now use separate render assets and produce distinct HTML/PDF layouts.

- Classic Academic
- Modern Research
- IEEE-Inspired Technical

## Batch 8 — Outline approval

**Status: complete.** PDF evidence is scanned before generation, proposals are
persisted, evidence availability is shown per section, and edited section order
and headings must receive explicit revision-bound approval before generation.

- Proposed sections and evidence availability
- Add, remove, rename and reorder before generation

## Batch 9 — Editing

**Status: complete.** Saved presentation sections now have editable prose and
approval locks, assisted transforms use the configured provider chain with a
deterministic fallback, and all three professional formats can be switched by
rerendering the same revisioned content model.

- Section editing, targeted rewrites and locks
- Template switching without content regeneration

## Batch 10 — Citations and quality checks

**Status: complete.** PDF page positions now survive parsing and chunking,
source evidence supports APA/IEEE/Harvard/source-linked display with a managed
bibliography, and persisted quality results identify unsupported claims,
empty sections, missing bibliography entries, and formatting risks.

- Page-preserving citations, APA, IEEE and Harvard bibliography formatting
- Unsupported-claim, missing-section and formatting checks

## Batch 11 — Export and deployment

**Status: complete.** Each report now includes a normal editable DOCX alongside
the polished PDF, project deletion removes associated local artifacts and job
records, and the repository includes production-style backend/frontend Docker
images, Compose orchestration, a keyless demo profile, and deployment guidance.

- Polished PDF and editable DOCX
- Docker, cleanup, deployment and public demo workflow

---

# Phase 3 — Research Workspace

**Goal:** Support larger and collaborative research workflows.

## Collaboration

- Authentication
- User accounts
- Team workspaces
- Shared projects

## Templates

- Literature Review
- Technical Report
- Product Requirements Document
- Whitepaper
- Meeting Notes
- Research Proposal

## Integrations

- Google Drive
- GitHub
- Notion
- Dropbox

## Storage

- Cloud storage
- Version history
- Automatic backups

---

# Phase 4 — Autonomous Research Platform

**Goal:** Build an AI research operating system.

## Agent Ecosystem

- Reviewer Agent
- Fact Checker Agent
- Citation Verification Agent
- Knowledge Graph Agent
- Translation Agent

## Intelligence

- Long-term research memory
- Knowledge graph visualization
- Cross-project learning
- Automatic research updates

## Enterprise

- Multi-organization support
- RBAC
- Audit logs
- API keys
- Webhooks

---

# Long-Term Vision

PaperForge evolves from a report generator into an AI-powered research platform capable of:

- Understanding large collections of documents
- Maintaining persistent research memory
- Collaborating with users through AI agents
- Producing publication-quality documents
- Supporting continuous document refinement through SuperDocs and MCP

Rather than replacing researchers, PaperForge aims to automate repetitive document work so users can focus on analysis, decision-making, and creativity.
