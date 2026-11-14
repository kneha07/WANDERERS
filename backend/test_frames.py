"""get_frames and its cache with the network faked (IRSA SIA, S3, Gaia): no network, no real FITS files."""
import json
import os
import time

import numpy as np
import pytest
from fastapi import HTTPException

from backend import spherex

DAY = 86400


class FakeSky:
    """Stands in for IRSA SIA, the S3 images and Gaia. Each image is a fixed star at the view center whose brightness
    depends on the detector (as in SPHEREx: each detector sees a star at a different wavelength)."""

    def __init__(self, epochs, bright=None):
        self.epochs = epochs  # [(mjd, ["D1", "D2"]), ...]
        self.bright = bright or {}
        self.fail = set()  # urls that raise a network error
        self.builds = 0

    def query_images(self, center, stats=None):
        self.builds += 1
        return [{"mjd": mjd + 0.01 * k, "detector": d, "url": f"{d}@{mjd}", "em_min": 1.0, "em_max": 2.0}
                for mjd, dets in self.epochs for k, d in enumerate(dets)]

    def read_cutout(self, url, ra, dec):
        if url in self.fail:
            raise OSError("S3 connection reset")
        n = ra.shape[0]
        yy, xx = np.indices((n, n))
        c = (n - 1) / 2
        star = self.bright.get(url.split("@")[0], 50.0) * np.exp(-((xx - c) ** 2 + (yy - c) ** 2) / 2.0)
        return star + np.random.default_rng(len(url)).normal(0, 0.1, (n, n))


@pytest.fixture
def sky(tmp_path, monkeypatch):
    fake = FakeSky([(60000.0, ["D1", "D2"]), (60200.0, ["D1", "D2"])])
    monkeypatch.setattr(spherex, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(spherex, "query_images", fake.query_images)
    monkeypatch.setattr(spherex, "read_cutout", fake.read_cutout)
    monkeypatch.setattr(spherex, "gaia_field", lambda center, radius: [])
    monkeypatch.setattr(spherex.time, "sleep", lambda s: None)
    return fake


def frames(**kw):
    return spherex.get_frames("10 20", fov=2, per_group=2, **kw)


def age_cache(tmp_path, seconds):
    for p in tmp_path.glob("*.json"):
        t = time.time() - seconds
        os.utime(p, (t, t))


def test_a_complete_build_is_cached_for_7_days_then_rebuilt(sky, tmp_path):
    assert frames()["cached"] is False
    again = frames()
    assert (again["cached"], again["quality"]["cache_age_s"] <= 2, sky.builds) == (True, True, 1)
    age_cache(tmp_path, 6 * DAY)
    assert frames()["quality"]["cache_age_s"] == pytest.approx(6 * DAY, abs=5)
    age_cache(tmp_path, 8 * DAY)  # QR3 adds surveys every week: an old answer can miss them
    assert (frames()["cached"], sky.builds) == (False, 2)


def test_a_build_with_failed_images_is_kept_for_one_hour_only(sky, tmp_path):
    sky.fail = {"D2@60200.0"}
    first = frames()
    assert (first["n_failed"], first["cached"]) == (1, False)
    assert any("not kept" in n for n in first["notes"])
    assert frames()["cached"] is True  # a reload within the hour does not rebuild
    age_cache(tmp_path, 2 * 3600)
    sky.fail = set()
    assert (frames()["n_failed"], sky.builds) == (0, 2)


def test_an_old_answer_is_served_with_a_note_when_irsa_is_down(sky, tmp_path):
    frames()
    age_cache(tmp_path, 8 * DAY)
    def down(center, stats=None):
        raise HTTPException(502, "IRSA did not answer")
    spherex.query_images = down  # monkeypatch restores the fake's original at teardown
    old = frames()
    assert old["cached"] is True
    assert any("IRSA did not answer" in n for n in old["notes"])


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
