"""Smoke test for a running Ledgerline instance (local container or the deployed service).

    make smoke BASE_URL=https://<service>.onrender.com ACCESS_CODE=<code>

Checks, in order: health, demo reset, S01 approves, S06 holds for treasury, the S04 scan holds
for a PO confirmation. Prints the timings and exits non-zero on the first failure. A sleeping
free instance can take a minute to wake, so the health check waits for it.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from typing import Any

import httpx

ACTIVE = ("queued", "running")


class SmokeError(RuntimeError):
    pass


class Smoke:
    def __init__(self, base_url: str, access_code: str | None, timeout: float) -> None:
        headers = {"X-Access-Code": access_code} if access_code else {}
        self.http = httpx.Client(base_url=base_url.rstrip("/"), headers=headers, timeout=timeout)
        self.timings: list[tuple[str, float]] = []

    def step(self, name: str, fn: Callable[[], str]) -> None:
        start = time.perf_counter()
        try:
            detail = fn()
        except (SmokeError, httpx.HTTPError) as exc:
            print(f"FAIL  {name}: {exc}")
            raise SystemExit(1) from exc
        took = time.perf_counter() - start
        self.timings.append((name, took))
        print(f"ok    {name} ({took:.1f} s) - {detail}")

    def request(self, method: str, path: str, **kw: Any) -> Any:
        resp = self.http.request(method, f"/api{path}", **kw)
        if resp.status_code >= 400:
            try:
                body = resp.json()
                why = f"{body.get('code')}: {body.get('detail')}"
            except ValueError:
                why = resp.text[:200]
            raise SmokeError(f"{method} {path} -> {resp.status_code} ({why})")
        return resp.json()

    # --- steps -----------------------------------------------------------------------------

    def health(self, wait_s: float) -> str:
        deadline = time.monotonic() + wait_s
        while True:
            try:
                h = self.request("GET", "/health")
                break
            except (SmokeError, httpx.TransportError):
                if time.monotonic() > deadline:
                    raise
                time.sleep(3)
        if h.get("status") != "ok" or h.get("db") != "ok":
            raise SmokeError(f"unhealthy: {h}")
        return (
            f"{h['app_env']} | {h['llm_provider']} {h['llm_model']} | "
            f"OCR {'on' if h['ocr_available'] else 'off'} | today {h['today']}"
        )

    def reset(self, wait_s: float) -> str:
        deadline = time.monotonic() + wait_s
        while True:
            try:
                start = time.perf_counter()
                body = self.request("POST", "/demo/reset", timeout=wait_s)
                took = time.perf_counter() - start
                how = {"snapshot": "restored the seeded snapshot", "reseed": "reseeded"}.get(
                    body.get("mode", ""), "reset"
                )
                server = (
                    f", {body['duration_ms'] / 1000:.1f} s on the server"
                    if "duration_ms" in body
                    else ""
                )
                return f"{body['runs']} seeded runs; {how} in {took:.1f} s{server}"
            except SmokeError as exc:
                busy = "reset_timeout" in str(exc) or "reset_in_progress" in str(exc)
                if not busy or time.monotonic() > deadline:
                    raise
                time.sleep(5)

    def run(self, doc_id: str, wait_s: float) -> dict[str, Any]:
        run_id = self.request("POST", f"/demo/runs/{doc_id}", json={})["run_id"]
        deadline = time.monotonic() + wait_s
        while True:
            run: dict[str, Any] = self.request("GET", f"/runs/{run_id}")
            if run["status"] not in ACTIVE:
                return run
            if time.monotonic() > deadline:
                raise SmokeError(f"{doc_id} still {run['status']} after {wait_s:.0f} s")
            time.sleep(1)

    def expect(self, doc_id: str, outcome: str, route: str, wait_s: float) -> str:
        run = self.run(doc_id, wait_s)
        if run["status"] == "failed":
            failed = next((s for s in run["stages"] if s["status"] == "error"), None)
            raise SmokeError(f"{doc_id} failed: {failed['summary'] if failed else 'unknown'}")
        got = (run["outcome"], run["route"])
        if got != (outcome, route):
            raise SmokeError(f"{doc_id}: expected {outcome}/{route}, got {got[0]}/{got[1]}")
        if outcome == "APPROVE" and not (run["decision"] or {}).get("posting"):
            raise SmokeError(f"{doc_id}: approved without a posting payload")
        cached = "cached reading" if run.get("cached_extraction") else "fresh reading"
        return f"{run['display_id']} {outcome}/{route}, {run.get('duration_ms')} ms, {cached}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke-test a running Ledgerline instance.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--access-code", default=None)
    parser.add_argument("--timeout", type=float, default=30, help="per request, seconds")
    parser.add_argument("--wake", type=float, default=120, help="wait for health, seconds")
    parser.add_argument("--run-wait", type=float, default=180, help="wait per run, seconds")
    args = parser.parse_args(argv)

    smoke = Smoke(args.base_url, args.access_code or None, args.timeout)
    print(f"Smoke test against {args.base_url}")
    smoke.step("health", lambda: smoke.health(args.wake))
    smoke.step("demo reset", lambda: smoke.reset(300))
    smoke.step("S01 approves", lambda: smoke.expect("S01", "APPROVE", "none", args.run_wait))
    smoke.step(
        "S06 holds for treasury", lambda: smoke.expect("S06", "HOLD", "treasury", args.run_wait)
    )
    smoke.step(
        "S04 scan holds for PO confirmation",
        lambda: smoke.expect("S04", "HOLD", "ap_clerk", args.run_wait),
    )
    total = sum(t for _, t in smoke.timings)
    print("timings: " + " | ".join(f"{n} {t:.1f} s" for n, t in smoke.timings))
    print(f"PASS in {total:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
