"""Persistent LRU cache.

Design notes:
- In-memory LRU order via OrderedDict.
- Persistence: JSON file written atomically (temp + fsync + os.replace).
- Exclusive cross-process locking: fcntl.flock (POSIX) / msvcrt.locking (Windows).
- Fork safety: record owning PID; on first access after fork, reload from disk.
- Optional per-entry TTL (absolute unix timestamp); expired entries are dropped lazily.
- Keys are coerced to strings via str(); values must be JSON-serializable.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Optional

_IS_WIN = sys.platform.startswith("win")

if _IS_WIN:
    import msvcrt
else:
    import fcntl


class _FileLock:
    """Portable exclusive advisory file lock. Context manager."""

    def __init__(self, path: Path):
        self.path = path
        self._fh = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a+b")
        if _IS_WIN:
            # Block until lock acquired; lock 1 byte at offset 0.
            self._fh.seek(0)
            while True:
                try:
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_LOCK, 1)
                    break
                except OSError:
                    time.sleep(0.01)
        else:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        try:
            if _IS_WIN:
                self._fh.seek(0)
                try:
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        finally:
            self._fh.close()
            self._fh = None


@dataclass
class CacheConfig:
    maxsize: int = 128
    path: Optional[str] = None
    ttl: Optional[float] = None  # default TTL in seconds; None = no expiry
    autosave: bool = True

    def __post_init__(self):
        if self.maxsize <= 0:
            raise ValueError("maxsize must be > 0")


class Cache:
    """Persistent LRU cache.

    Usage:
        c = Cache(maxsize=128, path="~/.mycache.json")
        c["k"] = "v"
        v = c["k"]
        c.clear()
        c.stats()  # {"hits", "misses", "size", "maxsize"}
    """

    def __init__(
        self,
        maxsize: int = 128,
        path: Optional[str] = None,
        ttl: Optional[float] = None,
        autosave: bool = True,
    ):
        self.cfg = CacheConfig(maxsize=maxsize, path=path, ttl=ttl, autosave=autosave)
        self._data: "OrderedDict[str, tuple]" = OrderedDict()  # key -> (value, expires_at|None)
        self._hits = 0
        self._misses = 0
        self._lock = threading.RLock()
        self._owner_pid = os.getpid()
        self._path: Optional[Path] = Path(os.path.expanduser(path)).resolve() if path else None
        self._lock_path: Optional[Path] = (
            self._path.with_suffix(self._path.suffix + ".lock") if self._path else None
        )
        if self._path is not None:
            self._load()

    # ---------- persistence ----------

    def _load(self) -> None:
        if self._path is None or not self._path.exists():
            return
        try:
            with _FileLock(self._lock_path):
                raw = self._path.read_text(encoding="utf-8")
            if not raw.strip():
                return
            blob = json.loads(raw)
            items = blob.get("items", [])
            self._data.clear()
            now = time.time()
            for k, v, exp in items:
                if exp is not None and exp <= now:
                    continue
                self._data[k] = (v, exp)
            self._hits = int(blob.get("hits", 0))
            self._misses = int(blob.get("misses", 0))
        except (OSError, ValueError, json.JSONDecodeError):
            # Corrupt/unreadable state: start fresh, leave file alone.
            self._data.clear()

    def _save(self) -> None:
        if self._path is None:
            return
        blob = {
            "items": [[k, v, exp] for k, (v, exp) in self._data.items()],
            "hits": self._hits,
            "misses": self._misses,
        }
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with _FileLock(self._lock_path):
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(blob, f)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
            os.replace(tmp, self._path)

    def _check_fork(self) -> None:
        pid = os.getpid()
        if pid != self._owner_pid:
            self._owner_pid = pid
            self._data.clear()
            self._hits = 0
            self._misses = 0
            if self._path is not None:
                self._load()

    # ---------- core API ----------

    def __setitem__(self, key: Any, value: Any) -> None:
        self.set(key, value)

    def set(self, key: Any, value: Any, ttl: Optional[float] = None) -> None:
        k = str(key)
        expires_at = None
        eff_ttl = ttl if ttl is not None else self.cfg.ttl
        if eff_ttl is not None:
            expires_at = time.time() + float(eff_ttl)
        with self._lock:
            self._check_fork()
            if k in self._data:
                self._data.move_to_end(k)
            self._data[k] = (value, expires_at)
            while len(self._data) > self.cfg.maxsize:
                self._data.popitem(last=False)
            if self.cfg.autosave:
                self._save()

    def __getitem__(self, key: Any) -> Any:
        found, value = self._get(key)
        if not found:
            raise KeyError(key)
        return value

    def get(self, key: Any, default: Any = None) -> Any:
        found, value = self._get(key)
        return value if found else default

    def _get(self, key: Any):
        k = str(key)
        with self._lock:
            self._check_fork()
            if k not in self._data:
                self._misses += 1
                return False, None
            value, exp = self._data[k]
            if exp is not None and exp <= time.time():
                del self._data[k]
                self._misses += 1
                if self.cfg.autosave:
                    self._save()
                return False, None
            self._data.move_to_end(k)
            self._hits += 1
            return True, value

    def __contains__(self, key: Any) -> bool:
        found, _ = self._get(key)
        return found

    def __len__(self) -> int:
        with self._lock:
            self._check_fork()
            return len(self._data)

    def __delitem__(self, key: Any) -> None:
        k = str(key)
        with self._lock:
            self._check_fork()
            if k not in self._data:
                raise KeyError(key)
            del self._data[k]
            if self.cfg.autosave:
                self._save()

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._hits = 0
            self._misses = 0
            if self._path is not None and self._path.exists():
                with _FileLock(self._lock_path):
                    try:
                        self._path.unlink()
                    except OSError:
                        pass

    def stats(self) -> dict:
        with self._lock:
            self._check_fork()
            return {
                "hits": self._hits,
                "misses": self._misses,
                "size": len(self._data),
                "maxsize": self.cfg.maxsize,
            }

    def flush(self) -> None:
        """Force write to disk (no-op if autosave is on and no pending changes)."""
        with self._lock:
            self._save()


def persistent_lru_cache(
    maxsize: int = 128,
    path: Optional[str] = None,
    ttl: Optional[float] = None,
) -> Callable:
    """Decorator: drop-in alternative to functools.lru_cache with disk persistence.

    The cache key is repr(args)+repr(sorted(kwargs.items())); values returned by the
    wrapped function must be JSON-serializable.
    """

    def decorator(fn: Callable) -> Callable:
        cache = Cache(maxsize=maxsize, path=path, ttl=ttl)

        @wraps(fn)
        def wrapper(*args, **kwargs):
            key = repr(args) + "|" + repr(sorted(kwargs.items()))
            found, value = cache._get(key)
            if found:
                return value
            value = fn(*args, **kwargs)
            cache.set(key, value)
            return value

        wrapper.cache = cache  # type: ignore[attr-defined]
        wrapper.cache_clear = cache.clear  # type: ignore[attr-defined]
        wrapper.cache_stats = cache.stats  # type: ignore[attr-defined]
        return wrapper

    return decorator
