---
project_name: 'AI Sponsorship Job Acquisition Platform'
user_name: 'Owner'
date: '2026-07-11'
sections_completed: ['technology_stack', 'language_specific_rules', 'framework_specific_rules', 'testing_rules', 'code_quality_style_rules', 'development_workflow_rules', 'critical_dont_miss_rules']
status: 'complete'
rule_count: 27
optimized_for_llm: true
mcp_note_added: true
existing_patterns_found: 24
---

# Project Context for AI Agents

_This file contains critical rules and patterns that AI agents must follow when implementing code in this project. Focus on unobvious details that agents might otherwise miss._

---

## Technology Stack & Versions

**Core Technologies:**
- Python ≥3.10, `uv` package manager (uv.lock committed), hatchling build backend
- Streamlit (UI layer, `st.navigation`/`st.Page` routing)
- `google-genai` (Gemini) — model `"gemini-3.5-flash"` hardcoded **identically in 3 files** (`jobs/extract.py`, `jobs/tailor.py`, `jobs/outreach.py`), no shared constant. **Rule: grep all 3 before bumping the model version — a partial bump silently splits the pipeline across two model versions.**
- Raw `sqlite3` (no ORM) — 4 independent DB files under `data/`: `sponsors.db`, `jobs.db`, `profile.db`, `roadmap.db`

**Key Dependencies:**
- `pydantic>=2.0` (unbounded) — used for LLM response schemas via `.model_json_schema()` at all 3 Gemini call sites. **Rule: pydantic minor version bumps can change generated schema shape — retest all 3 LLM call sites after any bump, not just run the test suite.**
- `python-dotenv` — loads `.env` at both `app.py` and CLI entry points. Only `GEMINI_API_KEY` is currently read; **no `.env.example` exists**, so a new env var has no discoverable place to be documented — update this file's rules, not just `.env`, when adding one.
- `python-docx` — resume/cover-letter generation (`docx_tailor.py`)
- `mcp>=1.28.1` — MCP SDK (`FastMCP`), used only by `mcp_server/server.py`
- `pytest>=8.0` (dev-only dependency)
- **No ruff/black/mypy configured** — there is no automated gate. An agent must actually run the test suite to call something done; nothing else will catch a mistake before it ships.

**Known gap (not yet fixed, just documented):** `extract.py`/`tailor.py` have no handling for a Gemini response that fails pydantic validation — raw `ValidationError` propagates to the Streamlit UI. Only `outreach.py` has a purpose-built exception (`OutreachLengthError`) for its specific failure mode (channel length cap). Don't assume the same safety net exists in the other two.

**MCP integration (implemented, see `src/mcp_server/`):** exposes the pipeline as four MCP tools — `check_sponsor`, `check_salary_threshold`, `track_application`, `list_applications` — verified end-to-end against a real MCP client (Claude Desktop, and a direct stdio protocol round-trip). Registered via `%APPDATA%\Claude\claude_desktop_config.json` → `mcpServers` (see README → MCP integration for the exact snippet).
- `src/mcp_server/tools.py` — all business logic; a thin wrapper only, zero import of the `mcp` package (stays importable/testable without the SDK). Each function owns its own DB connection lifecycle (open → `PRAGMA busy_timeout = 5000` → use → close in `finally`) — never a connection held across calls, since the MCP server is a long-running process.
- `src/mcp_server/server.py` — the only file that imports `mcp`; thin `@mcp.tool()` registrations delegating straight to `tools.py`.
- **Default DB paths are anchored to the project root** via `Path(__file__).resolve().parents[2]`, not CWD-relative — an MCP client spawns the server with an arbitrary working directory, and a relative default would have silently pointed every tool at a fresh, empty auto-created DB instead of erroring. Don't reintroduce a relative default here.
- Still wrap, don't reimplement, for any future tool added here: `register/normalize.py`, `register/ingest.py`, `jobs/sponsor_check.py`, `jobs/salary_check.py`, `jobs/tracker.py`, `jobs/db.py` are all read-only references for this layer.
- Known gap, deferred (see `_bmad-output/implementation-artifacts/deferred-work.md`): `track_application` has no audit trail (who/when/what) for its mutating calls.

## Critical Implementation Rules

### Language-Specific Rules (Python)

