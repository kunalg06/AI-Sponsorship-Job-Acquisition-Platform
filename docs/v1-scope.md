# AI Sponsorship Job Acquisition Platform — V1 Scope

**Status:** Converged from brainstorm, 2026-07-05. Personal-use tool, single candidate, UK Skilled Worker sponsorship search.
**Source conversation:** `_bmad-output/party-mode/memories/installed/.memlog.md`

## Purpose & core principle

One person's job search, automated where automation is cheap and safe, left manual where it's fragile or risky. Optimizes for **interview rate**, not application count or feature count. Every item below earned its place by answering "does this get an interview faster," not "does this look impressive in a diagram."

Not a multi-tenant platform. No autonomous external communication — every message a human reviews and sends.

## Core loop (build in this order — V1)

### 1. Sponsor register ingestion
- Source: [UK Worker and Temporary Worker sponsor register CSV](https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers) (gov.uk, updates periodically — re-download and re-import on refresh, don't assume it's static).
- Confirmed shape: ~142k rows, ~122k on the Skilled Worker route. Columns are only `Organisation Name, Town/City, County, Type & Rating, Route` — **no industry/sector signal at all**.
- Normalize on ingest: trim whitespace, split `T/A` / "trading as" into a separate trading-name field, strip `LIMITED`/`LTD` suffix variants for matching. Skip this and ~10-15% of real name matches silently fail later.
- Store as a simple lookup table (name → sponsor status). No enrichment of all 122k rows upfront — enrichment happens lazily, only for companies that actually surface a job you're considering (see §2).

### 2. Job intake (paste-in, not scraped)
- You source jobs manually across whatever platform each posting lives on (LinkedIn, company careers pages, niche ATS) — this stays manual by design, since postings are too fragmented across platforms for scraping to reliably cover, and scraping/automated-apply carries real ToS/ban risk (see §Risk Notes).
- You paste the raw job post text in. It may contain: company name, sometimes a separate client name (agency posting on behalf of an employer), sometimes a recruiter/contact name.
- Open question to settle before building the intake UI: paste raw text, paste a URL for the system to fetch, or a bookmarklet/extension for one-click capture. Start with paste-text — it's the zero-build option — and revisit if it's too much friction in practice.

### 3. Sponsor status check
Three cases, handled explicitly — never guess:
- **(a) Direct employer named clearly** → normalize the name, look it up against the cleaned register, return a verdict.
- **(b) Agency-only posting, client redacted** → return "can't verify," don't guess. This is also exactly the moment a cold DM to the recruiter ("who's the client?") pays for itself.
- **(c) You already found the real employer yourself** (e.g. via LinkedIn) → paste it in, treat as case (a).

