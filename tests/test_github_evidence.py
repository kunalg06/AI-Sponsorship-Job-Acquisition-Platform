import json
from io import BytesIO
from unittest.mock import patch

from resume.github_evidence import extract_github_username, fetch_public_repos


def test_extract_github_username_picks_most_frequent_match():
    text = (
        "GitHub: https://github.com/kunalg06/Autonomous-Data-Science-Agent\n"
        "GitHub: https://github.com/kunalg06/retail-insights-assistant\n"
        "GitHub: https://github.com/kunalg06/rag-knowledge-assistant\n"
    )
    assert extract_github_username(text) == "kunalg06"


def test_extract_github_username_ignores_generic_path_segments():
    text = "See github.com/topics/machine-learning for inspiration."
    assert extract_github_username(text) is None


def test_extract_github_username_returns_none_when_absent():
    assert extract_github_username("No GitHub link in this resume at all.") is None


class _FakeResponse(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def test_fetch_public_repos_excludes_forks_and_maps_fields():
    payload = [
        {
            "name": "rag-knowledge-assistant",
            "html_url": "https://github.com/kunalg06/rag-knowledge-assistant",
            "description": "RAG platform using LangChain and FAISS",
            "language": "Python",
            "stargazers_count": 3,
            "fork": False,
        },
        {
            "name": "some-forked-repo",
            "html_url": "https://github.com/kunalg06/some-forked-repo",
            "description": None,
            "language": "Python",
            "stargazers_count": 0,
            "fork": True,
        },
    ]

    with patch("resume.github_evidence.urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _FakeResponse(json.dumps(payload).encode("utf-8"))
        repos = fetch_public_repos("kunalg06")

    assert len(repos) == 1
    assert repos[0].name == "rag-knowledge-assistant"
    assert repos[0].language == "Python"
    assert repos[0].stars == 3