**Import/Export Patterns:**
- `from __future__ import annotations` is universal — include it in new files too.
- Imports are absolute module-style (`from jobs.db import ...`), not `src.`-prefixed — the package is installed editable via `uv`/hatchling. **Always run via `uv run` (e.g. `uv run streamlit run app.py`, `uv run pytest`) — a bare `python`/`streamlit` invocation may not resolve imports the same way.**

**Error Handling Patterns:**
- Domain verdicts are module-level string constants (`CONFIRMED`, `FUZZY_MATCH`, `NOT_FOUND`, `CANNOT_VERIFY`, `USER_CONFIRMED`, `USER_FLAGGED` in `sponsor_check.py`; `APPLIED`/`DISCARDED` in `tracker.py`), not enums — match this style for new statuses.
- `OutreachLengthError` (carrying `draft_text`/`char_count`/`limit`) is the **only** structured-exception example in the codebase so far — a useful precedent for new validation errors, not yet an established convention to enforce everywhere.
- `datetime.now(timezone.utc).isoformat()` is the consistent timestamp pattern everywhere — never naive `datetime.now()`.

**Naming & Typing Conventions:**
- snake_case files/functions; private helpers prefixed `_`; CLI handlers named `_cmd_<name>`.
- Both `X | None` (PEP 604) and `Optional[X]` (`typing`) appear in different files — match whichever style the file you're editing already uses; don't standardize across the codebase unprompted.
- Every module opens with a docstring explaining **why** it exists, not just what it does — match that tone for new modules.

### Framework-Specific Rules (Streamlit)

**Routing/App Structure:**
- `app.py` is a thin router using `st.navigation`/`st.Page` over `views/intake.py`, `views/roadmap.py`, `views/jobs_list.py` — new pages register here, not as ad-hoc scripts.

**State Management:**
- Heavy `st.session_state` usage keyed by job id (e.g. `outreach_draft_{job_id}` in `intake.py`, `list_outreach_draft_{job_id}` in `jobs_list.py` — **note the different prefixes for the same kind of draft**). An explicit `_reset_job_state()` helper pops a fixed key set — when adding new per-job session-state keys, add them to this reset list (and check which prefix(es) it actually covers) or stale state leaks across jobs.
- `st.form(...)` + `st.form_submit_button` groups inputs; `st.rerun()` follows every mutating action.
- **No `st.cache_data`/`st.cache_resource` anywhere** — every DB connection opens fresh per rerun. This is intentional simplicity for a single-user local-SQLite tool; don't add caching reflexively, since a cached connection can miss writes made by another view in the same session.

**Layering:**
- Views import CLI-layer helpers directly (e.g. `from jobs.cli import DEFAULT_GENERATED_CV_DIR, _sanitize_filename`) — CLI and UI are not decoupled behind a service layer. Reuse CLI helpers the same way rather than duplicating them in `views/`.

**Environment Loading:**
- `load_dotenv()` is called independently at 3 entry points (`app.py`, `jobs/cli.py`, `resume/cli.py`), not centralized. **Any new entry point (CLI, MCP server, etc.) must call `load_dotenv()` itself** — nothing does it automatically, and forgetting it fails silently until the first Gemini call needs `GEMINI_API_KEY`.

### Testing Rules

**Test Organization:**
- One test file per module, name mirrors the module (`test_sponsor_check.py` ↔ `sponsor_check.py`).
- Test names are long, behavior-descriptive sentences (e.g. `test_lapsed_override_wins_over_an_otherwise_confirmed_register_match`, `test_agency_posting_with_redacted_client_leaves_sponsor_check_name_unset`) — not generic. Match this style.
- Comments frequently cite the real/confirmed scenario that motivated the test (e.g. a "Bending Spoons" fuzzy-match case).

**Mock Usage:**
- DB-layer tests use real SQLite via pytest's `tmp_path` fixture — no mocking there.
- **Gemini-calling functions ARE mocked** — `unittest.mock.MagicMock` stubs `client.interactions.create.return_value`, and tests assert on `call_args` (`model`, `input`, `response_format["schema"]`), not just the parsed return value. This is what catches a broken request shape before it hits the real API — preserve the `client: Optional[genai.Client] = None` kwarg on any new Gemini-calling function so it stays testable this way.
- Testing an *absent*/null case (e.g. redacted employer name) is treated as a first-class test, not an afterthought — matches the "never guess" design principle.

