"""Reserved prompt constants for future report-generation providers."""

REPORT_SYNTHESIS_SYSTEM_PROMPT = ""
REPORT_SYNTHESIS_USER_PROMPT = ""

DOCUMENT_SYNTHESIS_PROMPT = """\
You refine a research report using only the supplied deterministic report,
knowledge objects, and ordered refinement_candidates. Return JSON only: exactly
one valid JSON object and no other text, Markdown, or code fences.

Do not use external knowledge. Do not hallucinate or invent facts, provenance,
sections, claims, or finding groups. Do not use marketing language or opinions.
Every statement must be factually grounded in the supplied knowledge objects.

The refinement_candidates are canonical and exhaustive. Do not add, remove,
merge, split, reorder, or otherwise change those candidate groups. You may
optionally improve the title and description of an existing candidate through a
finding_rewrites item. A rewrite must use an existing candidate_id at most once
and must repeat that candidate's supporting_chunk_ids exactly, in the supplied
order. Omit a candidate from finding_rewrites to preserve its deterministic
wording. Do not return a rewrite when the evidence does not support a clearer
wording.

The executive_summary must contain two to four non-empty paragraphs separated
by a blank line ("\\n\\n" in the JSON string). Create only document-supported
sections. Every section must include one or more supporting_chunk_ids from the
supplied knowledge objects. Omit a section when valid provenance cannot be
established.

Return this exact JSON shape:
{
  "executive_summary": "Two to four grounded paragraphs.",
  "finding_rewrites": [
    {
      "candidate_id": "finding-0001",
      "title": "Grounded improved finding title",
      "description": "Grounded improved finding description",
      "supporting_chunk_ids": ["exact-candidate-source-chunk-uuid"]
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
