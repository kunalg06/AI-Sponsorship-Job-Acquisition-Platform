import httpx
import pytest
from google.genai._gaos import errors as gaos_response_errors
from google.genai._gaos.lib import compat_errors
from pydantic import ValidationError

from llm_errors import GEMINI_CALL_EXCEPTIONS, raise_llm_call_failure

_FAKE_REQUEST = httpx.Request("POST", "https://example.com")


def test_raise_llm_call_failure_raises_system_exit_with_prefixed_message():
    original = compat_errors.APIConnectionError(message="Connection refused", request=_FAKE_REQUEST)

    with pytest.raises(SystemExit, match="Something failed: Connection refused") as exc_info:
        raise_llm_call_failure("Something failed", original)
    assert exc_info.value.__cause__ is original


def test_raise_llm_call_failure_falls_back_to_type_name_when_message_is_empty():
    original = httpx.HTTPError("")

    with pytest.raises(SystemExit, match="Something failed: HTTPError"):
        raise_llm_call_failure("Something failed", original)


def test_raise_llm_call_failure_prints_original_traceback_to_stderr(capsys):
    original = httpx.ConnectError("Connection refused")

    with pytest.raises(SystemExit):
        raise_llm_call_failure("Something failed", original)

    captured = capsys.readouterr()
    assert "ConnectError" in captured.err
    assert "Connection refused" in captured.err
    assert captured.out == ""


def test_raise_llm_call_failure_is_safe_to_call_outside_an_active_except_block():
    # A caller that formats a validation_error saved from an earlier except
    # block (e.g. tailor.py's retry loop) must still get the right
    # traceback - not "NoneType: None" from an empty ambient sys.exc_info().
    original = ValidationError.from_exception_data("Model", [])

    try:
        raise original
    except ValidationError:
        pass

    with pytest.raises(SystemExit):
        raise_llm_call_failure("Something failed", original)


def test_gemini_call_exceptions_covers_connection_and_response_validation_errors():
    connection_error = compat_errors.APIConnectionError(message="down", request=_FAKE_REQUEST)
    response = httpx.Response(200, request=_FAKE_REQUEST)
    validation_error = gaos_response_errors.ResponseValidationError("bad shape", response, ValueError("inner"))

    assert isinstance(connection_error, GEMINI_CALL_EXCEPTIONS)
    assert isinstance(validation_error, GEMINI_CALL_EXCEPTIONS)


def test_gemini_call_exceptions_does_not_cover_the_unrelated_public_errors_hierarchy():
    from google.genai import errors as public_genai_errors

    original = public_genai_errors.APIError(500, {"message": "Internal error", "status": "INTERNAL"})

    assert not isinstance(original, GEMINI_CALL_EXCEPTIONS)
