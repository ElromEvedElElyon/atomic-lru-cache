"""Basic usage of atomic-lru-cache.

Run twice: the second run finds results already cached on disk.
"""
import time

from atomic_lru_cache import Cache, persistent_lru_cache


def demo_direct_cache():
    cache = Cache(maxsize=64, path="~/.alc_demo.json")

    if "greeting" in cache:
        print("[hit]  greeting =", cache["greeting"])
    else:
        cache["greeting"] = "hello from atomic-lru-cache"
        print("[miss] stored greeting")

    cache.set("session", {"user": "agnes", "ts": time.time()}, ttl=30)
    print("session:", cache["session"])
    print("stats: ", cache.stats())


@persistent_lru_cache(maxsize=128, path="~/.alc_fib_cache.json")
def fib(n: int) -> int:
    if n < 2:
        return n
    return fib(n - 1) + fib(n - 2)


def demo_decorator():
    t0 = time.time()
    value = fib(30)
    dt = (time.time() - t0) * 1000
    print(f"fib(30) = {value}  [{dt:.2f} ms]")
    print("fib stats:", fib.cache_stats())


if __name__ == "__main__":
    demo_direct_cache()
    demo_decorator()
