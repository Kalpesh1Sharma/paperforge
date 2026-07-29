"""Reserved prompt constants for future report-generation providers."""

REPORT_SYNTHESIS_SYSTEM_PROMPT = ""
REPORT_SYNTHESIS_USER_PROMPT = ""

DOCUMENT_SYNTHESIS_PROMPT = """\
You synthesize a research report using only the supplied deterministic report and
knowledge objects. Return JSON only: exactly one valid JSON object and no other
text, Markdown, or code fences.

Do not use external knowledge. Do not hallucinate or invent facts, provenance,
sections, or claims. Do not use marketing language or opinions. Every statement
must be factually grounded in the supplied knowledge objects.

The executive_summary must contain two to four non-empty paragraphs separated
by a blank line ("\\n\\n" in the JSON string). Every finding and section must
include one or more supporting_chunk_ids from the supplied knowledge objects.
Omit a finding or section when valid provenance cannot be established.

Create only document-supported sections. Suitable section headings may include
Professional Experience, Projects, Technical Skills, Achievements, or Research
Contributions when the supplied knowledge supports them. Do not create empty or
unsupported sections.

Return this exact JSON shape:
{
  "executive_summary": "Two to four grounded paragraphs.",
  "findings": [
    {
      "title": "Grounded finding title",
      "description": "Grounded finding description",
      "supporting_chunk_ids": ["source-chunk-uuid"]
    }
  ],
  "sections": [
    {
      "heading": "Grounded section heading",
      "content": "Grounded section content",
      "supporting_chunk_ids": ["source-chunk-uuid"]
    }
  ]
}
"""
