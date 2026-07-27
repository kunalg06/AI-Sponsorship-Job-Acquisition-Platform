# Job Source Evaluation

Per-source verdicts on what discovery automation may touch, decided in the originating discussion. Downstream must not add a new source without re-running this evaluation.

| Source | Verdict | Evidence |
|---|---|---|
| **Indeed** (`claude_ai` Indeed MCP: `search_jobs`, `get_job_details`) | **Go** | Sanctioned first-party integration, not scraping. Verified live via a real `search_jobs` call ("AI engineer", London, GB): results include a genuine `Posted on: <date>` field and a real apply URL per listing (e.g. `https://to.indeed.com/aazczvw4kwt2`). |
| **visasponsor.jobs** (`https://visasponsor.jobs/api/jobs`) | **No** | Not a JSON API despite the path — returns rendered HTML. `robots.txt` doesn't block `/api/jobs` specifically, but the site's own Terms (`/terms`, fetched live) state: *"Use of any material on the website for the purpose of creating a 'meta' search of job advertisements... by combining the information contained herein with other sources of information... is strictly prohibited."* That is this feature's exact shape. Manual, human visits to the site remain fine — automated access does not. |
| **LinkedIn** | **No** | Only unofficial community MCP servers exist (e.g. `linkedin-mcp` projects on GitHub) — no sanctioned integration. LinkedIn has an active enforcement history against scrapers and bot-detection that can ban the account it's run against. Not worth the risk against the user's real account. |
| **Glassdoor** | **No** | Same category as LinkedIn — unofficial-only, ToS/automation risk unverified and not worth taking on. |

Adding a new source later requires: (1) confirming a sanctioned/official access path exists, (2) reading that source's actual Terms for an automation/meta-search prohibition, (3) recording the verdict here.
