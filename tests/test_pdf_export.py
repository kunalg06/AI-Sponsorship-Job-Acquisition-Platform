import subprocess
from unittest.mock import MagicMock

import pytest

import jobs.pdf_export as pdf_export_module
from jobs.pdf_export import PdfConversionError, convert_docx_to_pdf


def test_convert_docx_to_pdf_raises_when_soffice_is_not_found(tmp_path, monkeypatch):
    monkeypatch.delenv(pdf_export_module._SOFFICE_ENV_VAR, raising=False)
    monkeypatch.setattr(pdf_export_module.shutil, "which", lambda name: None)
    monkeypatch.setattr(pdf_export_module.os, "name", "posix")  # skip the Windows default-path fallback

    docx_path = tmp_path / "resume.docx"
    docx_path.write_bytes(b"not a real docx")

    with pytest.raises(PdfConversionError, match="not found on PATH"):
        convert_docx_to_pdf(docx_path)


def test_convert_docx_to_pdf_respects_the_soffice_env_var_override(tmp_path, monkeypatch):
    monkeypatch.setenv(pdf_export_module._SOFFICE_ENV_VAR, "/custom/path/to/soffice")
    docx_path = tmp_path / "resume.docx"
    docx_path.write_bytes(b"not a real docx")
    pdf_path = docx_path.with_suffix(".pdf")

    def fake_run(cmd, **kwargs):
        assert cmd[0] == "/custom/path/to/soffice"
        pdf_path.write_bytes(b"%PDF-fake")
        return MagicMock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(pdf_export_module.subprocess, "run", fake_run)

    result = convert_docx_to_pdf(docx_path)

    assert result == pdf_path
    assert pdf_path.exists()


def test_convert_docx_to_pdf_raises_when_the_source_file_is_missing(tmp_path, monkeypatch):
    monkeypatch.setenv(pdf_export_module._SOFFICE_ENV_VAR, "/custom/soffice")

    with pytest.raises(PdfConversionError, match="No such file"):
        convert_docx_to_pdf(tmp_path / "does_not_exist.docx")


def test_convert_docx_to_pdf_raises_on_a_nonzero_exit(tmp_path, monkeypatch):
    monkeypatch.setenv(pdf_export_module._SOFFICE_ENV_VAR, "/custom/soffice")
    docx_path = tmp_path / "resume.docx"
    docx_path.write_bytes(b"not a real docx")

    monkeypatch.setattr(
        pdf_export_module.subprocess, "run", lambda cmd, **kwargs: MagicMock(returncode=1, stdout="", stderr="boom")
    )

    with pytest.raises(PdfConversionError, match="boom"):
        convert_docx_to_pdf(docx_path)


def test_convert_docx_to_pdf_raises_when_exit_is_zero_but_no_pdf_appeared(tmp_path, monkeypatch):
    # A real-world LibreOffice quirk: it can exit 0 while silently failing to
    # produce output (e.g. a corrupt input file) - trusting the exit code
    # alone would report success on an unusable/missing PDF.
    monkeypatch.setenv(pdf_export_module._SOFFICE_ENV_VAR, "/custom/soffice")
    docx_path = tmp_path / "resume.docx"
    docx_path.write_bytes(b"not a real docx")

    monkeypatch.setattr(
        pdf_export_module.subprocess, "run", lambda cmd, **kwargs: MagicMock(returncode=0, stdout="", stderr="")
    )

    with pytest.raises(PdfConversionError, match="exit 0"):
        convert_docx_to_pdf(docx_path)


def test_convert_docx_to_pdf_raises_a_pdf_conversion_error_on_timeout(tmp_path, monkeypatch):
    monkeypatch.setenv(pdf_export_module._SOFFICE_ENV_VAR, "/custom/soffice")
    docx_path = tmp_path / "resume.docx"
    docx_path.write_bytes(b"not a real docx")

    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout", 60))

    monkeypatch.setattr(pdf_export_module.subprocess, "run", fake_run)

    with pytest.raises(PdfConversionError, match="timed out"):
        convert_docx_to_pdf(docx_path)


def test_convert_docx_to_pdf_actually_renders_a_real_docx_via_libreoffice(tmp_path):
    try:
        pdf_export_module._find_soffice()
    except PdfConversionError:
        pytest.skip("LibreOffice ('soffice') not installed on this machine")

    import docx

    docx_path = tmp_path / "real.docx"
    doc = docx.Document()
    doc.add_paragraph("A real paragraph for a real conversion test.")
    doc.save(docx_path)

    result = convert_docx_to_pdf(docx_path)

    assert result == docx_path.with_suffix(".pdf")
    assert result.exists()
    assert result.read_bytes().startswith(b"%PDF")
