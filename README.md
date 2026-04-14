# atomic-lru-cache

Persistent LRU cache that survives process restarts, forks, and crashes.
Atomic writes, portable file locking, zero dependencies, ~250 lines of Python.

```bash
pip install atomic-lru-cache
```

```python
from atomic_lru_cache import Cache

c = Cache(maxsize=128, path="~/.mycache.json")
c["key"] = "value"      # atomic write to disk
v = c["key"]            # LRU bump, read from memory
c.stats()               # {"hits": 1, "misses": 0, "size": 1, "maxsize": 128}
```

Drop-in decorator alternative to `functools.lru_cache`:

```python
from atomic_lru_cache import persistent_lru_cache

@persistent_lru_cache(maxsize=256, path="~/.myfunc_cache.json")
def expensive(x, y):
    return slow_computation(x, y)

expensive(1, 2)   # computes, writes to disk
expensive(1, 2)   # served from memory
# ...restart process...
expensive(1, 2)   # served from disk, no recomputation
```

## Why another cache?

| Feature                       | `functools.lru_cache` | `diskcache`   | `atomic-lru-cache` |
|-------------------------------|:---------------------:|:-------------:|:------------------:|
| Persists across restarts      | no                    | yes           | yes                |
| Pure stdlib                   | yes                   | no            | yes                |
| Dependencies                  | none                  | sqlite + more | none (stdlib)      |
| Lines of code                 | n/a                   | ~10,000       | ~250               |
| Atomic writes                 | n/a                   | yes (sqlite)  | yes (replace+fsync)|
| Portable file locking         | n/a                   | yes           | yes (fcntl/msvcrt) |
| Fork-safe                     | no                    | yes           | yes (PID-tracked)  |
| Per-entry TTL                 | no                    | yes           | yes                |
| Install surface               | trivial               | heavy         | trivial            |

`functools.lru_cache` is fast but dies with the process. `diskcache` is excellent
and battle-tested but pulls SQLite and thousands of lines for the common case of
"I want a small LRU that doesn't forget everything on restart." `atomic-lru-cache`
fills that gap.

## Use cases

- ML model warm-up caches (embeddings, tokenizer outputs, feature vectors)
- API response memoization across CLI invocations
- Expensive computation memoization for scripts, notebooks, batch jobs
- Small per-host caches for CI/CD helper scripts
- Cheap substitute for Redis/Memcached when you just need one file on disk

## How it works

- In-memory LRU ordering via `collections.OrderedDict`.
- Persistence: JSON blob written to a temp file, `fsync`'d, then `os.replace`'d
  over the target. No reader ever sees a half-written file.
- Cross-process exclusive locking: `fcntl.flock` on POSIX, `msvcrt.locking` on
  Windows, wrapped in a single portable context manager.
- Fork detection: the owning PID is recorded at construction; on the first access
  after a `fork()`, state is discarded and reloaded from disk, so child processes
  never write a stale snapshot back.
- Optional per-entry TTL (absolute expiry timestamp, checked lazily on read).

## 🔥 atomic-lru-cache is a powerful tool

atomic-lru-cache gives you a persistent LRU cache that survives process
restarts, forks, and crashes with atomic writes, portable file locking,
zero dependencies, and ~250 lines of code.

**What it can do:**
- Outlives your process without SQLite or Redis
- Safe under `fork()`, `exec()`, and concurrent writes
- Drop-in replacement for `functools.lru_cache` with disk persistence

**With great power comes responsibility.** This tool can silently keep stale
data across deploys — when misconfigured (wrong path, wrong TTL), it can
also serve wrong values to your app for as long as the file lives. Read the
[Disclaimer](DISCLAIMER.md) before deploying to production. You are solely
responsible for your use.

**Recommended for:**
- CLI tools, scripts, notebooks, batch jobs, ML pipelines
- Single-host services that want a durable cache without new infrastructure

**NOT recommended for:**
- Life-critical, safety-critical, or mission-critical systems
- Regulatory environments requiring formal validation (medical, aerospace, SIL)
- High-throughput shared caches across many hosts (use Redis / Memcached)
- Any use that would violate third-party terms of service

## ⚠️ Disclaimer

atomic-lru-cache is provided **AS IS**, without warranty of any kind. Use at
your own risk. You are solely responsible for your use and for compliance
with all applicable laws and third-party terms of service.

See [DISCLAIMER.md](DISCLAIMER.md) for full terms.

## Constraints

- Values must be JSON-serializable (str, int, float, bool, None, list, dict).
- Keys are coerced with `str()`. For structured keys, pass a canonical string
  form (e.g., `json.dumps(obj, sort_keys=True)`).
- File locking is advisory; all writers must go through this library.
- Designed for small-to-medium caches (thousands of entries, not millions).
  For millions of entries or huge values, use `diskcache` or a real DB.

## License

MIT. See [LICENSE](LICENSE) and [DISCLAIMER.md](DISCLAIMER.md).
