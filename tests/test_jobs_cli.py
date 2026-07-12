"""Tests for `jobs.cli`'s tailoring + legacy-migration commands.

Exercised through `build_parser()`/`args.func(args)` (the real CLI wiring),
not only the internal helper functions - the previous implementation
attempt's test gap (testing helpers directly) is exactly what let a
caching bug in `_cmd_tailor`'s wiring through undetected. See
`_bmad-output/implementation-artifacts/spec-tailored-content-file-only-storage.md`
Spec Change Log for the full story.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import docx
import pytest

import jobs.cli as jobs_cli
from jobs.cli import _sanitize_filename, _tailored_docx_paths, build_parser
from jobs.db import connect as connect_jobs
from jobs.db import get_job, insert_job
from jobs.extract import JobExtraction
from jobs.tailor import TailoredApplication
from resume.db import connect as connect_profile
from resume.db import insert_profile
from resume.extract import ResumeProfile

RESUME_TEXT = "Jane Doe - Senior Backend Engineer. 5 years Python. No GitHub link in this resume."


def _add_profile_version(profile_db_path: Path, resume_text: str) -> None:
    conn = connect_profile(profile_db_path)
    try:
        insert_profile(
            conn,
            resume_text,
            ResumeProfile(
                full_name="Jane Doe",
                years_experience=5,
                seniority="Senior",
                core_skills=["Python"],
                domains=["Backend"],
                past_roles=["Engineer"],
                summary="Backend engineer.",
            ),
        )
    finally:
        conn.close()


def _make_job(jobs_db_path: Path, *, company_name="Acme AI", raw_text="job posting text") -> int:
    conn = connect_jobs(jobs_db_path)
    try:
        job_id = insert_job(
            conn, raw_text, JobExtraction(job_title="AI Engineer", company_name=company_name, is_agency_posting=False)
        )
    finally:
        conn.close()
    return job_id


def _make_source_resume_docx(path: Path) -> None:
    document = docx.Document()
    document.add_paragraph("JANE DOE")
    document.add_paragraph("SUMMARY")
    document.add_paragraph("Software engineer with 5 years building backend systems in Python.")
    document.save(str(path))


def _fake_tailored_application(suffix: str = "") -> TailoredApplication:
    return TailoredApplication(
        tailored_resume=f"TAILORED RESUME{suffix}",
        cover_letter=f"COVER LETTER{suffix}",
        evidence_notes=[f"evidence note{suffix}"],
        portfolio_gaps=[f"portfolio gap{suffix}"],
    )


def _run(argv: list[str]) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


def _add_legacy_columns_with_text(jobs_db_path: Path, job_id: int, tailored_resume: str, cover_letter: str) -> None:
    """Simulate a jobs.db created before this refactor: `tailored_resume`/
    `cover_letter` still exist as real columns with real data, since
    `_ensure_columns()` only ever adds columns, never drops them. A fresh
    `connect()` no longer creates these columns at all (they're not in
    SCHEMA anymore), so this reaches for raw sqlite3 to simulate the
    pre-existing state directly."""
    conn = sqlite3.connect(jobs_db_path)
    conn.execute("ALTER TABLE jobs ADD COLUMN tailored_resume TEXT")
    conn.execute("ALTER TABLE jobs ADD COLUMN cover_letter TEXT")
    conn.execute(
        "UPDATE jobs SET tailored_resume = ?, cover_letter = ? WHERE id = ?", (tailored_resume, cover_letter, job_id)
    )
    conn.commit()
    conn.close()


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A ready-to-use jobs.db (one job) + profile.db + a real source .docx,
    with the two LLM-calling functions the docx path uses monkeypatched so
    tests can assert on call counts without hitting a real API. No GitHub
    URL appears in the resume text, so `_fetch_github_evidence` also never
    makes a real network call."""
    jobs_db = tmp_path / "jobs.db"
    profile_db = tmp_path / "profile.db"
    resume_dir = tmp_path / "my-resume"
    out_dir = tmp_path / "generated_cv"
    resume_dir.mkdir()

    job_id = _make_job(jobs_db)
    _add_profile_version(profile_db, RESUME_TEXT)
    _make_source_resume_docx(resume_dir / "resume.docx")

    tailor_calls = MagicMock(return_value=_fake_tailored_application())
    paragraph_calls = MagicMock(return_value={})
    monkeypatch.setattr(jobs_cli, "generate_tailored_application", tailor_calls)
    monkeypatch.setattr(jobs_cli, "generate_paragraph_edits", paragraph_calls)

    return {
        "jobs_db": jobs_db,
        "profile_db": profile_db,
        "resume_dir": resume_dir,
        "out_dir": out_dir,
        "job_id": job_id,
        "tailor_calls": tailor_calls,
        "paragraph_calls": paragraph_calls,
    }


