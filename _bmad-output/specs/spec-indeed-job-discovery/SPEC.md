---
id: SPEC-indeed-job-discovery
companions: ["job-source-evaluation.md", "../../project-context.md"]
sources: []
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability only — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# Automated Indeed Job Discovery

## Why

A pain to solve: the user is racing a 136-day UK Skilled Worker sponsorship deadline while also studying DSA, system design, and interview prep — bandwidth, not job-match scarcity, is the bottleneck. The motivating incident: job #18 (ASOS, 85/100 match) sat forgotten in `pending` for weeks despite the user's own roadmap milestone to "apply immediately to anything clearing the match threshold." Automating discovery is meant to buy back the hours currently spent manually searching, and to structurally reduce the chance of a good match going stale unnoticed — not to increase raw match volume, which the existing pipeline already handles well (14 of 25 jobs logged so far were already applied to manually).

## Capabilities

- **CAP-1**
  - **intent:** The system can discover new Indeed job postings (via the sanctioned Indeed MCP integration) matching the user's target criteria and hold them in a staging area, without inserting anything into the main `jobs` pipeline yet.
  - **success:** After a discovery run, newly found Indeed postings appear in the staging area with title, company, posted date, and apply link populated.

- **CAP-2**
  - **intent:** The user can browse staged, not-yet-promoted candidates in a new "Automate" section of the app, sorted by posted date with the newest first (since an older, un-acted-on posting has accrued more applicant competition).
  - **success:** The Automate view lists every staged candidate that is neither promoted nor dismissed, ordered newest-posted-first, each showing title, company, posted date, and apply link.

- **CAP-3**
  - **intent:** Selecting a staged candidate promotes it into the real job pipeline — fetching the full posting and running the same sponsor-check, salary-check, and match-score steps a manually pasted job goes through — and marks that staging entry as promoted so it cannot be shown or promoted again.
  - **success:** After selecting a staged candidate, a corresponding row exists in `jobs` with sponsor/salary/match verdicts populated, and its staging entry is flagged promoted.

- **CAP-4**
  - **intent:** The user applies to promoted jobs manually via the real apply link; the system never submits an application on the user's behalf.
  - **success:** No code path reachable from the Automate flow calls an apply/submit action; the apply link opens the real Indeed posting.

- **CAP-5**
  - **intent:** The discovery-and-staging step runs automatically on a daily recurring schedule by default, with an on-demand, live-session-triggered run as an explicit fallback when the schedule stalls or a fresh pull is wanted immediately — both triggers execute the same underlying logic.
  - **success:** A scheduled daily run and a manually triggered run both populate the same staging table via the same code path.

## Constraints

- The `jobs` table has no DB-level uniqueness (pre-existing, documented gap) — the staging table must itself track which Indeed job IDs have already been promoted, or a repeat search will re-offer or re-promote the same posting as a duplicate.
- Promoted candidates must run through the existing sponsor-check/salary-check/match-score pipeline unmodified — this feature is a new feed into that pipeline, not a fork of it.
- The Indeed MCP tool is reachable only from a Claude Code/claude.ai session, never from the deployed Streamlit app process. The discovery-and-staging step must therefore run outside the app (a scheduled agent or a live session) and write results to storage the app can read independently — the existing Turso-backed shared DB, consistent with this project's established cross-environment persistence pattern.

## Non-goals

- No automated application submission — applying stays a manual, human action on the real posting link.
- No integration with visasponsor.jobs — its own Terms of Service explicitly prohibit both automated access and combining its listings with other data sources, which is this feature's exact shape. See `job-source-evaluation.md`.
- No LinkedIn or Glassdoor discovery — only unofficial/community scrapers exist for either, and running one against the user's own logged-in account risks a ban. See `job-source-evaluation.md`.
- No change to the existing manual paste-in `jobs intake` flow — it continues to work exactly as today, untouched and independent of this feature.

## Success signal

The user opens the Automate section on any given day and finds new, sponsor-checked, match-scored Indeed candidates already waiting for review — populated by the prior scheduled run, without the user having manually searched Indeed. A high-match candidate is structurally less likely to go unnoticed the way job #18 did, because staged candidates surface on a fixed cadence rather than depending on the user remembering to look.

## Assumptions

- "ATS match score" refers to this codebase's existing `jobs/match_score.py` LLM-based scorer (0–100 integer, current `strong_match` threshold of 70) — there is no separate literal ATS/keyword-parser in this project, and none is introduced here.

## Open Questions

- What search terms/location/job-type should the daily Indeed query use by default — a fixed list, terms derived from the stored candidate profile/narrative-core, or user-configurable per run?
- Should the Automate view hard-filter to only show candidates scoring ≥ 85% match (the user's original framing), or show all discovered candidates with score visible and let the user set the bar themselves? The existing pipeline's own `strong_match` threshold is 70, not 85, and that gap has never been validated against real outcomes.
- Should staged-but-never-selected candidates expire or get cleaned up after some period, or persist indefinitely in the staging table?
- Where exactly does the daily scheduled routine run from, and does it need its own credentials/config to reach the shared Turso DB the same way the deployed app does?
