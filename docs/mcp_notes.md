# SuperDocs MCP Server Notes

Last Updated: July 2026

---

# Overview

The SuperDocs MCP (Model Context Protocol) Server allows AI agents to interact with documents directly through standardized tools instead of calling low-level REST endpoints.

Instead of manually constructing API requests, an AI agent can create, edit, inspect and manipulate documents through MCP.

This makes it ideal for autonomous AI workflows.

---

# What is MCP?

Model Context Protocol (MCP) is an open standard that lets AI models use external tools safely.

Instead of asking an LLM to rewrite an entire document, an agent can call specific tools like:

- Create document
- Read document
- Replace text
- Edit sections
- Apply formatting

The LLM reasons.

The MCP server performs the actions.

---

# Main Capabilities

## Document Editing

✓ Edit existing documents

✓ Rewrite paragraphs

✓ Insert new sections

✓ Delete content

✓ Replace text

✓ Preserve formatting

---

## Document Creation

Supported.

An agent can create a new document and populate it with generated content.

Useful for ResearchPilot.

---

## Section Editing

Supported.

The MCP server allows targeted edits instead of regenerating the whole document.

Example

Original

Introduction

Background

Conclusion

Agent

↓

Rewrite only the Background section.

Everything else remains unchanged.

---

## Paragraph Replacement

Supported.

Instead of replacing the entire document, an agent can:

- replace one paragraph
- insert below paragraph
- delete paragraph
- modify paragraph

This is significantly cheaper and faster.

---

## Formatting Preservation

One of SuperDocs' biggest advantages.

Edits preserve:

- headings
- bold
- italic
- lists
- tables
- spacing
- numbering

No copy-paste required.

---

# Agent Workflow

ResearchPilot

↓

Generate report

↓

Create SuperDocs document

↓

Allow user edits

↓

Agent edits only requested section

↓

Updated DOCX

---

# Why MCP is Useful

Traditional workflow

LLM

↓

Rewrite entire document

↓

Lose formatting

↓

User copies text

↓

Manual editing

---

SuperDocs MCP

LLM

↓

Reason

↓

Call MCP Tool

↓

Edit only required section

↓

Formatting preserved

---

# Possible Tools

Based on current documentation the MCP server exposes document-related operations such as:

✓ Create document

✓ Read document

✓ Edit document

✓ Replace content

✓ Insert content

✓ Delete content

✓ Apply formatting

(Exact tool names may evolve.)

---

# ResearchPilot Integration

Phase 1

FastAPI

↓

LLM

↓

SuperDocs REST API

↓

Formatted document

---

Phase 2

FastAPI

↓

Research Agent

↓

SuperDocs MCP Server

↓

Interactive editing

↓

DOCX

---

# Example Workflow

User

↓

Uploads research folder

↓

AI extracts knowledge

↓

Creates report

↓

SuperDocs creates document

↓

User says

"Expand section 3"

↓

ResearchPilot

↓

MCP Tool

↓

Only section 3 changes

---

# Advantages over REST

REST

- Better for one-shot document generation

MCP

- Better for interactive AI agents
- Incremental document editing
- Multi-step workflows
- Tool calling
- Agent autonomy

ResearchPilot should support both.

REST will power the initial report generation.

MCP will power follow-up edits.

---

# Project Decision

ResearchPilot MVP

✓ REST API for report generation

ResearchPilot V2

✓ MCP for conversational document editing

This separation keeps the MVP simple while demonstrating a clear roadmap toward autonomous document agents.