def _tailor_docx_argv(env, job_id=None, *, force: bool = False) -> list[str]:
    argv = [
        "tailor-docx",
        str(job_id if job_id is not None else env["job_id"]),
        "--db",
        str(env["jobs_db"]),
        "--profile-db",
        str(env["profile_db"]),
        "--resume-dir",
        str(env["resume_dir"]),
        "--out-dir",
        str(env["out_dir"]),
    ]
    if force:
        argv.append("--force")
    return argv


def _get_job_row(jobs_db_path, job_id):
    conn = connect_jobs(jobs_db_path)
    try:
        return get_job(conn, job_id)
    finally:
        conn.close()


# --------------------------------------------------------------------------
# `tailor-docx` - job_id-keyed docx cache-check
# --------------------------------------------------------------------------


def test_tailor_docx_first_run_generates_via_llm_and_writes_job_id_keyed_files(env):
    _run(_tailor_docx_argv(env))

    resume_path, cover_letter_path = _tailored_docx_paths("Acme AI", env["job_id"], str(env["out_dir"]))
    assert resume_path.exists()
    assert cover_letter_path.exists()
    assert env["tailor_calls"].call_count == 1
    assert env["paragraph_calls"].call_count == 1

    row = _get_job_row(env["jobs_db"], env["job_id"])
    assert row["tailor_hash"] is not None
    assert row["tailor_evidence_notes"] == '["evidence note"]'
    assert row["tailor_portfolio_gaps"] == '["portfolio gap"]'


def test_tailor_docx_rerun_with_nothing_changed_is_a_cache_hit_with_no_llm_call(env):
    _run(_tailor_docx_argv(env))
    resume_path, _ = _tailored_docx_paths("Acme AI", env["job_id"], str(env["out_dir"]))
    mtime_before = resume_path.stat().st_mtime

    _run(_tailor_docx_argv(env))

    assert env["tailor_calls"].call_count == 1
    assert env["paragraph_calls"].call_count == 1
    assert resume_path.stat().st_mtime == mtime_before


def test_tailor_docx_second_job_same_company_gets_its_own_files_and_does_not_touch_the_first(env):
    _run(_tailor_docx_argv(env))
    first_resume_path, _ = _tailored_docx_paths("Acme AI", env["job_id"], str(env["out_dir"]))
    first_content = first_resume_path.read_bytes()

    second_job_id = _make_job(env["jobs_db"], company_name="Acme AI", raw_text="a different job posting entirely")
    _run(_tailor_docx_argv(env, job_id=second_job_id))

    second_resume_path, second_cover_path = _tailored_docx_paths("Acme AI", second_job_id, str(env["out_dir"]))
    assert second_resume_path.exists()
    assert second_cover_path.exists()
    assert second_resume_path != first_resume_path
    assert first_resume_path.exists()
    assert first_resume_path.read_bytes() == first_content
    assert env["tailor_calls"].call_count == 2


def test_tailor_docx_resume_updated_since_last_tailor_regenerates_this_jobs_files(env):
    _run(_tailor_docx_argv(env))
    _, cover_letter_path = _tailored_docx_paths("Acme AI", env["job_id"], str(env["out_dir"]))
    old_cover_text = docx.Document(str(cover_letter_path)).paragraphs[0].text

    env["tailor_calls"].return_value = _fake_tailored_application("_V2")
    _add_profile_version(env["profile_db"], RESUME_TEXT + " Updated with a new AWS certification.")

    _run(_tailor_docx_argv(env))

    new_cover_text = docx.Document(str(cover_letter_path)).paragraphs[0].text
    assert new_cover_text != old_cover_text
    assert env["tailor_calls"].call_count == 2
    assert env["paragraph_calls"].call_count == 2

    row = _get_job_row(env["jobs_db"], env["job_id"])
    assert row["tailor_evidence_notes"] == '["evidence note_V2"]'


