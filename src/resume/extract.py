"""LLM-based structured extraction from a pasted resume/CV.

This is a rarely-run step (once, or whenever the resume changes) that turns
free-text CV content into a structured candidate profile used by match
scoring (and later, tailoring) against job postings.
"""

from __future__ import annotations

from typing import Optional

import docx
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from google import genai
from pydantic import BaseModel

from llm_errors import GEMINI_CALL_EXCEPTIONS, raise_llm_call_failure

MODEL = "gemini-3.5-flash"

_MAX_SDT_DEPTH = 20  # defensive ceiling against pathological/adversarial nesting - real CV content controls are never nested this deep

_SYSTEM_INSTRUCTION = (
    "You extract a structured candidate profile from a pasted CV/resume, for "
    "an AI/ML/software engineering job seeker. Extract only what the resume "
    "actually supports - core_skills and domains should reflect real, "
    "demonstrated experience (projects, roles, tools actually used), not "
    "aspirational or inferred skills. seniority should be your best judgment "
    "from years of experience and role titles (e.g. junior, mid, senior, "
    "staff/lead). summary is a factual 2-3 sentence professional summary "
    "written in third person, suitable for comparing against job postings."
)


class ResumeProfile(BaseModel):
    full_name: Optional[str] = None
    years_experience: Optional[float] = None
    seniority: str
    core_skills: list[str]
    domains: list[str]
    past_roles: list[str]
    summary: str


def extract_profile(raw_resume_text: str, *, client: Optional[genai.Client] = None) -> ResumeProfile:
    """Extract a structured candidate profile from raw pasted resume text via Gemini."""
    client = client or genai.Client()
    try:
        interaction = client.interactions.create(
            model=MODEL,
            system_instruction=_SYSTEM_INSTRUCTION,
            input=raw_resume_text,
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": ResumeProfile.model_json_schema(),
            },
        )
        return ResumeProfile.model_validate_json(interaction.output_text)
    except GEMINI_CALL_EXCEPTIONS as exc:
        raise_llm_call_failure("Resume profile extraction failed", exc)


def _iter_sdt_unwrapped_children(parent_element, leaf_tags):
    """Walks `parent_element`'s direct children in document order, expanding
    any `w:sdt` (structured document tag / content control) wrapper element
    - an explicit stack, not recursion, so it can't raise `RecursionError`
    or hang on an arbitrarily deep `w:sdt` chain, and depth-capped at
    `_MAX_SDT_DEPTH` (a separate, narrower guarantee bounding how much of a
    pathologically/adversarially deep chain gets *read* - a data-loss
    containment measure, not what makes the walk itself safe to run) - to
    look for elements matching `leaf_tags` inside. Yields the matched leaf
    elements themselves, never the `w:sdt` wrapper. Generic core shared by
    the body-level, row-level, and cell-level walks below - the only
    difference between them is which tags count as leaf content."""
    sdt_tag = qn("w:sdt")
    sdt_content_tag = qn("w:sdtContent")

    stack = [(element, 0) for element in reversed(parent_element)]
    while stack:
        element, depth = stack.pop()
        tag = element.tag
        if tag in leaf_tags:
            yield element
        elif tag == sdt_tag and depth < _MAX_SDT_DEPTH:
            sdt_content = element.find(sdt_content_tag)
            if sdt_content is not None:
                stack.extend((child, depth + 1) for child in reversed(sdt_content))
        # any other element (w:sectPr, an over-depth w:sdt, content wrapped
        # in some other element like w:ins, ...) is skipped - not a leaf tag
        # the caller asked for, and not a w:sdt worth unwrapping


def _iter_body_content_including_sdt(document):
    """Order-preserving walk of the document body, like
    `document.iter_inner_content()`, extended to look inside a `w:sdt`
    wrapper found as a direct child of the body - python-docx's own public
    API skips them entirely (`CT_Body.inner_content_elements`'s xpath is
    `./w:p | ./w:tbl`, direct children only), yet Word's built-in resume/CV
    templates commonly wrap whole sections in content controls this way."""
    p_tag = qn("w:p")
    tbl_tag = qn("w:tbl")
    for element in _iter_sdt_unwrapped_children(document.element.body, {p_tag, tbl_tag}):
        yield Paragraph(element, document) if element.tag == p_tag else Table(element, document)