### 4. Salary threshold check
UK Skilled Worker sponsorship has a **minimum salary threshold** — the higher of a general floor or the role's specific "going rate" by SOC occupation code, with reduced rates for some shortage/new-entrant cases. A job can be at a fully licensed sponsor and still be **legally unable to sponsor you** if the salary is below threshold for that occupation code.
- Sources: [eligible occupations & SOC codes](https://www.gov.uk/government/publications/skilled-worker-visa-eligible-occupations/skilled-worker-visa-eligible-occupations-and-codes), [going rates by code](https://www.gov.uk/government/publications/skilled-worker-visa-going-rates-for-eligible-occupations/skilled-worker-visa-going-rates-for-eligible-occupation-codes), [immigration salary list](https://www.gov.uk/government/publications/skilled-worker-visa-immigration-salary-list/skilled-worker-visa-immigration-salary-list) (shortage occupations, reduced rate).
- The one non-trivial piece: mapping a free-text job title ("GenAI Engineer") to a SOC code, since the government list won't use your title. Small classification problem, same shape as sponsor-name matching in §1, just smaller — a keyword/heuristic map is enough to start.
- Filter out anything that fails this check *before* spending effort tailoring for it.

### 5. Match scoring
Score the pasted job description against your resume/profile. Use a threshold (e.g. ~70%) as the go/no-go gate for spending effort on tailoring — tune this number once you have real data on what converts.

### 6. Resume & cover letter tailoring
- Generate a tailored resume + ATS-friendly version + cover letter per job.
- Back skill claims with evidence: cross-check resume bullets against your actual GitHub repos. Where a claim ("built production multi-agent systems") has a real repo behind it, cite specifics (repo, a real metric); where it doesn't, that's a portfolio gap, not a resume line.
- Cache on hash(resume + JD) to avoid regenerating identical work.

### 7. Cold outreach draft generation
- Draft messages **length-aware per channel** — a LinkedIn connection note has a hard character cap, email/InMail doesn't. One generation path producing the wrong length is worse than no draft.
- Drafts remix a single **narrative core** you write once (why AI, why UK, why you) rather than being invented fresh each time — consistency reads as confidence.
- Contact discovery stays manual/your-tool-of-choice (LinkedIn browsing, Apollo.io-style extensions) — paste the name/title in, same as a job post. The system never scrapes LinkedIn itself.

### 8. Application tracker & reminders
- Track per **(company, role)** pair, not per company — the same company with two open roles is two independent tracker rows with independent state.
- Two actions: **Applied** / **Discard**. Nothing heavier, or it stops getting used within a week.
- Applied → repeating reminder cadence at **day 3 / 7 / 14**: never auto-sent, always surfaced with a drafted follow-up for you to review and send.

### 9. Goal / Roadmap Planner
- Fixed target: **land a UK sponsorship role.** Real deadline for a *signed offer* is early-to-mid December 2026, not Dec 31 — UK hiring materially slows from mid-December through early January, and Certificate of Sponsorship + visa processing adds real weeks after an offer.
- Maintains a phased prep plan (see worked example below) covering DSA, AI/ML system design, and AI coding-interview practice, run **in parallel with active applying from week one** — never "study first, apply once ready" (that pattern alone can cost 4-8 weeks of funnel lag for nothing).
- **Goal-readjustment rule:** any new goal you propose (e.g. "should I get a certification") gets weighed against real data — does it actually show up as required/preferred in job postings you've pasted in, what's the time cost, what does it displace given the fixed deadline — and the planner says plainly if it doesn't pay for itself. No default encouragement; grounded answers only.

## Deliberately out of scope for V1 (and why)

| Original PRD idea | Why it's cut/deferred for V1 |
|---|---|
| LangGraph multi-agent orchestration | Core loop is a short linear pipeline. No stateful multi-agent orchestration needed at this scale. |
| Qdrant vector DB, 4 collections | Single user, single resume, a few thousand job descriptions at most. A lookup table beats a vector DB. |
| Playwright application automation | Automating submit-clicks against Greenhouse/Lever/Workday risks bot-detection bans on your own accounts — you click submit. |
| LinkedIn/contact scraping automation | Same ToS/ban risk. Contact discovery stays manual or via existing third-party tools (Apollo.io etc.); you paste results in. |
| Autonomous outreach scheduler (auto-send day 0/3/7/14) | Replaced with reminders that surface a draft for you to send — same cadence, zero automation risk. |
| Full enrichment of all ~122k sponsors upfront | Enrich lazily, only for companies that actually surface a matching job. |

## Fast-follow (V2 — build once the core loop produces real data)

- **Daily coach digest** — a read layer over the tracker + match queue + gap list + reminders, producing a short prioritized "do these things today" list. Not a new autonomous agent, just a summarizer with a personality — and it must notice effort/momentum, not just recite backlog, and never invent generic advice not grounded in your real data.
- **Gmail integration** — this environment already has a Gmail connector available; scope it read-only to a specific label/folder you route recruiter mail into, never full-inbox access. Surfaces replies into the coach digest with a drafted response; you send.
- **Personal brand assets** — LinkedIn headline/About tuned for recruiter keyword search + "Open to Work" set recruiters-only; a one-page shareable link (CV highlights + GitHub proof + clear sponsorship-need statement) to drop into cold DMs instead of a wall of text.
- **Outcome feedback loop** — track which resume version / DM template / channel actually gets replies, and use that real data to improve future generations. Needs weeks of real outcomes to be worth anything, hence fast-follow not core.
- **Referral/mutual-connection nudges, portfolio-gap-driven interview prep** (which of your GitHub repos best answers which likely interview question, tied to the JD).

## Data sources

- UK sponsor register CSV — gov.uk, updates periodically, re-import on refresh.
- SOC eligible occupations & codes, going rates by code, immigration salary list (shortage occupations) — all gov.uk, static-ish, re-check periodically.
- Optional secondary enrichment: Companies House free API (SIC industry codes) for cases where name-based classification is ambiguous.
- Explicitly **not** relying on third-party sponsorship-checker browser extensions — unverified provenance, likely just scraping the same official CSV with lag. Official source only.

## Suggested tech shape

Small and boring, on purpose — matches the "one person's job search" scale, not "platform for many":
- A simple relational store (SQLite is enough to start; Postgres if you want it) for sponsors, jobs, matches, tracker state.
- A linear pipeline (plain functions/scripts), not a multi-agent framework, for §1-§5.
- LLM calls for §6-§7 generation, cached on content hash.
- A minimal UI — a form to paste a job in, a list view for the tracker — before anything fancier.

## Risk notes

- Every core-loop step is either reading public government data or generating text — no scraping, no automated submission, no automated sending. Keep it that way; every risky action stays a human click.
- The belief that "the same ATS vendor reuses the first scan result across different companies" is unverified — but the conclusion (formal ATS applications are a low-visibility channel; cold DM to a human is higher-leverage) holds regardless of the exact mechanism, so it's fine to build around without resolving that claim.
- Agency-redacted client names are a real, recurring case, not an edge case — build the "can't verify" path from day one rather than bolting it on later.

## Your Dec 2026 roadmap (worked example, not sugarcoated)

Today: 2026-07-05. Target: signed offer by **early-to-mid December 2026** (~22 effective hiring weeks once the December slowdown is priced in, not 26). Realistic weekly budget alongside full-time work: ~15-25 hours, so roughly 400-500 hours total for prep + search combined.

**Applying starts week one, never after "feeling ready"** — funnel lag from first application to first interview typically runs 4-8 weeks.

| Month | Focus |
|---|---|
| July | Profile/one-pager locked, filter+match pipeline running, applying immediately to anything clearing threshold. DSA: fundamentals refresh (arrays, hashmaps, two pointers, sliding window). Start portfolio project #1. |
| August | DSA into trees/graphs/light DP. AI system design fundamentals (RAG pipelines, LLM serving trade-offs, vector DB choices — building this very tool doubles as practice). Keep applying weekly. First mock interviews. |
| September | Timed DSA practice, harder patterns. AI-specific system design deeper (multi-agent orchestration, latency/cost trade-offs). Portfolio project #2 if #1 landed. First real interviews should be landing now if July applications are converting. |
| October | Interview cycle running. Less new content, more spaced repetition on weak spots, behavioral prep, mock interviews with real feedback. Never let the application pipeline hit zero, even mid-loop. |
| November | Peak interview + offer-negotiation window. Last full month before the December slowdown — triage anything not moving. |
| Early December | Close, sign, start CoS/visa paperwork. Anything not converted by here realistically slides into January regardless of the calendar. |

**On certifications:** not necessary by default for 3-8 years of real experience — a working portfolio project plus real production claims outweighs a cert. Only worth the hours if actual pasted job postings explicitly list it as required/preferred; if it's not showing up in real postings, it doesn't earn a place in the 400-hour budget.

## Open questions / next steps

1. Job-intake format: paste text, paste URL, or bookmarklet — decide by trying paste-text first.
2. SOC-code inference from free-text job titles: heuristic keyword map to start, revisit if too lossy.
3. Set the actual match-score threshold and salary-threshold logic against a handful of real pasted jobs before trusting it.
4. Provide: base resume, GitHub username/repos, LinkedIn profile — the actual inputs the whole loop runs on.
