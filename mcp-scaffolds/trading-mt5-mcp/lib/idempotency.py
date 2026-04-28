"""Client-order-id cache. 60 s TTL, disk-backed, with pre-flight PENDING marker.

If the same ``client_order_id`` arrives twice within the window, the second
call returns the first response without contacting MT5. Lets Claude / the
sync poller retry safely.

Three concrete safety properties this module gives:

  1. **Pre-flight marker** — before ``mt5.order_send``, the caller writes a
     PENDING entry via ``mark_pending(coid)``. If the process crashes between
     ``order_send`` and the post-write, on the next restart ``check(coid)``
     sees PENDING and the caller MUST reconcile with MT5 history (search by
     comment == coid) before deciding to re-submit. This eliminates the
     classic "double-fire on crash" race.

  2. **Disk-backed** — cache is persisted to ``~/mcp/state/idempotency.json``,
     so a process restart does NOT silently empty the 60 s replay window.

  3. **TTL purge** — entries older than ``_TTL_SECONDS`` are removed on
     every check, keeping the file small.

Backwards-compatible API: ``check`` and ``remember`` keep their old
signatures and behaviour. Callers may opt into ``mark_pending`` for the
crash-safety property; the existing call sites do not need to change for
the persistence + TTL improvements to take effect.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Optional

_TTL_SECONDS = 60.0
_PENDING = "__PENDING__"

# Disk path. Honours $LOG_DIR (same env var the bot uses for ~/mcp/logs);
# state/ lives next to logs/ by default so users only have to back up one root.
_STATE_DIR = Path(os.path.expanduser(os.environ.get("LOG_DIR", "~/mcp/logs"))) \
    .parent / "state"
_STATE_FILE = _STATE_DIR / "idempotency.json"

_lock = threading.Lock()
_recent: dict = {}      # coid -> (ts, result_or_PENDING)
_loaded = False         # lazy-load on first call


def _load_if_needed() -> None:
    """Read the cache from disk on first use. Bad/missing file → empty cache."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        if _STATE_FILE.exists():
            data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
            # data is a list of [coid, ts, result_or_pending]
            for coid, ts, value in data:
                _recent[coid] = (float(ts), value)
            _purge_locked()  # drop any stale entries from previous run
    except (OSError, ValueError, TypeError):
        # Corrupt file: ignore and start fresh. We do NOT delete it — a human
        # may want to inspect it. Next write will overwrite.
        _recent.clear()


def _save_locked() -> None:
    """Write the cache to disk. Caller must hold ``_lock``."""
    try:
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        # Tuples → lists for JSON
        payload = [[coid, ts, value] for coid, (ts, value) in _recent.items()]
        # Atomic write: tmp + rename so an interrupted write can't corrupt
        # the file mid-flight.
        tmp = _STATE_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, default=str), encoding="utf-8")
        os.replace(tmp, _STATE_FILE)
    except OSError:
        # Best effort. The in-memory cache still works, we just lose
        # crash-safety for this entry.
        pass


def _purge_locked() -> None:
    """Drop entries older than TTL. Caller must hold ``_lock``."""
    now = time.time()
    stale = [k for k, (ts, _) in _recent.items() if now - ts > _TTL_SECONDS]
    for k in stale:
        del _recent[k]


def check(coid: Optional[str]):
    """Return the cached result for ``coid``, or ``None`` if not seen.

    A return of the special token ``__PENDING__`` means the caller previously
    flagged this coid as in-flight via ``mark_pending`` but never wrote a
    result — i.e. the previous attempt likely crashed mid-send. Caller MUST
    reconcile with MT5 history (search by ``comment == coid``) before
    deciding to re-submit.
    """
    if not coid:
        return None
    with _lock:
        _load_if_needed()
        _purge_locked()
        entry = _recent.get(coid)
        if entry is None:
            return None
        return entry[1]


def is_pending(value: Any) -> bool:
    """True iff ``value`` is the PENDING sentinel returned by ``check``."""
    return value == _PENDING


def mark_pending(coid: Optional[str]) -> None:
    """Write a PENDING marker BEFORE the broker call. If the process dies
    between this call and ``remember``, the next ``check`` will report
    ``__PENDING__`` and the caller can reconcile rather than re-fire."""
    if not coid:
        return
    with _lock:
        _load_if_needed()
        _recent[coid] = (time.time(), _PENDING)
        _save_locked()


def remember(coid: Optional[str], result: dict) -> dict:
    """Cache the final result and persist to disk. Idempotent."""
    if coid:
        with _lock:
            _load_if_needed()
            _recent[coid] = (time.time(), result)
            _save_locked()
    return result


def reset() -> None:
    """Clear cache (memory + disk). Used by tests."""
    with _lock:
        _recent.clear()
        try:
            if _STATE_FILE.exists():
                _STATE_FILE.unlink()
        except OSError:
            pass


# Module-level alias for the sentinel, exported for callers that want to
# import the constant rather than use ``is_pending``.
PENDING = _PENDING
