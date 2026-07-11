"""Fetch public GitHub repo data as grounding evidence for resume tailoring.

Unauthenticated GitHub API access (60 requests/hour/IP) - fine for a
personal tool's usage volume. No token support in V1; add one later if
rate limits ever become a problem.
"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from typing import Optional

GITHUB_API = "https://api.github.com"

_GITHUB_URL_RE = re.compile(r"github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)", re.IGNORECASE)
_EXCLUDED_PATH_SEGMENTS = {"orgs", "topics", "sponsors", "marketplace", "settings", "search", "about"}


@dataclass(frozen=True)
class RepoEvidence:
    name: str
    url: str
    description: Optional[str]
    language: Optional[str]
    stars: int


def extract_github_username(raw_resume_text: str) -> Optional[str]:
    """Best-effort: pull a GitHub username out of any github.com URL in the resume.

    A resume usually repeats the same username across several project links,
    so the most frequent match wins over incidental one-off mentions.
    """
    matches = [m for m in _GITHUB_URL_RE.findall(raw_resume_text) if m.lower() not in _EXCLUDED_PATH_SEGMENTS]
    if not matches:
        return None
    return max(set(matches), key=matches.count)


def fetch_public_repos(username: str, limit: int = 15) -> list[RepoEvidence]:
    """Fetch a candidate's public, non-fork GitHub repos as evidence."""
    url = f"{GITHUB_API}/users/{username}/repos?per_page={limit}&sort=updated"
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "sponsorship-job-platform"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        data = json.loads(response.read().decode("utf-8"))

    return [
        RepoEvidence(
            name=repo["name"],
            url=repo["html_url"],
            description=repo.get("description"),
            language=repo.get("language"),
            stars=repo.get("stargazers_count", 0),
        )
        for repo in data
        if not repo.get("fork")
    ]