def test_tailor_docx_files_deleted_manually_is_treated_as_a_cache_miss(env):
    _run(_tailor_docx_argv(env))
    resume_path, _ = _tailored_docx_paths("Acme AI", env["job_id"], str(env["out_dir"]))
    resume_path.unlink()

    _run(_tailor_docx_argv(env))

    assert resume_path.exists()
    assert env["tailor_calls"].call_count == 2


def test_tailor_docx_force_flag_regenerates_even_when_hash_matches_and_files_exist(env):
    _run(_tailor_docx_argv(env))
    _run(_tailor_docx_argv(env, force=True))

    assert env["tailor_calls"].call_count == 2
    assert env["paragraph_calls"].call_count == 2


def test_tailor_docx_unknown_job_id_raises_system_exit(env):
    """Driven through the real CLI wiring (`build_parser()`/`args.func`),
    matching this file's own stated test philosophy - not just the
    internal `_tailor_docx_for_job` helper directly."""
    unknown_job_id = env["job_id"] + 999
    with pytest.raises(SystemExit, match=f"No job #{unknown_job_id} found"):
        _run(_tailor_docx_argv(env, job_id=unknown_job_id))


def test_tailor_docx_cache_hit_succeeds_even_after_source_docx_is_deleted(env, monkeypatch):
    """The frozen cache-hit contract requires no source-.docx read at all on
    a hit. Delete the source file the first generation read from, then
    monkeypatch `_find_source_resume_docx` to fail loudly if called - the
    second run must succeed anyway (no SystemExit, no crash) and return the
    exact same warning that was stored at generation time."""
    _run(_tailor_docx_argv(env))
    stored_warning_before = _get_job_row(env["jobs_db"], env["job_id"])["tailor_page_risk_warning"]

    (env["resume_dir"] / "resume.docx").unlink()

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("cache hit must not read the source .docx")

    monkeypatch.setattr(jobs_cli, "_find_source_resume_docx", _fail_if_called)

    _run(_tailor_docx_argv(env))  # must not raise SystemExit or AssertionError

    stored_warning_after = _get_job_row(env["jobs_db"], env["job_id"])["tailor_page_risk_warning"]
    assert stored_warning_after == stored_warning_before
    assert env["tailor_calls"].call_count == 1


# --------------------------------------------------------------------------
# `tailor` - plain-text, deliberately uncached
# --------------------------------------------------------------------------


def test_cmd_tailor_calls_llm_both_times_and_overwrites_txt_output(env, tmp_path):
    txt_out_dir = tmp_path / "tailored_txt"
    argv = [
        "tailor",
        str(env["job_id"]),
        "--db",
        str(env["jobs_db"]),
        "--profile-db",
        str(env["profile_db"]),
        "--out-dir",
        str(txt_out_dir),
    ]

    _run(argv)
    _run(argv)

    assert env["tailor_calls"].call_count == 2
    resume_txt = txt_out_dir / f"{env['job_id']}_resume.txt"
    assert resume_txt.read_text(encoding="utf-8") == "TAILORED RESUME"

    # The plain-text path must never touch the docx-cache's DB fields -
    # sharing that state is exactly the bug this refactor's amendment fixed.
    row = _get_job_row(env["jobs_db"], env["job_id"])
    assert row["tailor_hash"] is None


def test_cmd_tailor_unknown_job_id_raises_system_exit(env, tmp_path):
    """Driven through the real CLI wiring (`build_parser()`/`args.func`),
    matching this file's own stated test philosophy - not just the
    internal helper functions directly."""
    unknown_job_id = env["job_id"] + 999
    argv = [
        "tailor",
        str(unknown_job_id),
        "--db",
        str(env["jobs_db"]),
        "--profile-db",
        str(env["profile_db"]),
        "--out-dir",
        str(tmp_path / "tailored_txt"),
    ]

    with pytest.raises(SystemExit, match=f"No job #{unknown_job_id} found"):
        _run(argv)


# --------------------------------------------------------------------------
# `migrate-legacy-tailoring`
# --------------------------------------------------------------------------


