"""get_frames and its cache with the network faked (IRSA SIA, S3, Gaia): no network, no real FITS files."""
import json
import os

import pytest

from backend import spherex


def test_cache_write_gives_up_quietly_when_windows_keeps_the_file_locked(tmp_path, monkeypatch):
    # Windows refuses os.replace while another request reads the file: PermissionError(13).
    def locked(src, dst):
        raise PermissionError(13, "The process cannot access the file because it is being used by another process")
    monkeypatch.setattr(spherex.os, "replace", locked)
    monkeypatch.setattr(spherex.time, "sleep", lambda s: None)
    assert spherex.write_json(tmp_path / "a.json", {"x": 1}) is False
    assert os.listdir(tmp_path) == []  # no .tmp file left behind


def test_cache_write_retries_a_short_lock(tmp_path, monkeypatch):
    real, calls = os.replace, []
    def busy_twice(src, dst):
        calls.append(dst)
        if len(calls) <= 2:
            raise PermissionError(13, "locked")
        real(src, dst)
    monkeypatch.setattr(spherex.os, "replace", busy_twice)
    monkeypatch.setattr(spherex.time, "sleep", lambda s: None)
    assert spherex.write_json(tmp_path / "a.json", {"x": 1}) is True
    assert json.loads((tmp_path / "a.json").read_text()) == {"x": 1}
    assert os.listdir(tmp_path) == ["a.json"]
