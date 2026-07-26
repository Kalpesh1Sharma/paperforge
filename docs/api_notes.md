# SuperDocs API Notes

Last Updated: July 2026

---

# Overview

SuperDocs provides multiple ways to interact with documents:

1. REST API
2. MCP Server
3. Browser Editor SDK

For ResearchPilot we'll primarily use the REST API, with MCP as a future enhancement.

---

# Base URL

https://api.superdocs.app

(Some lower-level SuperDoc document APIs are documented separately under api.superdoc.dev.)

---

# Authentication

Bearer Token

Example

Authorization: Bearer <SUPERDOCS_API_KEY>

Store the key in:

SUPERDOCS_API_KEY

Never hardcode it.

---

# Main Workflow

ResearchPilot

↓

Extract text from uploaded research files

↓

Generate report with LLM

↓

Send report to SuperDocs

↓

Receive edited/formatted document

↓

Download DOCX

---

# Main Endpoint

POST /v1/chat

Purpose

Edit or transform a document using natural-language instructions.

Example Request

{
  "message": "Generate a professional research report.",
  "session_id": "research-001",
  "document_html": "<h1>Draft</h1>...",
  "approval_mode": "approve_all"
}

Response

Updated document HTML.

---

# Sessions

session_id

Every document edit belongs to a session.

Useful because:

- multiple edits
- conversation history
- incremental editing

ResearchPilot should create one session per report.

---

# Input Formats

Current API examples primarily use:

- HTML

The backend should therefore:

Research files

↓

Extract text

↓

Generate HTML

↓

Send HTML to SuperDocs

---

# Output

Current API returns

Updated HTML

ResearchPilot will:

Updated HTML

↓

Convert to DOCX (using SuperDocs workflow)

↓

User downloads report

---

# Approval Modes

approve_all

Automatically applies edits.

Useful for automated pipelines like ResearchPilot.

Future

Human approval before applying edits.

---

# Authentication Notes

Environment Variable

SUPERDOCS_API_KEY

Example

Authorization: Bearer <API_KEY>

---

# Error Handling

Need to handle

401 Unauthorized

• Invalid API key

400 Bad Request

• Invalid request body

429 Rate Limited

• Retry with exponential backoff

5xx

• Retry
• Log request
• Notify user

---

# Rate Limits

No explicit public limits documented.

Assume

- retry strategy
- exponential backoff
- request timeout

---

# Project Decisions

ResearchPilot will

✓ Use FastAPI

✓ Use REST API

✓ Use HTML as intermediate format

✓ Create one session per report

✓ Store API key in .env

✓ Retry failed requests

✓ Keep SuperDocs integration isolated in

services/superdocs.py

---

# Future Improvements

- MCP support
- Streaming updates
- Human approval workflow
- Collaborative editing
- Multiple export formats