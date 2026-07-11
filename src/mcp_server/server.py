"""MCP transport entry point: exposes the job-search pipeline as tools for an
MCP client (Claude Desktop / Claude Code).

All business logic lives in `mcp_server.tools`, which imports nothing from
`mcp` - this module only wires those functions up to `FastMCP`'s
`@mcp.tool()` registration, so the `mcp` SDK dependency is confined to this
one file.
"""

from __future__ import annotations

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from mcp_server import tools

load_dotenv()

mcp = FastMCP("sponsorship-job-platform")


@mcp.tool()
def check_sponsor(employer_name: str | None = None, *, sponsor_db: str = tools.DEFAULT_SPONSOR_DB) -> dict:
    """Look up whether an employer is a licensed UK sponsor."""
    return tools.check_sponsor(employer_name, sponsor_db=sponsor_db)


@mcp.tool()
def check_salary_threshold(job_title: str, salary_raw: str | None = None) -> dict:
    """Check whether a posting's stated salary clears the Skilled Worker sponsorship threshold."""
    return tools.check_salary_threshold(job_title, salary_raw)


@mcp.tool()
def track_application(job_id: int, action: str, *, jobs_db: str = tools.DEFAULT_JOBS_DB) -> dict:
    """Mark a job applied or discarded, returning the updated job row."""
    return tools.track_application(job_id, action, jobs_db=jobs_db)


@mcp.tool()
def list_applications(due_only: bool = False, *, jobs_db: str = tools.DEFAULT_JOBS_DB) -> list[dict]:
    """List applied jobs, optionally filtered to only those with a due follow-up reminder."""
    return tools.list_applications(due_only, jobs_db=jobs_db)


if __name__ == "__main__":
    mcp.run()
