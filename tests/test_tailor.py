from unittest.mock import MagicMock

from jobs.tailor import MODEL, TailoredApplication, compute_tailor_hash, generate_tailored_application
from resume.github_evidence import RepoEvidence


def test_compute_tailor_hash_is_deterministic_and_sensitive_to_either_input():
    h1 = compute_tailor_hash("resume text", "job text")
    h2 = compute_tailor_hash("resume text", "job text")
    h3 = compute_tailor_hash("different resume", "job text")
    h4 = compute_tailor_hash("resume text", "different job")

    assert h1 == h2
    assert h1 != h3
    assert h1 != h4


def test_generate_tailored_application_includes_repo_evidence_and_job_text_in_input():
    expected = TailoredApplication(
        tailored_resume="TAILORED RESUME TEXT",
        cover_letter="COVER LETTER TEXT",
        evidence_notes=["RAG claim backed by rag-knowledge-assistant repo"],
        portfolio_gaps=["No Kubernetes experience shown"],
    )
    fake_response = MagicMock(output_text=expected.model_dump_json())
    fake_client = MagicMock()
    fake_client.interactions.create.return_value = fake_response

    repos = [
        RepoEvidence(
            name="rag-knowledge-assistant",
            url="https://github.com/kunalg06/rag-knowledge-assistant",
            description="RAG platform using LangChain and FAISS",
            language="Python",
            stars=3,
        )
    ]

    result = generate_tailored_application(
        "Senior GenAI Engineer job posting text",
        "Acme AI Ltd",
        "candidate's full resume text",
        repos,
        client=fake_client,
    )

    assert result == expected
    _, kwargs = fake_client.interactions.create.call_args
    assert kwargs["model"] == MODEL
    sent_input = kwargs["input"]
    assert "Senior GenAI Engineer job posting text" in sent_input
    assert "candidate's full resume text" in sent_input
    assert "rag-knowledge-assistant" in sent_input
    assert "Acme AI Ltd" in sent_input


def test_generate_tailored_application_handles_no_repo_evidence():
    expected = TailoredApplication(
        tailored_resume="TAILORED RESUME TEXT",
        cover_letter="COVER LETTER TEXT",
        evidence_notes=[],
        portfolio_gaps=[],
    )
    fake_response = MagicMock(output_text=expected.model_dump_json())
    fake_client = MagicMock()
    fake_client.interactions.create.return_value = fake_response

    result = generate_tailored_application(
        "job text", None, "resume text", [], client=fake_client
    )

    assert result == expected
    _, kwargs = fake_client.interactions.create.call_args
    assert "no public repos found" in kwargs["input"]
