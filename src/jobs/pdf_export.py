"""Best-effort .docx -> PDF conversion for tailored resumes/cover letters.

Renders via a headless LibreOffice subprocess rather than re-deriving a PDF
from scratch (e.g. docx -> HTML -> PDF) - `jobs.docx_tailor`'s whole design
is built around never letting the original .docx's formatting drift, so PDF
export should render that already-correct file exactly as Word would show
it, not reinterpret it through a lossy intermediate format.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

_SOFFICE_ENV_VAR = "SOFFICE_PATH"
# winget's standard install location on Windows - `soffice` isn't
# automatically added to PATH there, unlike the apt package this project's
# packages.txt installs for Streamlit Cloud (Linux `soffice` is on PATH).
_DEFAULT_WINDOWS_SOFFICE = r"C:\Program Files\LibreOffice\program\soffice.exe"


class PdfConversionError(RuntimeError):
    """LibreOffice isn't available, or the conversion itself failed."""


def _find_soffice() -> str:
    override = os.environ.get(_SOFFICE_ENV_VAR)
    if override:
        return override
    found = shutil.which("soffice") or shutil.which("soffice.exe")
    if found:
        return found
    if os.name == "nt" and Path(_DEFAULT_WINDOWS_SOFFICE).exists():
        return _DEFAULT_WINDOWS_SOFFICE
    raise PdfConversionError(
        "LibreOffice ('soffice') not found on PATH. Install it, or set the "
        f"{_SOFFICE_ENV_VAR} environment variable to its full executable path."
    )


def convert_docx_to_pdf(docx_path: Path, *, timeout: float = 60.0) -> Path:
    """Convert `docx_path` to a same-named .pdf in the same directory via a
    headless LibreOffice subprocess. Returns the resulting PDF path.

    Each call spawns a fresh `soffice` process rather than reusing a shared
    instance - simpler and safer for a low-volume personal tool (no shared
    profile-lock contention between concurrent conversions), at the cost of
    a ~1-2s startup per call. Raises `PdfConversionError` on any failure
    (missing binary, non-zero exit, timeout, or the expected output file
    not appearing) so callers can show a clear message instead of a bare
    subprocess traceback."""
    soffice = _find_soffice()
    docx_path = docx_path.resolve()
    if not docx_path.exists():
        raise PdfConversionError(f"No such file: {docx_path}")

    try:
        result = subprocess.run(
            [
                soffice,
                "--headless",
                "--norestore",
                "--convert-to",
                "pdf",
                "--outdir",
                str(docx_path.parent),
                str(docx_path),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise PdfConversionError(f"LibreOffice conversion of {docx_path.name} timed out after {timeout}s") from exc

    pdf_path = docx_path.with_suffix(".pdf")
    if result.returncode != 0 or not pdf_path.exists():
        detail = result.stderr.strip() or result.stdout.strip() or "no output"
        raise PdfConversionError(f"LibreOffice conversion failed for {docx_path.name} (exit {result.returncode}): {detail}")
    return pdf_path
