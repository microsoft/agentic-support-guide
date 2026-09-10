"""Measure how the deployed stack behaves under concurrent learner load.

A workshop cohort all press the button at once. This answers whether the
App Service plan, the knowledge base and the model deployment survive that,
and where the first bottleneck is.

Each request is a full orchestration: retrieval plus three agent calls. It
costs tokens, so the default is deliberately small.

    python scripts/load_test.py                 # 5, then 15
    python scripts/load_test.py --waves 30      # a full cohort
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from subprocess import run

REPO_ROOT = Path(__file__).resolve().parents[1]
DISTRICTS = ("DIST-A", "DIST-B", "DIST-DEMO")


def terraform_output(name: str) -> str:
    result = run(
        ["terraform", f"-chdir={REPO_ROOT / 'infra'}", "output", "-raw", name],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def acquire_key() -> str:
    """The key the web tier would attach. Without it every request is a 401."""

    return terraform_output("api_shared_key")


def one_request(api: str, index: int, timeout: int, key: str) -> dict:
    payload = {
        "district_id": DISTRICTS[index % len(DISTRICTS)],
        "learner_id": "LRN-0001",
        "category": "early-literacy",
        "concern_text": "Letter-sound fluency below expected pace.",
    }
    headers = {"Content-Type": "application/json"}
    if key:
        headers["x-api-key"] = key
    req = urllib.request.Request(
        f"{api}/api/recommendations/support-plan",
        data=json.dumps(payload).encode(),
        headers=headers,
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            body = json.loads(resp.read())
        elapsed = time.monotonic() - started
        return {
            "ok": body.get("status") == "ok",
            "status": body.get("status"),
            "error": body.get("error_code"),
            "seconds": elapsed,
        }
    except urllib.error.HTTPError as exc:
        return {
            "ok": False,
            "status": f"http_{exc.code}",
            "error": exc.reason,
            "seconds": time.monotonic() - started,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "status": type(exc).__name__,
            "error": str(exc)[:80],
            "seconds": time.monotonic() - started,
        }


def wave(api: str, size: int, timeout: int, key: str) -> list[dict]:
    with ThreadPoolExecutor(max_workers=size) as pool:
        return list(pool.map(lambda i: one_request(api, i, timeout, key), range(size)))


def report(size: int, results: list[dict], wall: float) -> bool:
    ok = [r for r in results if r["ok"]]
    bad = [r for r in results if not r["ok"]]
    times = sorted(r["seconds"] for r in results)
    p50 = statistics.median(times)
    p95 = times[min(len(times) - 1, int(len(times) * 0.95))]

    print(f"\n--- {size} concurrent ---")
    print(f"  succeeded : {len(ok)}/{size}")
    print(f"  wall clock: {wall:.1f}s")
    print(f"  p50 / p95 : {p50:.1f}s / {p95:.1f}s   slowest {times[-1]:.1f}s")
    if bad:
        reasons: dict[str, int] = {}
        for r in bad:
            key = f"{r['status']}:{r['error']}"
            reasons[key] = reasons.get(key, 0) + 1
        print("  failures  :")
        for reason, count in sorted(reasons.items(), key=lambda kv: -kv[1]):
            print(f"      {count:>3} x {reason}")
    return not bad


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="")
    parser.add_argument(
        "--waves",
        type=int,
        nargs="*",
        default=[5, 15],
        help="Concurrency levels to run, in order.",
    )
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()

    api = (args.api_url or terraform_output("api_url")).rstrip("/")
    parsed = urllib.parse.urlparse(api)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        print(f"expected an http(s) API URL, got {api!r}", file=sys.stderr)
        return 2

    print(f"API {api}")
    print(f"waves: {args.waves}   (each request is a full 4-step orchestration)")

    key = acquire_key()
    print(f"auth: {'shared key loaded' if key else 'none (expect 401s)'}")

    all_clean = True
    for size in args.waves:
        started = time.monotonic()
        results = wave(api, size, args.timeout, key)
        all_clean &= report(size, results, time.monotonic() - started)

    print()
    if all_clean:
        print("No failures at any tested concurrency.")
        return 0
    print("Failures observed. See the breakdown above.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