def _iter_table_tr_elements(tbl_element):
    """Yields each `<w:tr>` in `tbl_element` (a `<w:tbl>`), in document
    order, including rows wrapped in `w:sdt` - python-docx's own
    `Table.rows` only sees direct `<w:tr>` children."""
    yield from _iter_sdt_unwrapped_children(tbl_element, {qn("w:tr")})


def _table_has_any_sdt_wrapping(tbl_element) -> bool:
    """True if any `<w:tr>` row, or any `<w:tc>` cell inside a direct row,
    is itself `w:sdt`-wrapped anywhere in `tbl_element` (i.e. is not a
    plain direct `<w:tr>`/`<w:tc>` child) - NOT true merely because a row
    contains an sdt-wrapped cell, that IS the case this returns True for;
    a `w:sdt` wrapping only an in-cell *paragraph* does not trip this,
    since paragraph-level wrapping can't affect `grid_offset`/tr-tc
    ancestry the way row/cell-level wrapping does. Computed once per table
    (see `extract_text_from_docx`) and used to decide, for the WHOLE table
    at once, whether python-docx's own grid-offset/vMerge machinery can be
    trusted at all - see `_iter_row_tc_elements` for why a per-row/per-cell
    version of this check turned out not to be safe enough. Only checks
    for `w:sdt` specifically, matching this module's existing scope (the
    body-level fix's own non-goal on `w:ins`/other wrapper elements) - a
    table using one of those other wrapper types around a row/cell could
    still hit the same underlying python-docx trap undetected; considered
    out of scope here for the same reason. Nested tables inside a cell are
    also out of scope (matching `_cell_text`'s exclusion) and can't
    confuse this function: a nested `<w:tbl>`'s own rows live inside a
    `<w:tc>`, never mistaken for this table's direct `<w:tr>` children.
    Bounded by the same `_MAX_SDT_DEPTH` as extraction itself, so a row or
    cell buried past the cap is invisible to this check exactly as it's
    invisible to extraction - the two are consistent about what "exists"
    in the same way, not a separate blind spot."""
    tr_tag = qn("w:tr")
    direct_trs = tbl_element.findall(tr_tag)
    if len(direct_trs) != sum(1 for _ in _iter_sdt_unwrapped_children(tbl_element, {tr_tag})):
        return True  # a row itself is sdt-wrapped
    tc_tag = qn("w:tc")
    return any(
        len(tr.findall(tc_tag)) != sum(1 for _ in _iter_sdt_unwrapped_children(tr, {tc_tag}))
        for tr in direct_trs
    )


def _iter_row_tc_elements(tr_element, *, vmerge_resolution_is_safe: bool):
    """Yields each cell's `<w:tc>` in `tr_element` (a `<w:tr>`), in document
    order, including cells wrapped in `w:sdt`. When `vmerge_resolution_is_safe`,
    also resolves a vertically-merged continuation cell
    (`w:tcPr/w:vMerge="continue"`) to the `<w:tc>` that actually holds its
    content - exactly python-docx's own `_Row.cells` behavior for a table
    with no `w:sdt` wrapping anywhere.

    `vmerge_resolution_is_safe` is computed once per table (see
    `_table_has_any_sdt_wrapping`), not per row or per cell - a first
    attempt at a narrower, per-row guard turned out not to be safe. `CT_Tc`'s
    own `_tc_above`/`_tr_above`/`grid_offset` machinery walks `preceding-sibling`
    xpaths that assume every `<w:tr>` is a direct `<w:tbl>` child and every
    `<w:tc>` is a direct `<w:tr>` child; confirmed via live repro that once
    ANY row or cell in a table is `w:sdt`-wrapped, that assumption can break
    for OTHER, seemingly unrelated rows too - not just raising `ValueError`
    (e.g. "no tr above topmost tr in w:tbl" when a wrapped row sits between
    two unwrapped ones) but in one case silently resolving to a sibling
    cell's content instead of the true cell above, with no exception at
    all. Given real resolution can silently misfire in ways smaller,
    row-local guards didn't catch, this treats "any `w:sdt` use anywhere in
    the table" as disqualifying vMerge resolution for the WHOLE table, not
    just the specific row or chain involved - a wider, but definitely
    correct, residual: a genuinely unrelated vertical merge elsewhere in a
    table that also happens to use content controls stops repeating its
    content, in exchange for zero risk of ever fabricating a wrong cell's
    text or crashing the whole document's extraction.

    Does not expand a horizontal span (`gridSpan`) into repeated grid
    positions the way python-docx's own `_Row.cells` does (that exists only
    so a caller can reconstruct a rectangular grid) - a physical merge
    (`.merge()`) collapses to one `<w:tc>` with `w:gridSpan` in the real
    XML (the other `<w:tc>` is deleted), so each physical `<w:tc>` already
    contributes exactly once, with no dedup needed.

    `tc.getparent().tag == tr_tag` below is redundant defense-in-depth when
    `vmerge_resolution_is_safe` is True: `_table_has_any_sdt_wrapping`
    having already returned False for this table guarantees every `tc`
    reached here already has a `<w:tr>` parent. Kept anyway - cheap, and
    correct on its own even if the table-level check's guarantee ever
    changed."""
    tr_tag = qn("w:tr")
    for tc in _iter_sdt_unwrapped_children(tr_element, {qn("w:tc")}):
        if vmerge_resolution_is_safe and tc.getparent().tag == tr_tag and tc.vMerge == "continue":
            yield tc._tc_above
        else:
            yield tc


