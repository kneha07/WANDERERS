"""Run many downloads on a few threads without letting one stubborn failure stop the rest.

IRSA answers "503 busy" often during busy periods. pipeline/get() retries each request a few times and then gives up. With
ThreadPoolExecutor.map, the first item that gave up re-raised and ended the whole fetch, even when most other items had
downloaded fine. That is what happened on the first real run of this pipeline: 29 cutouts came down, one gave up, and the
run ended with exit code 1.

download_tolerant() records a failed item and carries on. It raises only when too few items worked for the result to be
useful. No third-party packages are needed, so it can be tested anywhere.
"""
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed


class TooFewDownloads(RuntimeError):
    """Not enough items downloaded. Carries the numbers so the caller can say them plainly."""

    def __init__(self, ok, total, needed, failed):
        self.ok, self.total, self.needed, self.failed = ok, total, needed, failed
        first = f" First error: {failed[0][1]}" if failed else ""
        super().__init__(f"only {ok} of {total} downloaded (at least {needed} are needed); {len(failed)} failed.{first}")


class Result:
    def __init__(self, ok, total, failed):
        self.ok, self.total, self.failed = ok, total, failed   # failed: [(index, message), ...]

    def __repr__(self):
        return f"Result(ok={self.ok}, total={self.total}, failed={len(self.failed)})"


def download_tolerant(items, work, workers=3, min_ok_fraction=0.5, on_progress=None):
    """Call work(item) for each item on `workers` threads. Returns a Result.

    An item whose work() raises an Exception counts as failed and is skipped. Items that return normally (including
    "already cached") count as ok. If the share of ok items is below min_ok_fraction, TooFewDownloads is raised after
    every item has been tried. on_progress(done, total, n_failed) is called after each item, from the calling thread.
    KeyboardInterrupt and SystemExit are not swallowed.
    """
    items = list(items)
    total = len(items)
    if total == 0:
        return Result(0, 0, [])
    failed, ok, done = [], 0, 0
    lock = threading.Lock()   # the failed list is shared by the worker threads

    def run(i, item):
        try:
            work(item)
            return i, None
        except Exception as exc:                       # noqa: BLE001  one bad item must not stop the others
            return i, f"{type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(max(1, workers)) as ex:
        futures = [ex.submit(run, i, item) for i, item in enumerate(items)]
        for fut in as_completed(futures):
            i, err = fut.result()
            with lock:
                if err is None:
                    ok += 1
                else:
                    failed.append((i, err))
                done += 1
                n_failed = len(failed)
            if on_progress:
                on_progress(done, total, n_failed)

    failed.sort()
    needed = int(-(-total * min_ok_fraction // 1))     # round up
    if ok < needed:
        raise TooFewDownloads(ok, total, needed, failed)
    return Result(ok, total, failed)