def test_migrate_legacy_tailoring_writes_txt_from_legacy_db_text_and_is_idempotent(tmp_path):
    jobs_db = tmp_path / "jobs.db"
    job_id = _make_job(jobs_db, company_name="Bending Spoons")
    _add_legacy_columns_with_text(jobs_db, job_id, "LEGACY RESUME TEXT", "LEGACY COVER LETTER TEXT")

    out_dir = tmp_path / "tailored_txt"
    generated_cv_dir = tmp_path / "generated_cv"
    argv = [
        "migrate-legacy-tailoring",
        "--db",
        str(jobs_db),
        "--out-dir",
        str(out_dir),
        "--generated-cv-dir",
        str(generated_cv_dir),
    ]

    _run(argv)

    resume_txt = out_dir / f"{job_id}_resume.txt"
    cover_txt = out_dir / f"{job_id}_cover_letter.txt"
    assert resume_txt.read_text(encoding="utf-8") == "LEGACY RESUME TEXT"
    assert cover_txt.read_text(encoding="utf-8") == "LEGACY COVER LETTER TEXT"

    _run(argv)  # idempotent - no error, content unchanged
    assert resume_txt.read_text(encoding="utf-8") == "LEGACY RESUME TEXT"
    assert cover_txt.read_text(encoding="utf-8") == "LEGACY COVER LETTER TEXT"


def test_migrate_legacy_tailoring_partial_state_only_writes_the_missing_txt_file(tmp_path):
    jobs_db = tmp_path / "jobs.db"
    job_id = _make_job(jobs_db, company_name="Acme AI")
    _add_legacy_columns_with_text(jobs_db, job_id, "LEGACY RESUME TEXT", "LEGACY COVER LETTER TEXT")

    out_dir = tmp_path / "tailored_txt"
    out_dir.mkdir()
    # Simulate the resume half of the .txt export having already happened
    # (e.g. from an earlier partial run) - the migration must not clobber it.
    (out_dir / f"{job_id}_resume.txt").write_text("ALREADY EXPORTED RESUME", encoding="utf-8")

    generated_cv_dir = tmp_path / "generated_cv"
    argv = [
        "migrate-legacy-tailoring",
        "--db",
        str(jobs_db),
        "--out-dir",
        str(out_dir),
        "--generated-cv-dir",
        str(generated_cv_dir),
    ]

    _run(argv)

    assert (out_dir / f"{job_id}_resume.txt").read_text(encoding="utf-8") == "ALREADY EXPORTED RESUME"
    assert (out_dir / f"{job_id}_cover_letter.txt").read_text(encoding="utf-8") == "LEGACY COVER LETTER TEXT"


def test_migrate_legacy_tailoring_renames_unambiguous_legacy_docx(tmp_path):
    jobs_db = tmp_path / "jobs.db"
    job_id = _make_job(jobs_db, company_name="Bending Spoons")

    generated_cv_dir = tmp_path / "generated_cv"
    company_dir = generated_cv_dir / _sanitize_filename("Bending Spoons")
    company_dir.mkdir(parents=True)
    (company_dir / "resume.docx").write_bytes(b"old resume bytes")
    (company_dir / "cover_letter.docx").write_bytes(b"old cover bytes")

    out_dir = tmp_path / "tailored_txt"
    argv = [
        "migrate-legacy-tailoring",
        "--db",
        str(jobs_db),
        "--out-dir",
        str(out_dir),
        "--generated-cv-dir",
        str(generated_cv_dir),
    ]

    _run(argv)

    assert (company_dir / f"{job_id}_resume.docx").read_bytes() == b"old resume bytes"
    assert (company_dir / f"{job_id}_cover_letter.docx").read_bytes() == b"old cover bytes"
    assert not (company_dir / "resume.docx").exists()
    assert not (company_dir / "cover_letter.docx").exists()

    _run(argv)  # idempotent - old-format files are already gone, no error


def test_migrate_legacy_tailoring_ambiguous_docx_folder_warns_and_leaves_files_untouched(tmp_path, capsys):
    jobs_db = tmp_path / "jobs.db"
    _make_job(jobs_db, company_name="Bending Spoons")
    _make_job(jobs_db, company_name="Bending Spoons")  # two jobs -> ambiguous match

    generated_cv_dir = tmp_path / "generated_cv"
    company_dir = generated_cv_dir / _sanitize_filename("Bending Spoons")
    company_dir.mkdir(parents=True)
    (company_dir / "resume.docx").write_bytes(b"old resume bytes")
    (company_dir / "cover_letter.docx").write_bytes(b"old cover bytes")

    out_dir = tmp_path / "tailored_txt"
    argv = [
        "migrate-legacy-tailoring",
        "--db",
        str(jobs_db),
        "--out-dir",
        str(out_dir),
        "--generated-cv-dir",
        str(generated_cv_dir),
    ]

    _run(argv)

    captured = capsys.readouterr()
    assert "ambiguous" in captured.out.lower()
    assert (company_dir / "resume.docx").exists()
    assert (company_dir / "cover_letter.docx").exists()