def _cell_text(tc_element) -> str:
    """A `<w:tc>` cell's text: every paragraph inside it (including ones
    wrapped in `w:sdt`), newline-joined - mirrors python-docx's own
    `_Cell.text` property (`"\\n".join(p.text for p in self.paragraphs)`)
    exactly, just sdt-aware. Nested tables inside a cell are out of scope,
    matching this module's existing nested-table exclusion. `Paragraph`'s
    second argument is normally a parent (for `.part`-dependent features
    like images/hyperlinks) - passed `None` here since only `.text` is
    ever read, which resolves purely from the element tree and never
    touches `.part`."""
    return "\n".join(Paragraph(p, None).text for p in _iter_sdt_unwrapped_children(tc_element, {qn("w:p")}))


def _row_text(tr_element, *, vmerge_resolution_is_safe: bool) -> Optional[str]:
    """One table row (a `<w:tr>` element) as a ' | '-joined line, including
    any sdt-wrapped cells and sdt-wrapped in-cell paragraphs, flattening
    each cell's internal newlines to spaces so a cell's content never gets
    mistaken for a row/paragraph boundary. Returns None for an all-blank
    row (e.g. an unfilled template table) so it doesn't inject a stray
    separator into a document that otherwise has no real content."""
    cell_texts = [
        _cell_text(tc).replace("\n", " ")
        for tc in _iter_row_tc_elements(tr_element, vmerge_resolution_is_safe=vmerge_resolution_is_safe)
    ]
    if not any(text.strip() for text in cell_texts):
        return None
    return " | ".join(cell_texts)


def extract_text_from_docx(file) -> str:
    """Pull raw text out of a .docx file: paragraphs and table content, in
    original document order (not paragraphs-then-tables), since a CV can
    interleave prose with a skills/dates table - including a paragraph,
    table, table row, table cell, or in-cell paragraph wrapped in a `w:sdt`
    content control, at any nesting depth up to `_MAX_SDT_DEPTH` (see
    `_iter_sdt_unwrapped_children`). A table that uses `w:sdt` anywhere in
    it loses vertical-merge content repetition for the whole table (see
    `_iter_row_tc_elements`) - a suppressed continuation cell then renders
    as a blank column between ` | ` separators, indistinguishable in the
    output from a source cell that was genuinely empty; accepted, since
    disambiguating the two would need a sentinel value with nowhere
    meaningful to go (this text feeds straight into Gemini profile
    extraction, not a UI). Headers, footers, and text boxes are not read -
    rarer in CVs and a different python-docx API."""
    document = docx.Document(file)
    lines: list[str] = []
    for item in _iter_body_content_including_sdt(document):
        if isinstance(item, Table):
            vmerge_resolution_is_safe = not _table_has_any_sdt_wrapping(item._tbl)
            lines.extend(
                text
                for tr in _iter_table_tr_elements(item._tbl)
                if (text := _row_text(tr, vmerge_resolution_is_safe=vmerge_resolution_is_safe)) is not None
            )
        else:
            lines.append(item.text)
    return "\n".join(lines)
