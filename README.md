# AI Sponsorship Job Acquisition Platform

A personal, single-user tool for running a UK Skilled Worker sponsorship job search.
It optimizes for **interview rate**, not application count: every step is either
reading public government data or generating a draft — nothing is sent, applied,
or messaged automatically. Every risky action stays a human click.

Full scope and design rationale: [`docs/v1-scope.md`](docs/v1-scope.md).

## What it does

1. **Sponsor register ingestion** — imports the UK gov.uk sponsor register CSV into a local lookup table, normalizing company names (trading names, `LTD`/`LIMITED` suffixes) so job-posting names match reliably.
2. **Job intake** — paste a raw job posting in; an LLM (Gemini) extracts structured fields (title, company, agency vs. direct employer, salary).
3. **Sponsor status check** — looks the employer up against the register. Never guesses: an agency posting with a redacted client returns "can't verify," not a false negative.
4. **Salary threshold check** — checks the posting's salary against the UK Skilled Worker minimum for the role's SOC occupation code.
5. **Match scoring** — scores the posting against your resume/profile as a go/no-go gate before spending effort tailoring.
6. **Resume & cover letter tailoring** — generates a tailored resume, ATS-friendly version, and cover letter per job, cached on content hash.
7. **Cold outreach drafting** — drafts channel-length-aware outreach messages (LinkedIn note vs. email) for you to review and send yourself.
8. **Application tracker** — tracks each (company, role) pair through Applied/Discard, with day 3/7/14 follow-up reminders (never auto-sent).
9. **Goal/roadmap planner** — tracks a phased prep plan against a fixed sponsorship deadline.

## Setup

Requires [`uv`](https://docs.astral.sh/uv/) and Python ≥3.10.

```bash
uv sync
```

Create a `.env` file in the project root with your Gemini API key:

```
GEMINI_API_KEY=your-key-here
```

Optionally, set `GENERATED_CV_DIR` to relocate where tailored resumes/cover letters and drafted outreach messages are written (defaults to `cv/generated_cv`). Setting it once keeps the CLI's own `--out-dir` defaults and the Streamlit UI pointed at the same directory — an explicit `--out-dir` passed to a single CLI invocation still overrides it for that command only.

## Running the app

```bash
uv run streamlit run app.py
```

This opens the Streamlit UI: paste a job posting in, review the roadmap, or browse the tracked jobs list.

### Deploying to Streamlit Community Cloud

`requirements.txt` (a single `-e .` line) exists only for Streamlit Community Cloud, which installs with plain `pip` and doesn't understand `uv`/`uv.lock`. It reads dependencies straight from `pyproject.toml` via an editable install. `uv.lock` remains the source of truth for local development; `requirements.txt` is not kept in lockstep with it, so Cloud may resolve slightly newer dependency versions than what's tested locally.

`app.py` bridges `GEMINI_API_KEY` from Cloud's Secrets UI (`st.secrets`) into `os.environ` on startup, since `genai.Client()` only reads the latter — set the key under **Settings → Secrets** in the Cloud app dashboard (as `GEMINI_API_KEY = "..."`). A local `.env`/real environment variable always takes precedence over `st.secrets` if both happen to be set.

Local state (`data/*.db`, `cv/`) still needs addressing separately — see `_bmad-output/implementation-artifacts/deferred-work.md`.

## CLI tools

Each domain area also has a standalone CLI, useful for one-off tasks (e.g. re-importing the register) without opening the UI:

```bash
# Sponsor register
uv run python -m register.cli ingest          # download + load the latest register
uv run python -m register.cli lookup "Acme Ltd"

# Jobs pipeline
uv run python -m jobs.cli intake              # paste a job posting in from the terminal
uv run python -m jobs.cli list                # list tracked jobs
uv run python -m jobs.cli due                 # show jobs with an overdue follow-up reminder

# Resume/profile
uv run python -m resume.cli add               # paste your resume in, extract a structured profile
uv run python -m resume.cli show

# Roadmap
uv run python -m roadmap.cli init             # set your goal deadline + seed the milestone plan
uv run python -m roadmap.cli status
```

Run `uv run python -m <module>.cli --help` for the full command list of any of the four.

## MCP integration

`src/mcp_server/` exposes four read/write operations from the pipeline as MCP
(Model Context Protocol) tools, so an MCP client (Claude Desktop, Claude Code)
can query and update your job search conversationally instead of through the
UI. It's a thin wrapper only — no business logic lives here, and no LangGraph
or agent orchestration is involved.

| Tool | Wraps | Purpose |
|---|---|---|
| `check_sponsor` | `jobs.sponsor_check` + `register.db` | Look up whether a company is a licensed UK sponsor |
| `check_salary_threshold` | `jobs.salary_check` | Check a stated salary against the Skilled Worker minimum for a role |
| `track_application` | `jobs.db` | Mark a tracked job `applied` or `discarded` |
| `list_applications` | `jobs.db` + `jobs.tracker` | List applied jobs, optionally filtered to those with a due follow-up reminder |

**To register it with Claude Desktop**, add this to `claude_desktop_config.json`
(Settings → Developer, or directly at `%APPDATA%\Claude\claude_desktop_config.json`
on Windows) and restart the app:

```json
{
  "mcpServers": {
    "sponsorship-job-platform": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "C:\\path\\to\\AI Sponsorship Job Acquisition Platform",
        "python",
        "-m",
        "mcp_server.server"
      ]
    }
  }
}
```

To run/verify the server standalone (e.g. for the [MCP Inspector](https://modelcontextprotocol.io/docs/tools/inspector) or any other MCP client):

```bash
uv run python -m mcp_server.server
```

## Testing

```bash
uv run pytest
```

## Project structure

```
src/
  register/   sponsor register ingestion, normalization, lookup
  jobs/       job intake, sponsor/salary checks, match scoring, tailoring, outreach, tracker
  resume/     resume/profile storage and structured extraction
  roadmap/    goal/milestone planner
  mcp_server/ MCP tool wrappers over the pipeline (for Claude Desktop/Code)
views/        Streamlit pages (routed from app.py)
tests/        one test file per module
data/         local SQLite state (gitignored — sponsors.db, jobs.db, profile.db, roadmap.db)
cv/           your resume + generated per-company tailored output (gitignored — personal content)
docs/         v1-scope.md, the source of truth for scope/design decisions
```

See [`_bmad-output/project-context.md`](_bmad-output/project-context.md) for the
full set of implementation rules, conventions, and known gotchas — read that
file before making non-trivial changes to this codebase.

## Design principles

- No scraping, no automated job applications, no automated outreach sending — every risky action is a manual click, by design (see `docs/v1-scope.md` risk notes).
- 4 independent SQLite databases, one per domain area — this is intentional, not fragmentation to fix.
- Not a multi-tenant platform, not a multi-agent system — a linear pipeline built for one person's job search.