def test_migrate_legacy_tailoring_zero_matching_jobs_warns_and_leaves_files_untouched(tmp_path, capsys):
    jobs_db = tmp_path / "jobs.db"
    _make_job(jobs_db, company_name="Some Other Company")  # no job matches "Bending Spoons"

    generated_cv_dir = tmp_path / "generated_cv"
    company_dir = generated_cv_dir / _sanitize_filename("Bending Spoons")
    company_dir.mkdir(parents=True)
    (company_dir / "resume.docx").write_bytes(b"old resume bytes")

    out_dir = tmp_path / "tailored_txt"
    argv = [
        "migrate-legacy-tailoring",
        "--db",
        str(jobs_db),
        "--out-dir",
        str(out_dir),
        "--generated-cv-dir",
        str(generated_cv_dir),
    ]

    _run(argv)

    captured = capsys.readouterr()
    # Zero matches is orphaned data with nothing to disambiguate - distinct
    # wording from the genuinely-ambiguous (2+ match) case above.
    assert "no matching job" in captured.out.lower()
    assert "ambiguous" not in captured.out.lower()
    assert (company_dir / "resume.docx").exists()


def test_migrate_legacy_tailoring_matches_company_less_job_via_fallback_slug(tmp_path):
    """A legacy folder created under the `job_{id}`/`unknown_company`
    fallback slug (for a job with no company_name) must still be matched
    and renamed like any other unambiguous case - not permanently reported
    ambiguous just because `company_name` is falsy."""
    jobs_db = tmp_path / "jobs.db"
    job_id = _make_job(jobs_db, company_name=None)

    generated_cv_dir = tmp_path / "generated_cv"
    company_dir = generated_cv_dir / f"job_{job_id}"
    company_dir.mkdir(parents=True)
    (company_dir / "resume.docx").write_bytes(b"old resume bytes")
    (company_dir / "cover_letter.docx").write_bytes(b"old cover bytes")

    out_dir = tmp_path / "tailored_txt"
    argv = [
        "migrate-legacy-tailoring",
        "--db",
        str(jobs_db),
        "--out-dir",
        str(out_dir),
        "--generated-cv-dir",
        str(generated_cv_dir),
    ]

    _run(argv)

    assert (company_dir / f"{job_id}_resume.docx").exists()
    assert (company_dir / f"{job_id}_cover_letter.docx").exists()
    assert not (company_dir / "resume.docx").exists()


def test_migrate_legacy_tailoring_continues_after_oserror_renaming_one_folder(tmp_path, monkeypatch):
    """One OSError (locked file, permission denied) on one company folder
    must not abort the entire migration loop for every subsequent folder."""
    jobs_db = tmp_path / "jobs.db"
    broken_job_id = _make_job(jobs_db, company_name="Broken Co")
    good_job_id = _make_job(jobs_db, company_name="Good Co")

    generated_cv_dir = tmp_path / "generated_cv"
    broken_dir = generated_cv_dir / _sanitize_filename("Broken Co")
    good_dir = generated_cv_dir / _sanitize_filename("Good Co")
    broken_dir.mkdir(parents=True)
    good_dir.mkdir(parents=True)
    (broken_dir / "resume.docx").write_bytes(b"broken resume")
    (broken_dir / "cover_letter.docx").write_bytes(b"broken cover")
    (good_dir / "resume.docx").write_bytes(b"good resume")
    (good_dir / "cover_letter.docx").write_bytes(b"good cover")

    original_rename = Path.rename

    def flaky_rename(self, target):
        if self.parent.name == _sanitize_filename("Broken Co"):
            raise OSError("simulated permission denied")
        return original_rename(self, target)

    monkeypatch.setattr(Path, "rename", flaky_rename)

    out_dir = tmp_path / "tailored_txt"
    argv = [
        "migrate-legacy-tailoring",
        "--db",
        str(jobs_db),
        "--out-dir",
        str(out_dir),
        "--generated-cv-dir",
        str(generated_cv_dir),
    ]

    _run(argv)  # must not raise - and must still process Good_Co

    assert (broken_dir / "resume.docx").exists()
    assert not (broken_dir / f"{broken_job_id}_resume.docx").exists()

    assert (good_dir / f"{good_job_id}_resume.docx").exists()
    assert (good_dir / f"{good_job_id}_cover_letter.docx").exists()
