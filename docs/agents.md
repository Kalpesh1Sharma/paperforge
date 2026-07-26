# PaperForge Agent System

Version: 1.0

Author: Kalpesh Sharma

Date: July 2026

---

# Overview

PaperForge uses a multi-agent architecture instead of relying on a single LLM prompt.

Each agent owns one responsibility and passes structured outputs to the next agent.

Benefits:

- Better reasoning
- Easier debugging
- More modular architecture
- Higher quality outputs
- Easier future improvements

---

# Agent Pipeline

```
Upload Research Folder
          │
          ▼
   Planner Agent
          │
          ▼
   Parser Agent
          │
          ▼
Knowledge Extraction Agent
          │
          ▼
Research Synthesizer
          │
          ▼
   Report Writer
          │
          ▼
SuperDocs Formatter
          │
          ▼
 Professional DOCX
```

---

# 1. Planner Agent

## Responsibility

Understand the uploaded workspace and create an execution plan.

Instead of processing every document identically, the planner decides how each file should be handled.

---

### Input

- Uploaded folder
- File metadata
- File types

---

### Tasks

- Detect document types
- Prioritize processing order
- Ignore unsupported files
- Build execution plan

---

### Output

```json
{
  "documents": [
    {
      "type": "pdf",
      "priority": "high"
    }
  ]
}
```

---

### Failure Handling

If a file cannot be processed:

- Skip the file
- Record the error
- Continue processing

---

# 2. Parser Agent

## Responsibility

Extract readable text from every supported document.

---

### Input

Execution plan

Research documents

---

### Supported Files

- PDF
- DOCX
- Markdown
- TXT

Future

- Images (OCR)
- HTML
- URLs

---

### Tasks

- Read document
- Extract text
- Preserve metadata
- Normalize formatting

---

### Output

```json
{
  "document": "...",
  "text": "...",
  "pages": 18
}
```

---

### Failure Handling

- Corrupted PDF
- Empty document
- Unsupported encoding

Skip failed files while logging the error.

---

# 3. Knowledge Extraction Agent

## Responsibility

Transform raw text into structured knowledge.

---

### Input

Parsed documents

---

### Tasks

Extract

- Facts
- Entities
- Dates
- Metrics
- References
- Definitions
- Important quotes

Remove

- Boilerplate
- Duplicate text
- Headers
- Footers

---

### Output

```json
{
  "facts": [],
  "entities": [],
  "references": []
}
```

---

### Failure Handling

If extraction confidence is low:

- Retry with refined prompt
- Flag uncertain results
- Continue pipeline

---

# 4. Research Synthesizer

## Responsibility

Merge knowledge from multiple documents into one coherent understanding.

---

### Input

Extracted knowledge

---

### Tasks

- Remove duplicates
- Resolve conflicting information
- Group related topics
- Build relationships
- Organize information

---

### Output

```json
{
  "themes": [],
  "timeline": [],
  "insights": []
}
```

---

### Failure Handling

If conflicting evidence exists:

Include both viewpoints in the final report.

Never silently discard information.

---

# 5. Report Writer

## Responsibility

Generate a professional report from structured research.

---

### Input

Synthesized knowledge

---

### Tasks

Create:

- Executive Summary
- Background
- Findings
- Insights
- Risks
- Open Questions
- References

---

### Output

Markdown or HTML report

---

### Failure Handling

If required sections are missing:

Generate placeholders instead of failing.

Example:

> "No significant risks identified."

---

# 6. SuperDocs Formatter

## Responsibility

Convert the generated report into a professionally formatted document.

---

### Input

HTML / Markdown

---

### Tasks

- Apply formatting
- Build heading hierarchy
- Preserve spacing
- Create lists
- Prepare DOCX
- Export final document

Future:

Support conversational editing through the SuperDocs MCP Server.

---

### Output

Professional DOCX

---

### Failure Handling

If SuperDocs API is unavailable:

- Retry automatically
- Save intermediate report
- Notify the user

---

# Communication Model

Agents communicate using structured JSON rather than natural language.

Example

Planner

↓

```json
{
  "documents":[]
}
```

↓

Parser

↓

```json
{
  "parsed_documents":[]
}
```

↓

Knowledge Extraction

↓

```json
{
  "facts":[]
}
```

This makes the system predictable and easier to debug.

---

# Why Multi-Agent?

A single LLM prompt becomes difficult to maintain as complexity grows.

PaperForge separates reasoning into specialized agents.

Advantages:

- Better maintainability
- Better observability
- Easier testing
- Independent improvements
- Lower hallucination risk
- Clear responsibilities

---

# Future Agents

Future versions may introduce:

- Citation Verification Agent
- Fact Checking Agent
- Research Memory Agent
- Literature Review Agent
- Knowledge Graph Agent
- Translation Agent
- Reviewer Agent

The current architecture is designed so additional agents can be added without modifying the existing pipeline.