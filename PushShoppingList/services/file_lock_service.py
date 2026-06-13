import contextlib
import os
import time
from pathlib import Path

from PushShoppingList.services.storage_service import workspace_data_root


DEFAULT_LOCK_TIMEOUT_SECONDS = 300
DEFAULT_STALE_LOCK_SECONDS = 30 * 60


class WorkspaceLockTimeout(TimeoutError):
    pass


def _lock_timeout_seconds():
    try:
        return max(1, int(os.getenv("WORKSPACE_WRITE_LOCK_TIMEOUT_SECONDS", str(DEFAULT_LOCK_TIMEOUT_SECONDS))))
    except (TypeError, ValueError):
        return DEFAULT_LOCK_TIMEOUT_SECONDS


def _stale_lock_seconds():
    try:
        return max(30, int(os.getenv("WORKSPACE_WRITE_LOCK_STALE_SECONDS", str(DEFAULT_STALE_LOCK_SECONDS))))
    except (TypeError, ValueError):
        return DEFAULT_STALE_LOCK_SECONDS


def _lock_root():
    root = workspace_data_root() / ".locks"
    root.mkdir(parents=True, exist_ok=True)
    return root


@contextlib.contextmanager
def workspace_write_lock(name="imports", timeout_seconds=None):
    lock_name = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in str(name or "imports"))
    lock_dir = _lock_root() / f"{lock_name}.lock"
    owner_path = lock_dir / "owner.txt"
    timeout = _lock_timeout_seconds() if timeout_seconds is None else max(1, int(timeout_seconds))
    stale_after = _stale_lock_seconds()
    owner = f"pid={os.getpid()} time={time.time():.3f}"
    started = time.monotonic()
    acquired = False

    while not acquired:
        try:
            lock_dir.mkdir()
            owner_path.write_text(owner, encoding="utf-8")
            acquired = True
            break
        except FileExistsError:
            try:
                age = time.time() - lock_dir.stat().st_mtime
            except OSError:
                age = 0
            if age > stale_after:
                try:
                    owner_path.unlink(missing_ok=True)
                    lock_dir.rmdir()
                    continue
                except OSError:
                    pass
            if time.monotonic() - started > timeout:
                raise WorkspaceLockTimeout(f"Timed out waiting for workspace write lock: {lock_name}")
            time.sleep(0.1)

    try:
        yield Path(lock_dir)
    finally:
        if acquired:
            try:
                owner_path.unlink(missing_ok=True)
                lock_dir.rmdir()
            except OSError:
                pass
