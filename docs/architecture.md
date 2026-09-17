# PaperForge Architecture

Version: 1.0

Author: Kalpesh Sharma

Date: July 2026

---

# Overview

PaperForge is an AI-powered research workspace that transforms a collection of research documents into professionally formatted reports.

Unlike traditional AI chat interfaces, PaperForge is built around an autonomous multi-agent pipeline that reads, organizes, synthesizes, and structures information before producing a polished document through SuperDocs.

The architecture is modular so that each component can evolve independently.

---

# High-Level Architecture

```
                   User
                     │
                     ▼
             React Frontend
                     │
             REST API (HTTP)
                     │
                     ▼
            FastAPI Backend
                     │
        ┌────────────┴────────────┐
        │                         │
        ▼                         ▼
 Document Processing        AI Agent Pipeline
        │                         │
        └────────────┬────────────┘
                     ▼
            Report Generation
                     │
                     ▼
            SuperDocs API
                     │
                     ▼
         Professional DOCX Report
```

---

# Request Flow

## Step 1 – Upload

The user uploads a research folder containing:

- PDF
- DOCX
- Markdown
- TXT

Future versions may support:

- Images
- Web URLs
- GitHub repositories

---

## Step 2 – Document Processing

PaperForge extracts raw text from every document.

Responsibilities:

- Detect file type
- Extract readable content
- Preserve metadata
- Remove unnecessary formatting
- Normalize text

Output:

```
Structured Research Documents
```

---

## Step 3 – AI Agent Pipeline

Instead of one large prompt, PaperForge uses specialized agents.

Planner Agent

↓

Determines processing strategy.

Knowledge Extraction Agent

↓

Finds facts, entities, dates, references and important ideas.

Research Synthesizer

↓

Groups similar ideas.

Removes duplicates.

Resolves conflicting information.

Report Writer

↓

Creates a structured report.

Formatter

↓

Prepares the document for SuperDocs.

---

# Configurable Report Contract

Report generation uses a versioned configuration with five independent parts:

- `report_structure`: preset plus an ordered list of enabled section keys and headings
- `content`: writing tone, intended audience and language
- `visual_theme`: template, page size, density and optional accent colour
- `citations`: citation style and bibliography policy
- `publication`: title, subtitle, author and institutional metadata

The composer still materializes typed evidence-aware section payloads, while the
service projects those payloads into the user-selected order and headings. HTML,
Markdown, PDF, and editable DOCX renderers consume the same immutable presentation model. This
lets later phases edit an outline or switch a theme without changing evidence or
regenerating report content.

Stored Phase 1 settings are upgraded to schema version 2 at the model boundary,
so existing projects and regeneration continue to work.

## Citation and quality projection

The PDF parser records one-based page character spans. Chunking projects those
spans into `page_number` and `page_end_number` metadata without changing chunk
text or identifiers. Citation formatting is a renderer-facing projection:
APA, IEEE, Harvard, and source-linked labels all retain the same raw chunk UUIDs.
Bibliography entries are deduplicated by source document.

A deterministic quality pass runs before artifacts are persisted and again
after report edits. It records support coverage and actionable issues in the
presentation model; it never invents evidence or rewrites report prose.

## Export and local cleanup

The HTML renderer remains the visual source for PDF output. A separate
`EditableDocxRenderer` creates a standard Word document with editable headings,
paragraphs, tables, provenance, bibliography, and page fields. SuperDocs review
continues to produce a separate reviewed DOCX.

Deleting a ready project removes its project row, related job rows, saved source
files, and generated artifact directory. Docker Compose mounts report storage at
`/data/reports`, keeping SQLite state and artifacts in one persistent volume.

---

# SuperDocs Integration

PaperForge uses the SuperDocs API as the final document generation layer.

Responsibilities:

- Professional formatting
- Heading hierarchy
- Lists
- Tables
- Document editing
- DOCX export

Future versions will integrate the MCP server for conversational editing.

Example:

User

"Expand section 3."

↓

PaperForge

↓

SuperDocs MCP

↓

Only that section changes.

---

# Folder Structure

```
paperforge/

backend/
    app/
        api/
        agents/
        services/
        models/
        utils/

frontend/

docs/

examples/

assets/
```

Each directory has a single responsibility.

---

# Why FastAPI?

FastAPI was selected because it provides:

- High performance
- Automatic OpenAPI documentation
- Strong typing
- Excellent async support
- Easy deployment
- Large ecosystem

The backend primarily orchestrates AI workflows rather than serving traditional CRUD operations.

---

# Why React?

The frontend requires:

- Drag-and-drop uploads
- Progress indicators
- Streaming status updates
- Interactive editing
- Responsive UI

React provides a mature ecosystem for building this experience.

---

# Why SuperDocs?

Most AI applications generate plain text.

PaperForge focuses on delivering production-ready documents.

SuperDocs provides:

- Document-aware editing
- Formatting preservation
- Structured document operations
- Future MCP integration
- High-quality DOCX generation

This lets PaperForge focus on research understanding while SuperDocs handles professional document editing.

---

# Design Principles

## Modular

Each component can evolve independently.

## AI-First

The workflow is driven by AI agents rather than rigid pipelines.

## API-Driven

Every major capability is exposed through clean service boundaries.

## Extensible

Support for OCR, citations, collaborative editing, and additional document types can be added without redesigning the system.

## Observable

Each stage of processing can be logged and monitored for debugging and future improvements.

---

# Future Architecture

Future versions will introduce:

- MCP-powered interactive editing
- Research memory
- Knowledge graph visualization
- Multi-user collaboration
- Authentication
- Cloud storage
- Background job queues
- Streaming report generation

The current architecture is intentionally designed so these features can be added without major restructuring.
