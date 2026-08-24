---
id: SPEC-automate-queue-triage
companions: []
sources: []
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability only — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# Automate queue triage control

## Why

A pain to solve. The Indeed discovery queue has accumulated 92 unreviewed rows (verified live 2026-08-24) and the Automate page offers no way to act on more than one at a time — its only controls are a per-row "Apply on Indeed" link and a per-row "Mark Reviewed" button. The bulk path already exists as `jobs triage-discovery` (`src/jobs/cli.py:1114`), but reaching it means leaving the app for a terminal, which is the opposite of what a "too busy to review often" feature should ask of a user racing a sponsorship deadline. The backlog is now large enough that the queue's ranking no longer helps: the page renders 20 rows and the other 72 are invisible.

## Capabilities

- **CAP-1**
  - **intent:** From the Automate page, the user can preview how the entire unreviewed queue would split at a match-score threshold, before anything changes.
  - **success:** With 92 unreviewed rows and threshold 85, the preview reports keep 13 / discard 78 / unscored 1 — counts spanning the whole queue, not the 20 rows the page renders — and no row's `applied_status` changes.

- **CAP-2**
  - **intent:** After seeing the preview, the user can commit it in a second, distinct action that discards the below-threshold rows.
  - **success:** Committing sets `applied_status = 'discarded'` on exactly the previewed discard set; those rows leave `list_discovery_queue` and become visible under the Jobs List page's Discarded filter, while keep and unscored rows are untouched.

- **CAP-3**
  - **intent:** Rows that were never scored are reported and left in the queue rather than swept up by a bulk discard.
  - **success:** A queue containing a `match_score IS NULL` row, triaged at any threshold, leaves that row's `applied_status` NULL and names it in the preview's own left-in-queue count.

- **CAP-4**
  - **intent:** The control states how many rows it considered, so a capped display can never read as a completed triage.
  - **success:** The rendered result names the total queue size acted on (92), distinct from the number of rows displayed on the page (20).

## Constraints

- The control acts on the entire unreviewed queue, not the page's 20-row display window. `list_discovery_queue` defaults to `limit=20` and `views/automate.py:69` passes no limit; `triage-discovery --limit` also defaults to 20. A control wired to those defaults would discard 7 of the 78 below-threshold rows and appear finished — the silent-partial-action failure this codebase spent commit `851a151` correcting.
- Preview and commit are two separate user actions. `_cmd_triage_discovery` is dry-run by default because it is the one batch mutation no human inspects row by row, and `data/*.db` has no backup (see `project-context.md` → Durability). A single-click apply would discard that safety.
- Discarding means `mark_discarded` setting `applied_status = 'discarded'` — recoverable and still readable under the Jobs List Discarded filter. Never a `DELETE`: a wrong threshold must cost a `WHERE` clause, not data.
- Unscored rows are never discarded at any threshold. A NULL `match_score` is an absence of information, not a low score — the stated purpose of `partition_discovery_queue`'s third bucket.
- Triage performs no scoring and makes no LLM call. It is a pure partition over already-stored `match_score` values.

## Non-goals

- Not invoking tailoring from the triage flow. `_cmd_triage_discovery` deliberately prints `tailor-docx` as a ready-to-run command instead of calling it, because `tailor-docx` holds a per-job advisory lock precisely because concurrent runs race; firing a batch unattended is a different feature with a different failure mode.
- Not changing `DISCOVERY_TRIAGE_THRESHOLD`'s value, nor introducing any hard filter into the queue's own display — the queue ranks and never hides, per `spec-indeed-job-discovery.md`'s Design Notes.
- Not building an undo or bulk-restore control. The Jobs List Discarded filter is the recovery path.
- Not modifying `jobs triage-discovery`'s own CLI behavior, flags, or output.

## Success signal

A user opens Automate, sees the queue is 92 deep rather than the 20 on screen, previews a threshold, and clears the backlog to 14 rows in a second click — then names any discarded row and finds it intact under Jobs List's Discarded filter.

## Assumptions

- The control renders on `views/automate.py` above the queue listing, since it describes the queue as a whole rather than any single row.
- Preview state survives the `st.rerun()` that follows a Streamlit mutating action, so the commit acts on the set the user actually saw.

## Open Questions

- Should the threshold be fixed at `DISCOVERY_TRIAGE_THRESHOLD` (85) or adjustable in the UI? Neither 85 nor the project's other `strong_match` threshold of 70 has been validated against real interview outcomes, and the two produce materially different splits on the current queue (discard 78 vs 69).
