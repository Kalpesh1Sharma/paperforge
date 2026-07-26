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

# Report Structure

The generated report follows a consistent format.

- Executive Summary
- Background
- Key Findings
- Insights
- Risks
- Open Questions
- References

This structure can later support templates for different report types.

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