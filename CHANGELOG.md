# Changelog

## 0.1.0 (initial public release)

- `Cache(maxsize, path, ttl)` — persistent LRU cache with OrderedDict in memory.
- `CacheConfig` dataclass for ergonomic configuration.
- `@persistent_lru_cache` decorator — drop-in alternative to `functools.lru_cache`
  with disk persistence.
- Atomic write via `os.replace` + `fsync` (crash-safe on POSIX; best-effort on Windows).
- Portable exclusive file locking: `fcntl.flock` on POSIX, `msvcrt.locking` on Windows.
- Fork safety: PID is tracked; on first access after `fork()` the on-disk state is
  re-read before any write, avoiding stale snapshots across processes.
- Per-entry TTL support (absolute expiry timestamp).
- Zero dependencies — Python 3.9+ stdlib only.
- Thread-safe within a single process via `threading.RLock`.
- 8 unit tests covering get/set, LRU eviction, persistence across re-instantiation,
  TTL expiry, fork detection, atomic write semantics, stats, and clear.
- CI matrix: 3 OS × 4 Python versions (12 combos).
