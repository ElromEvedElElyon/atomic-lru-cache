"""Tests for atomic-lru-cache."""
import os
import time
from pathlib import Path

import pytest

from atomic_lru_cache import Cache, persistent_lru_cache


def test_get_set_basic(tmp_path):
    c = Cache(maxsize=10, path=str(tmp_path / "c.json"))
    c["a"] = 1
    c["b"] = "hello"
    assert c["a"] == 1
    assert c["b"] == "hello"
    assert c.get("missing") is None
    assert c.get("missing", "def") == "def"
    assert "a" in c
    assert "missing" not in c
    assert len(c) == 2


def test_lru_eviction(tmp_path):
    c = Cache(maxsize=3, path=str(tmp_path / "c.json"))
    c["a"] = 1
    c["b"] = 2
    c["c"] = 3
    _ = c["a"]  # touch 'a' so it becomes MRU
    c["d"] = 4  # should evict 'b' (least recently used)
    assert "a" in c
    assert "b" not in c
    assert "c" in c
    assert "d" in c
    assert len(c) == 3


def test_persistence_across_reinstantiation(tmp_path):
    path = str(tmp_path / "persist.json")
    c1 = Cache(maxsize=10, path=path)
    c1["key1"] = "value1"
    c1["key2"] = [1, 2, 3]
    # Simulate process restart by dropping c1 and creating c2
    del c1
    c2 = Cache(maxsize=10, path=path)
    assert c2["key1"] == "value1"
    assert c2["key2"] == [1, 2, 3]
    assert len(c2) == 2


def test_ttl_expiry(tmp_path):
    c = Cache(maxsize=10, path=str(tmp_path / "c.json"))
    c.set("short", "v", ttl=0.1)
    c.set("long", "v", ttl=60)
    assert c["short"] == "v"
    time.sleep(0.2)
    assert c.get("short") is None
    assert c["long"] == "v"


def test_fork_safety(tmp_path):
    path = str(tmp_path / "fork.json")
    c = Cache(maxsize=10, path=path)
    c["before"] = 1
    # Spoof a PID change to trigger the fork-detection code path.
    c._owner_pid = os.getpid() + 99999
    # Next access should detect the "fork" and reload from disk, keeping 'before'.
    assert c["before"] == 1
    assert c._owner_pid == os.getpid()


def test_atomic_write_semantics(tmp_path):
    """The on-disk file should always be valid JSON — no partial writes visible."""
    path = Path(tmp_path / "atomic.json")
    c = Cache(maxsize=10, path=str(path))
    for i in range(20):
        c[f"k{i}"] = {"idx": i, "data": "x" * 100}
    # File exists, is valid JSON, and no tmp leftover.
    assert path.exists()
    import json
    raw = path.read_text(encoding="utf-8")
    blob = json.loads(raw)  # must not raise
    assert "items" in blob
    assert not any(p.name.endswith(".tmp") for p in tmp_path.iterdir())


def test_stats_and_clear(tmp_path):
    c = Cache(maxsize=5, path=str(tmp_path / "c.json"))
    c["a"] = 1
    _ = c["a"]        # hit
    _ = c["a"]        # hit
    _ = c.get("z")    # miss
    s = c.stats()
    assert s["hits"] == 2
    assert s["misses"] == 1
    assert s["size"] == 1
    assert s["maxsize"] == 5
    c.clear()
    assert len(c) == 0
    assert c.stats()["hits"] == 0


def test_persistent_lru_cache_decorator(tmp_path):
    path = str(tmp_path / "dec.json")
    calls = {"n": 0}

    @persistent_lru_cache(maxsize=8, path=path)
    def slow_add(x, y):
        calls["n"] += 1
        return x + y

    assert slow_add(1, 2) == 3
    assert slow_add(1, 2) == 3
    assert calls["n"] == 1  # second call hit cache

    # Re-decorate a fresh function on the same path -> still hits disk cache.
    @persistent_lru_cache(maxsize=8, path=path)
    def slow_add2(x, y):
        calls["n"] += 1
        return x + y

    assert slow_add2(1, 2) == 3
    assert calls["n"] == 1  # served from disk
    stats = slow_add2.cache_stats()
    assert stats["hits"] >= 1
