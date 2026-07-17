from unittest.mock import MagicMock

import jobs.atomic_fs as atomic_fs_module
from jobs.atomic_fs import _fsync_directory


def test_fsync_directory_is_a_noop_on_non_posix(tmp_path, monkeypatch):
    monkeypatch.setattr(atomic_fs_module.os, "name", "nt")
    mock_open = MagicMock()
    monkeypatch.setattr(atomic_fs_module.os, "open", mock_open)

    _fsync_directory(tmp_path)

    mock_open.assert_not_called()


def test_fsync_directory_opens_and_fsyncs_the_directory_on_posix(tmp_path, monkeypatch):
    monkeypatch.setattr(atomic_fs_module.os, "name", "posix")
    fake_fd = object()  # a sentinel, not a real fd - can never collide with a real fd value

    def fake_open(path, flags):
        assert path == str(tmp_path)
        assert flags == atomic_fs_module.os.O_RDONLY
        return fake_fd

    mock_fsync = MagicMock()
    mock_close = MagicMock()
    monkeypatch.setattr(atomic_fs_module.os, "open", fake_open)
    monkeypatch.setattr(atomic_fs_module.os, "fsync", mock_fsync)
    monkeypatch.setattr(atomic_fs_module.os, "close", mock_close)

    _fsync_directory(tmp_path)

    mock_fsync.assert_called_once_with(fake_fd)
    mock_close.assert_called_once_with(fake_fd)


def test_fsync_directory_swallows_its_own_failure_and_warns_on_stderr(tmp_path, monkeypatch, capsys):
    # Deliberately never raises - a directory-fsync failure happens after the
    # caller's own rename already succeeded, so it must not look like the
    # write itself failed (see _atomic_write_text's docstring).
    monkeypatch.setattr(atomic_fs_module.os, "name", "posix")
    monkeypatch.setattr(
        atomic_fs_module.os, "open", MagicMock(side_effect=OSError("simulated permission denied"))
    )

    _fsync_directory(tmp_path)  # must not raise

    stderr = capsys.readouterr().err
    assert "simulated permission denied" in stderr
    assert str(tmp_path) in stderr