**Coverage Expectations:**
- No formal coverage threshold (`pytest-cov` isn't a dependency) — coverage is judged by "every module has a matching test file," not a numeric gate.
- `pytest>=8.0` is the only pinned test dependency — no fixtures/plugins beyond stdlib + pytest unless you add one.

### Code Quality & Style Rules

**Linting/Formatting:**
- No `.ruff.toml`, `.flake8`, `black` config, or `mypy.ini` — no automated style/type gate. Consistency comes from matching existing file style by eye.

**Version Control:**
- **This project has no git repo yet, and no `.gitignore`.** `.env` (holds `GEMINI_API_KEY`) and all `data/*.db` files sit untracked in the project root with nothing excluding them. **Before the first `git init`/`git add`, a `.gitignore` must exist** covering at minimum `.env`, `data/*.db`, `__pycache__/`, `.venv/` — otherwise secrets and local runtime DBs go into the first commit.

**Code Organization:**
- One package per domain area under `src/` (`register`, `jobs`, `resume`, `roadmap`), each with its own `db.py`, `cli.py`, and domain logic — new domain areas should follow the same shape.
- `jobs/db.py`'s `_ensure_columns()` migration shim is specific to that module's evolving schema, not a pattern every new `db.py` must replicate — add it only when an existing table's columns actually need to grow later.
- `data/*.db` files are local runtime state (see Version Control above) — never assume a specific file has particular rows; tests always build their own via `tmp_path`.

**Documentation Requirements:**
- Module-level docstrings explain design rationale ("why"), not just "what" — this is the primary internal documentation; there's no separate architecture doc or ADR log.
- **`docs/v1-scope.md` is the de facto source of truth for product scope/design decisions** — there is no PRD or architecture.md in this repo. A second decision record (the MCP integration decisions reconciled earlier in this session) currently exists only in conversation history, not written into the repo anywhere — worth saving to `docs/` if it should persist past this session.

### Development Workflow Rules

**Git/Repository Rules:**
- No git repo exists yet — no branch naming, commit message format, or PR process to document; these genuinely don't exist, they're not "undocumented." See Code Quality & Style Rules → Version Control for the `.gitignore`-before-`git init` requirement.

**Deployment Patterns:**
- No deployment target — runs locally only, via `uv run streamlit run app.py`. No CI/CD, no hosting config, no Dockerfile.

**Durability:**
- No git history and no visible backup/sync means `data/*.db` (sponsor overrides, application tracker, resume/profile history) currently has exactly one copy, on this machine. Not a code change to make — just don't assume any of this state is recoverable if it's lost.

### Critical Don't-Miss Rules

**Anti-Patterns to Avoid:**
- Don't merge the 4 SQLite DBs, split a partial Gemini model-version bump across files, or assume a pydantic bump is free — see Technology Stack & Versions for specifics.
- Don't add auto-send/auto-apply/scraping anywhere — explicit, repeated product decision in `docs/v1-scope.md`; every risky action stays a human click.
- Don't introduce LangGraph or any agent-orchestration framework — cut from V1, confirmed absent from the codebase; linear pipeline by design.

**Edge Cases:**
- Agency-redacted client names are a first-class case (`CANNOT_VERIFY`), never guessed to force a verdict.
- A licensed sponsor is not a guarantee they'll sponsor *this* role (`LICENCE_CAVEAT`) — don't conflate "on the register" with "will sponsor you."
- **No DB-level uniqueness on `jobs`** — pasting the same posting twice (different session, forgotten dedup) creates two independent rows, not an update or a rejected duplicate. `jobs` is insert-only by design; don't assume "one posting = one row" without checking.

**Security Rules:**
- See Code Quality & Style Rules → Version Control: `.gitignore` must exist before the first `git init`/`git add`, or `.env` (`GEMINI_API_KEY`) and `data/*.db` land in the first commit.

**Performance Gotchas:**
- No enrichment of all ~122k sponsor register rows upfront — lazy enrichment only for companies that actually surface a matching job, per `docs/v1-scope.md` §1.

---

## Usage Guidelines

**For AI Agents:**
- Read this file before implementing any code in this repo.
- Follow all rules exactly as documented; when in doubt, prefer the more restrictive option.
- Update this file if a new pattern emerges that a future agent would otherwise have to rediscover.

**For Humans:**
- Keep this file lean and focused on agent needs — not a general architecture doc.
- Update when the technology stack changes (e.g. MCP integration lands, git repo is initialized) or a rule above is invalidated.
- Review periodically and remove rules that become obvious or outdated.

Last Updated: 2026-07-11
