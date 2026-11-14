"""Tests for pipeline/tolerant.py (downloads that survive a few failures). No third-party packages needed.

Run from the repository root:  python3 test/test_tolerant.py -v
"""
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from tolerant import TooFewDownloads, download_tolerant  # noqa: E402


class Flaky:
    """work(item) that fails for chosen items and records every call."""

    def __init__(self, bad=(), exc=RuntimeError, delay=0.0):
        self.bad, self.exc, self.delay, self.calls, self.lock = set(bad), exc, delay, [], threading.Lock()

    def __call__(self, item):
        with self.lock:
            self.calls.append(item)
        if self.delay:
            time.sleep(self.delay)
        if item in self.bad:
            raise self.exc(f"gave up on {item}")
        return "new"


class DownloadTolerantTests(unittest.TestCase):
    def test_everything_works(self):
        w = Flaky()
        r = download_tolerant(range(20), w)
        self.assertEqual((r.ok, r.total, r.failed), (20, 20, []))
        self.assertEqual(sorted(w.calls), list(range(20)))

    def test_a_failure_does_not_stop_the_rest(self):
        # the bug: one item that gives up used to end the whole run
        w = Flaky(bad={4})
        r = download_tolerant(range(30), w)
        self.assertEqual(r.ok, 29)
        self.assertEqual([i for i, _ in r.failed], [4])
        self.assertIn("gave up on 4", r.failed[0][1])
        self.assertEqual(sorted(w.calls), list(range(30)), "every item must still be tried")

    def test_many_failures_are_all_recorded_in_order(self):
        r = download_tolerant(range(10), Flaky(bad={7, 2, 5}))
        self.assertEqual(r.ok, 7)
        self.assertEqual([i for i, _ in r.failed], [2, 5, 7])

    def test_too_few_working_raises_with_the_numbers(self):
        with self.assertRaises(TooFewDownloads) as cm:
            download_tolerant(range(10), Flaky(bad=set(range(6))), min_ok_fraction=0.5)
        e = cm.exception
        self.assertEqual((e.ok, e.total, e.needed, len(e.failed)), (4, 10, 5, 6))
        self.assertIn("only 4 of 10 downloaded", str(e))
        self.assertIn("at least 5 are needed", str(e))

    def test_it_still_tries_every_item_before_giving_up(self):
        w = Flaky(bad=set(range(8)))
        with self.assertRaises(TooFewDownloads):
            download_tolerant(range(10), w)
        self.assertEqual(sorted(w.calls), list(range(10)))

    def test_exactly_at_the_limit_is_accepted(self):
        r = download_tolerant(range(10), Flaky(bad=set(range(5))), min_ok_fraction=0.5)
        self.assertEqual(r.ok, 5)
        r = download_tolerant(range(3), Flaky(bad={0}), min_ok_fraction=0.5)   # 2 of 3 when 1.5 is needed: rounds up to 2
        self.assertEqual(r.ok, 2)
        with self.assertRaises(TooFewDownloads):
            download_tolerant(range(3), Flaky(bad={0, 1}), min_ok_fraction=0.5)

    def test_the_limit_can_be_changed(self):
        download_tolerant(range(10), Flaky(bad=set(range(9))), min_ok_fraction=0.1)    # 1 of 10 is enough here
        with self.assertRaises(TooFewDownloads):
            download_tolerant(range(10), Flaky(bad={0}), min_ok_fraction=1.0)          # nothing may fail

    def test_nothing_to_download_is_fine(self):
        r = download_tolerant([], Flaky())
        self.assertEqual((r.ok, r.total, r.failed), (0, 0, []))

    def test_any_ordinary_exception_is_tolerated(self):
        for exc in (ValueError, OSError, KeyError, TimeoutError):
            r = download_tolerant(range(10), Flaky(bad={3}, exc=exc))
            self.assertEqual(r.ok, 9, exc.__name__)
            self.assertTrue(r.failed[0][1].startswith(exc.__name__))

    def test_ctrl_c_is_not_swallowed(self):
        def work(item):
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            download_tolerant(range(3), work, workers=1)

    def test_progress_counts_up_to_the_total_and_reports_failures(self):
        seen = []
        download_tolerant(range(12), Flaky(bad={1, 9}), on_progress=lambda d, t, f: seen.append((d, t, f)))
        self.assertEqual([d for d, _, _ in seen], list(range(1, 13)))
        self.assertTrue(all(t == 12 for _, t, _ in seen))
        self.assertEqual(seen[-1], (12, 12, 2))

    def test_work_really_runs_in_parallel(self):
        t0 = time.time()
        download_tolerant(range(6), Flaky(delay=0.2), workers=3)
        self.assertLess(time.time() - t0, 0.9, "6 items of 0.2 s on 3 workers should take about 0.4 s, not 1.2 s")

    def test_single_worker_and_zero_workers_still_work(self):
        self.assertEqual(download_tolerant(range(5), Flaky(), workers=1).ok, 5)
        self.assertEqual(download_tolerant(range(5), Flaky(), workers=0).ok, 5)     # never fewer than one worker

    def test_items_can_be_any_iterable(self):
        self.assertEqual(download_tolerant((x for x in "abcd"), Flaky(bad={"c"})).ok, 3)


if __name__ == "__main__":
    unittest.main()
