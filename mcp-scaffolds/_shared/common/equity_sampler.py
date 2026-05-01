"""equity_sampler — registra muestras (balance, equity) en disco para que el
chart del dashboard sobreviva refresh / cierre de browser / multi-tab.

Antes el sparkline de LiveDashboard solo guardaba samples en `useState`
de React: cada vez que el usuario recargaba o abría el sitio en otro
device, el chart arrancaba desde cero. Ahora hay un thread en el backend
que cada N segundos lee el balance live de MT5 y lo persiste en
``state/equity_samples.jsonl``. El frontend lee esa fuente al montar
y luego añade ticks nuevos en memoria.

Persistencia: JSONL append-only, una línea por sample. Rotación por
TAMAÑO (default 5 MB) — al rotar, mantenemos solo las últimas 12h
para evitar archivo gigante.

Reset: cuando el usuario hace /api/capital/reset o /deposit o /withdrawal,
los samples viejos se archivan (no borran) y empieza una serie nueva.
Esto da chart "limpio" desde el evento sin perder histórico.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterable

_STATE_DIR_ENV = os.environ.get("STATE_DIR", "").strip()
_FILE = Path(os.path.expanduser(
    os.environ.get(
        "EQUITY_SAMPLES_FILE",
        f"{_STATE_DIR_ENV}/equity_samples.jsonl"
        if _STATE_DIR_ENV
        else "/opt/trading-bot/state/equity_samples.jsonl",
    )
))

# Cuántos segundos entre samples (default 30s = 2880 samples/día)
SAMPLE_INTERVAL_SEC = int(os.environ.get("EQUITY_SAMPLE_INTERVAL_SEC", "30"))

# Tamaño máximo del archivo antes de rotar (5 MB ≈ ~50k líneas)
MAX_FILE_BYTES = int(os.environ.get("EQUITY_SAMPLES_MAX_BYTES", str(5 * 1024 * 1024)))

# Cuántas horas de histórico conservar al rotar
ROTATE_KEEP_HOURS = int(os.environ.get("EQUITY_SAMPLES_KEEP_HOURS", "12"))

_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def record(balance: float, equity: float | None = None) -> None:
    """Append una sample al archivo. Best-effort — nunca lanza."""
    try:
        _FILE.parent.mkdir(parents=True, exist_ok=True)
        eq = float(equity) if equity is not None else float(balance)
        line = json.dumps({
            "ts": _now_iso(),
            "balance": round(float(balance), 4),
            "equity": round(eq, 4),
        }, default=str)
        with _lock:
            with open(_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            _maybe_rotate()
    except Exception:
        pass


def _maybe_rotate() -> None:
    """Caller debe tener _lock. Si el archivo es muy grande, rota."""
    try:
        if not _FILE.exists():
            return
        size = _FILE.stat().st_size
        if size < MAX_FILE_BYTES:
            return
        # Estrategia simple: leer, filtrar últimas N horas, reescribir.
        cutoff = datetime.now(timezone.utc) - timedelta(hours=ROTATE_KEEP_HOURS)
        keep = []
        with open(_FILE, "r", encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                    ts = datetime.fromisoformat(str(obj["ts"]).replace("Z", "+00:00"))
                    if ts >= cutoff:
                        keep.append(raw)
                except Exception:
                    continue
        tmp = _FILE.with_suffix(".jsonl.tmp")
        tmp.write_text("\n".join(keep) + ("\n" if keep else ""), encoding="utf-8")
        os.replace(tmp, _FILE)
    except Exception:
        pass


def get_samples(*, hours: float = 24.0, max_n: int = 1000) -> list[dict]:
    """Retorna samples ordenadas (más vieja → más reciente).

    Args:
      hours: ventana en horas hacia atrás. None/0 para "todo el archivo".
      max_n: cap absoluto. Si hay más, se devuelven samples uniformemente
        distribuidas en el tiempo (downsample, no las últimas N).
    """
    if not _FILE.exists():
        return []
    cutoff = None
    if hours and hours > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    samples = []
    try:
        with open(_FILE, "r", encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                    if cutoff:
                        ts = datetime.fromisoformat(str(obj["ts"]).replace("Z", "+00:00"))
                        if ts < cutoff:
                            continue
                    samples.append({
                        "ts": obj["ts"],
                        "balance": float(obj.get("balance", 0)),
                        "equity": float(obj.get("equity", obj.get("balance", 0))),
                    })
                except Exception:
                    continue
    except OSError:
        return []
    if len(samples) <= max_n:
        return samples
    # Downsample: tomar 1 cada step para llegar aprox a max_n
    step = max(1, len(samples) // max_n)
    return samples[::step][-max_n:]


def reset(archive: bool = True) -> dict:
    """Limpia el archivo de samples. Si archive=True, lo renombra con
    timestamp en lugar de borrar (preserva histórico para post-mortem)."""
    with _lock:
        if not _FILE.exists():
            return {"ok": True, "archived": None}
        if archive:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            archived = _FILE.with_suffix(f".jsonl.{ts}")
            try:
                _FILE.rename(archived)
                return {"ok": True, "archived": str(archived)}
            except OSError as exc:
                return {"ok": False, "reason": "RENAME_FAILED",
                        "detail": str(exc)}
        else:
            try:
                _FILE.unlink()
                return {"ok": True, "archived": None}
            except OSError as exc:
                return {"ok": False, "reason": "UNLINK_FAILED",
                        "detail": str(exc)}


def stats() -> dict:
    """Diagnóstico: tamaño del archivo, primer/último sample."""
    if not _FILE.exists():
        return {"exists": False, "count": 0}
    try:
        size = _FILE.stat().st_size
        first = None
        last = None
        count = 0
        with open(_FILE, "r", encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                count += 1
                try:
                    obj = json.loads(raw)
                    if first is None:
                        first = obj
                    last = obj
                except Exception:
                    continue
        return {
            "exists": True,
            "path": str(_FILE),
            "size_bytes": size,
            "count": count,
            "first": first,
            "last": last,
            "interval_sec": SAMPLE_INTERVAL_SEC,
        }
    except OSError as exc:
        return {"exists": False, "error": str(exc)}


# ──────────────────────────── background sampler ────────────────────────────

_LOCK_FILE = Path(os.path.expanduser(
    os.environ.get(
        "EQUITY_SAMPLER_LOCK_FILE",
        f"{_STATE_DIR_ENV}/equity_sampler.lock"
        if _STATE_DIR_ENV
        else "/opt/trading-bot/state/equity_sampler.lock",
    )
))


class SamplerThread(threading.Thread):
    """Thread que llama a ``read_callback()`` cada SAMPLE_INTERVAL_SEC y
    persiste el resultado.

    Usa un file lock global (fcntl.flock o msvcrt.locking) para que cuando
    uvicorn corre con multiples workers, SOLO UNO escriba samples al archivo.
    Los otros workers spawnean el thread pero exiten al no obtener el lock.

    ``read_callback`` debe retornar ``(balance, equity)`` o lanzar excepción.
    Si lanza, se loggea pero el thread continúa.
    """

    def __init__(self, read_callback, interval_sec: int = None,
                 name: str = "equity-sampler"):
        super().__init__(name=name, daemon=True)
        self.read_callback = read_callback
        self.interval = int(interval_sec or SAMPLE_INTERVAL_SEC)
        self._stop = threading.Event()
        self._last_logged = 0.0
        self._lock_fh = None

    def _acquire_lock(self) -> bool:
        """True si soy el único sampler. False si otro proceso ya tiene el lock."""
        try:
            _LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
            self._lock_fh = open(_LOCK_FILE, "a+")
            if os.name == "nt":
                import msvcrt
                try:
                    msvcrt.locking(self._lock_fh.fileno(), msvcrt.LK_NBLCK, 1)
                    return True
                except OSError:
                    self._lock_fh.close()
                    self._lock_fh = None
                    return False
            else:
                import fcntl
                try:
                    fcntl.flock(self._lock_fh.fileno(),
                                fcntl.LOCK_EX | fcntl.LOCK_NB)
                    # Escribir PID para diagnóstico
                    self._lock_fh.seek(0)
                    self._lock_fh.truncate()
                    self._lock_fh.write(f"{os.getpid()}\n")
                    self._lock_fh.flush()
                    return True
                except OSError:
                    self._lock_fh.close()
                    self._lock_fh = None
                    return False
        except Exception:
            if self._lock_fh:
                try:
                    self._lock_fh.close()
                except Exception:
                    pass
                self._lock_fh = None
            return False

    def _release_lock(self) -> None:
        if self._lock_fh is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                try:
                    self._lock_fh.seek(0)
                    msvcrt.locking(self._lock_fh.fileno(),
                                   msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl
                try:
                    fcntl.flock(self._lock_fh.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
        finally:
            try:
                self._lock_fh.close()
            except Exception:
                pass
            self._lock_fh = None

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        # Esperá un poco antes del primer sample para que el sistema
        # termine de inicializar todo (MT5, mongo, etc).
        self._stop.wait(5)
        if not self._acquire_lock():
            # Otro worker ya está sampleando — exit limpio.
            return
        try:
            while not self._stop.is_set():
                try:
                    result = self.read_callback()
                    if result is not None:
                        bal, eq = result
                        if bal is not None and bal > 0:
                            record(bal, eq)
                except Exception:
                    now = time.time()
                    if now - self._last_logged > 300:
                        import sys as _sys
                        _sys.stderr.write("equity_sampler: read failed\n")
                        self._last_logged = now
                self._stop.wait(self.interval)
        finally:
            self._release_lock()
