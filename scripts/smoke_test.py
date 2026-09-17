"""End-to-end smoke test against the deployed app.

Modules 1 and 9 both use this. It deliberately tests things a health check
cannot: that the UI bundle points at the right API host, that CORS permits
that origin, that a real agent call returns citations, and which evidence
provider actually served them.

    python scripts/smoke_test.py
    python scripts/smoke_test.py --expect-evidence foundry_iq

URLs come from Terraform outputs unless --api-url/--web-url are given.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INFRA_DIR = REPO_ROOT / "infra"


def terraform_output(name: str) -> str:
    try:
        result = subprocess.run(
            ["terraform", f"-chdir={INFRA_DIR}", "output", "-raw", name],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


# Populated from the terraform output. Scripts talk to the API directly, so
# they need the key the web tier would otherwise attach for them.
AUTH_HEADERS: dict[str, str] = {}


def _require_http_url(url: str) -> str:
    """Reject anything that is not a plain http(s) URL.

    The URLs normally come from Terraform outputs, but they are also CLI
    arguments, and this script is run inside CI where a file:// or
    link-local address would be a genuine problem.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"expected an http(s) URL, got {url!r}")
    return url.rstrip("/")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Keeps a 302-to-login from being read as a successful API response."""

    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


_NO_REDIRECT = urllib.request.build_opener(_NoRedirect)


def get(url: str, timeout: int = 120) -> tuple[int, bytes]:
    headers = {"Accept": "*/*", **AUTH_HEADERS}
    req = urllib.request.Request(_require_http_url(url), headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return resp.status, resp.read()


def post(url: str, payload: dict, timeout: int = 240) -> tuple[int, dict]:
    req = urllib.request.Request(
        _require_http_url(url),
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **AUTH_HEADERS},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return resp.status, json.loads(resp.read())


class Smoke:
    def __init__(self, api: str, web: str, expect_evidence: str) -> None:
        self.api = api.rstrip("/")
        self.web = web.rstrip("/")
        self.expect_evidence = expect_evidence
        self.failures: list[str] = []
        self.state: dict = {}

    def check(self, name: str, fn) -> None:
        try:
            fn()
            print(f"  PASS  {name}")
        except Exception as exc:  # noqa: BLE001
            detail = ""
            if isinstance(exc, urllib.error.HTTPError):
                detail = f" body={exc.read()[:400]!r}"
            print(f"  FAIL  {name}: {type(exc).__name__}: {exc}{detail}")
            self.failures.append(name)

    # --- checks ---------------------------------------------------------

    def health(self) -> None:
        status, body = get(f"{self.api}/api/health")
        assert status == 200, status
        data = json.loads(body)
        self.state["health"] = data
        print(f"        build_id={data.get('build_id')} version={data.get('version')}")
        assert data.get("status") == "ok", data.get("status")

    def evidence_source(self) -> None:
        status, body = get(f"{self.api}/api/health/details")
        assert status == 200, status
        data = json.loads(body)
        source = data.get("evidence_source")
        kb = data.get("evidence_knowledge_base")
        ready = data.get("customer_demo_ready")
        verified = data.get("evidence_verified")
        print(
            f"        evidence_source={source} knowledge_base={kb} "
            f"demo_ready={ready} evidence_verified={verified}"
        )
        assert ready, "customer_demo_ready is false; the app is not configured"
        # `evidence_verified` is False for a remote source because the API
        # cannot prove a knowledge base holds anything without a network call.
        # The real proof is the live request below, which is why this script
        # exists rather than trusting a health flag.
        if self.expect_evidence:
            assert source == self.expect_evidence, (
                f"expected evidence_source={self.expect_evidence}, got {source}"
            )

    def auth_is_enforced(self) -> None:
        """The deploy is only secure if this fails for a caller without the key.

        Everything else in this script sends the key, so a completely
        unauthenticated API would sail through every other check.
        """

        for path in ("/api/supports/plans", "/api/dealerships", "/api/health/details"):
            # No redirect following: a 302 to a login page returns 200 for the
            # login HTML, which would read as a successful API response.
            req = urllib.request.Request(f"{self.api}{path}")
            try:
                with _NO_REDIRECT.open(req, timeout=30) as resp:
                    raise AssertionError(f"{path} answered {resp.status} without the key")
            except urllib.error.HTTPError as exc:
                assert exc.code == 401, f"{path} returned {exc.code}, expected 401"
        print("        direct calls without the key are refused on 3 paths")

    def ui_reaches_api_through_proxy(self) -> None:
        """The real access path: browser -> web tier -> API.

        The browser holds no credential, so this is what actually has to work.
        Testing only the direct API path would pass while the UI was broken.
        """

        req = urllib.request.Request(f"{self.web}/api/health/details")
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
        print(f"        proxied auth_mode={data.get('api_auth_mode')}")
        assert data.get("customer_demo_ready"), "proxied health says the app is not configured"

    def ui_serves(self) -> None:
        status, body = get(self.web)
        assert status == 200, status
        assert b'id="root"' in body, body[:200]

    def ui_spa_fallback(self) -> None:
        status, body = get(f"{self.web}/dashboard")
        assert status == 200, status
        assert b'id="root"' in body, "SPA fallback is not rewriting deep links"

    def bundle_carries_no_secret(self) -> None:
        """The whole design rests on the browser never receiving the key.

        If the key or the API hostname ends up inlined in the bundle, the
        proxy has been bypassed and the key is public.
        """

        _, body = get(self.web)
        text = body.decode("utf-8", "replace")
        match = re.search(r"[\"'](/assets/[^\"']+\.js)[\"']", text)
        assert match, "no JS bundle referenced in index.html"
        _, js = get(f"{self.web}{match.group(1)}")

        key = AUTH_HEADERS.get("x-api-key", "")
        assert not (key and key.encode() in js), "the shared key is inlined in the UI bundle"
        host = self.api.split("//", 1)[-1]
        assert host.encode() not in js, (
            f"bundle calls {host} directly, bypassing the proxy that holds the key"
        )
        print("        bundle contains neither the key nor the API hostname")

    def recommendation(self) -> None:
        status, data = post(
            f"{self.api}/api/recommendations/support-plan",
            {
                "dealer_group_id": "GROUP-A",
                "dealership_id": "DLR-0001",
                "category": "lead-response",
                "concern_text": "Median first response to online enquiries slipped past one hour.",
            },
        )
        assert status == 200, status
        self.state["rec"] = data
        assert data.get("status") == "ok", (
            f"{data.get('status')}: {data.get('error_code')} {data.get('error_message')}"
        )
        for step in data.get("agent_trace") or []:
            print(
                f"        {step.get('agent'):<30} {step.get('status'):<9} "
                f"provider={step.get('provider')} {step.get('latency_ms')}ms"
            )

    def citations(self) -> None:
        rec = (self.state.get("rec") or {}).get("recommendation") or {}
        cites = rec.get("citations") or []
        print(f"        citations: {len(cites)}")
        assert cites, "recommendation returned no citations"

    def trace_reports_expected_provider(self) -> None:
        if not self.expect_evidence:
            return
        trace = (self.state.get("rec") or {}).get("agent_trace") or []
        step = next((s for s in trace if s.get("agent") == "evidence-retrieval"), None)
        assert step is not None, "no evidence-retrieval step in the trace"
        assert step.get("provider") == self.expect_evidence, (
            f"trace says provider={step.get('provider')}, expected {self.expect_evidence}"
        )

    def dealer_group_isolation(self) -> None:
        rec = (self.state.get("rec") or {}).get("recommendation") or {}
        stray = [
            c
            for c in (rec.get("citations") or [])
            if c.get("dealer_group_id") not in (None, "", "GROUP-A")
        ]
        assert not stray, f"citations leaked from another dealer group: {stray}"

    def audit(self) -> None:
        status, body = get(f"{self.api}/api/audit/events")
        assert status == 200, status
        events = json.loads(body)
        items = events if isinstance(events, list) else events.get("events", [])
        print(f"        audit events: {len(items)}")
        assert items, "no audit events recorded"

    def run(self) -> int:
        print(f"API {self.api}")
        print(f"UI  {self.web}")
        if self.expect_evidence:
            print(f"expecting evidence_source={self.expect_evidence}")
        print()
        self.check("API health responds", self.health)
        self.check("API refuses calls without the key", self.auth_is_enforced)
        self.check("UI reaches the API through the proxy", self.ui_reaches_api_through_proxy)
        self.check("evidence source is as expected", self.evidence_source)
        self.check("UI serves index.html", self.ui_serves)
        self.check("UI deep link falls back to the SPA", self.ui_spa_fallback)
        self.check("UI bundle carries no secret", self.bundle_carries_no_secret)
        self.check("support-plan request succeeds", self.recommendation)
        self.check("recommendation carries citations", self.citations)
        self.check("trace names the real evidence provider", self.trace_reports_expected_provider)
        self.check("no cross-group citations", self.dealer_group_isolation)
        self.check("audit trail recorded the call", self.audit)

        print()
        if self.failures:
            print(f"{len(self.failures)} FAILED: {', '.join(self.failures)}")
            return 1
        print("ALL SMOKE CHECKS PASSED")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="")
    parser.add_argument("--web-url", default="")
    parser.add_argument(
        "--expect-evidence",
        default="",
        choices=["", "fixture", "foundry_iq"],
        help="Fail if the app is not serving evidence from this provider.",
    )
    parser.add_argument(
        "--api-key",
        default="",
        help="Shared key for the API. Defaults to the terraform output.",
    )
    args = parser.parse_args()

    api = args.api_url or terraform_output("api_url")
    web = args.web_url or terraform_output("web_url")
    if not api or not web:
        print(
            "Could not determine URLs. Pass --api-url and --web-url, or run "
            "from a repo with Terraform state.",
            file=sys.stderr,
        )
        return 2

    # This script calls the API directly, so it needs the key the web tier
    # would otherwise attach. CI has no Terraform state in the deploy job, so
    # the key also comes from the environment.
    key = (
        args.api_key
        or os.environ.get("API_SHARED_KEY", "").strip()
        or terraform_output("api_shared_key")
    )
    if key:
        AUTH_HEADERS["x-api-key"] = key
        print("calling the API with the shared key")
    else:
        print(
            "no API key available; direct API checks will fail with 401.",
            file=sys.stderr,
        )

    return Smoke(api, web, args.expect_evidence).run()


if __name__ == "__main__":
    raise SystemExit(main())
