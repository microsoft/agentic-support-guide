"""Step-by-step verification of the deployed workshop stack.

Walks the path a learner actually takes (open the UI, build a plan) and then
checks the properties the key-based design depends on. Every check prints what
it observed, so a pass is legible rather than a green tick.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def tf(name: str) -> str:
    out = subprocess.run(
        ["terraform", f"-chdir={REPO / 'infra'}", "output", "-raw", name],
        capture_output=True,
        text=True,
        check=False,
    )
    return out.stdout.strip() if out.returncode == 0 else ""


API = tf("api_url").rstrip("/")
WEB = tf("web_url").rstrip("/")
KEY = tf("api_shared_key")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_a: object, **_k: object) -> None:
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def call(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: dict | None = None,
    timeout: int = 240,
) -> tuple[int, bytes, dict[str, str]]:
    data = json.dumps(body).encode() if body is not None else None
    hdrs = dict(headers or {})
    if data:
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with OPENER.open(req, timeout=timeout) as resp:
            return resp.status, resp.read(), {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), {k.lower(): v for k, v in exc.headers.items()}
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc).encode(), {}


RESULTS: list[tuple[bool, str, str]] = []


def step(name: str, ok: bool, detail: str) -> None:
    RESULTS.append((ok, name, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    print(f"        {detail}")


print(f"API {API}")
print(f"UI  {WEB}")
print(f"key {'loaded from terraform' if KEY else 'MISSING'}\n")

# --- the API is closed unless you have the key -------------------------
status, body, _ = call(f"{API}/api/health")
health = json.loads(body) if status == 200 else {}
step(
    "API health is anonymous (deploy polls it)",
    status == 200 and health.get("status") == "ok",
    f"{status} build_id={health.get('build_id')} "
    f"foundry_auth_mode={health.get('foundry_auth_mode')}",
)

closed = {}
for path in ("/api/health/details", "/api/supports/plans", "/api/learners", "/api/audit/events"):
    code, _, _ = call(f"{API}{path}")
    closed[path] = code
step(
    "direct API calls without the key are refused",
    all(c == 401 for c in closed.values()),
    ", ".join(f"{p}={c}" for p, c in closed.items()),
)

code, _, _ = call(f"{API}/api/supports/plans", headers={"x-api-key": "wrong-key"})
step("a wrong key is refused", code == 401, f"/api/supports/plans with bad key = {code}")

code, body, _ = call(f"{API}/api/supports/plans", headers={"x-api-key": KEY})
step("the correct key is accepted", code == 200, f"/api/supports/plans with key = {code}")

# --- the UI is reachable and has no credential -------------------------
code, body, _ = call(WEB)
html = body.decode("utf-8", "replace")
step("UI serves index.html", code == 200 and 'id="root"' in html, f"{code}, {len(body)} bytes")

code, body, _ = call(f"{WEB}/supports")
step(
    "deep link falls back to the SPA",
    code == 200 and b'id="root"' in body,
    f"GET /supports = {code}",
)

match = re.search(r"[\"'](/assets/[^\"']+\.js)[\"']", html)
asset = match.group(1) if match else ""
code, js, hdrs = call(f"{WEB}{asset}") if asset else (0, b"", {})
step(
    "static assets serve with a content type",
    code == 200 and "javascript" in hdrs.get("content-type", ""),
    f"{asset} = {code} {hdrs.get('content-type')} cache={hdrs.get('cache-control')}",
)

api_host = API.split("//", 1)[-1]
leaks = []
if KEY and KEY.encode() in js:
    leaks.append("the shared key")
if api_host.encode() in js:
    leaks.append(f"the API hostname {api_host}")
step(
    "the bundle carries no secret and no API hostname",
    not leaks,
    "clean" if not leaks else f"LEAKED: {', '.join(leaks)}",
)

# --- the proxy is the only way in --------------------------------------
code, body, _ = call(f"{WEB}/api/health/details")
details = json.loads(body) if code == 200 else {}
# Asserts the payload came from the API, not that the app is configured.
# `customer_demo_ready` is a configuration signal and stays true when the
# knowledge base is missing, so using it here passed while every
# recommendation was failing.
step(
    "browser path reaches the API through the proxy",
    code == 200 and details.get("service") == "agentic-support-guide-api",
    f"{code} service={details.get('service')} evidence={details.get('evidence_source')} "
    f"verified={details.get('evidence_verified')}",
)

code, body, _ = call(f"{WEB}/api/supports/options")
options = json.loads(body) if code == 200 else {}
districts = options.get("districts", [])
step(
    "district roster comes from the API, not the bundle",
    code == 200 and len(districts) > 0,
    f"districts={districts}",
)

# A client supplying its own key must not be able to choose the credential.
code, _, _ = call(f"{WEB}/api/supports/options", headers={"x-api-key": "attacker-supplied"})
step(
    "proxy overrides a client-supplied key",
    code == 200,
    f"forged x-api-key still served correctly = {code}",
)

traversal: dict[str, str] = {}
leaked_file = False
for probe in (
    "/../../etc/passwd",
    "/%2e%2e%2f%2e%2e%2fetc%2fpasswd",
    "/assets/..%2f..%2fserver.js",
    "/server.js",
    "/package.json",
):
    code, body, hdrs = call(f"{WEB}{probe}")
    ctype = hdrs.get("content-type", "")
    traversal[probe] = f"{code} {ctype.split(';')[0]}"
    # Anything outside dist/ must come back as the SPA fallback. Serving it as
    # javascript or json would mean the file itself was read off disk.
    if code == 200 and "text/html" not in ctype:
        leaked_file = True
    if b"root:" in body or b"API_SHARED_KEY" in body or b"httpRequest" in body:
        leaked_file = True
step(
    "no path escapes the static root or serves server source",
    not leaked_file,
    ", ".join(f"{p}={c}" for p, c in traversal.items()),
)

# --- the actual product path -------------------------------------------
payload = {
    "district_id": districts[0] if districts else "DIST-A",
    "learner_id": "LRN-0001",
    "category": "early-literacy",
    "concern_text": "Letter-sound fluency below expected pace.",
}
code, body, _ = call(f"{WEB}/api/recommendations/support-plan", method="POST", body=payload)
env = json.loads(body) if code == 200 else {}
trace = env.get("agent_trace") or []
step(
    "full recommendation runs through the proxy",
    code == 200 and env.get("status") == "ok",
    f"{code} status={env.get('status')} {env.get('error_code') or ''} steps={len(trace)}",
)
for s in trace:
    print(
        f"           {s.get('agent'):<30} {s.get('status'):<9} "
        f"provider={s.get('provider')} {s.get('latency_ms')}ms"
    )

rec = env.get("recommendation") or {}
cites = rec.get("citations") or []
step("recommendation carries citations", bool(cites), f"{len(cites)} citation(s)")

stray = [c for c in cites if c.get("district_id") != payload["district_id"]]
step(
    "no evidence from another district",
    not stray,
    f"all citations scoped to {payload['district_id']}" if not stray else f"leaked: {stray}",
)

code, body, _ = call(f"{WEB}/api/audit/events")
events = json.loads(body).get("events", []) if code == 200 else []
step("the call reached the audit trail", code == 200 and len(events) > 0, f"{len(events)} events")

print()
failed = [name for ok, name, _ in RESULTS if not ok]
if failed:
    print(f"{len(failed)} FAILED:")
    for name in failed:
        print(f"  - {name}")
    sys.exit(1)
print(f"ALL {len(RESULTS)} CHECKS PASSED")
