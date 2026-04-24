"""
Smoke-test the Vertex AI <-> Cloudflare AI Gateway path used by
syrabit-backend in production.

What it does, in order:
  1. Loads VERTEX_SERVICE_ACCOUNT or GOOGLE_APPLICATION_CREDENTIALS_JSON
     and mints a short-lived OAuth bearer token for the
     `cloud-platform` scope (same as vertex_services._auth_headers).
  2. Sends a tiny `generateContent` call DIRECTLY to
     `{LOCATION}-aiplatform.googleapis.com`           (baseline)
  3. Sends the SAME call through the Cloudflare AI Gateway at
     `gateway.ai.cloudflare.com/v1/{ACCT}/{GW}/google-vertex-ai/...`
     with `cf-aig-authorization: Bearer <CF_AI_GATEWAY_TOKEN>`.
  4. Prints, per call: HTTP status, total wall-clock latency, the
     model's text reply, and any `cf-*` response headers (cf-ray,
     cf-cache-status, cf-aig-cache-status, cf-aig-eventid).

Exit codes:
  0  = both calls returned 200 with a non-empty model reply
  1  = direct call failed (Vertex/SA problem; gateway test skipped)
  2  = gateway call failed (gateway/auth/binding problem)
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
import urllib.error

PROMPT = "Reply with the single word: pong"
MODEL  = os.environ.get("VERTEX_GEMINI_MODEL", "gemini-2.5-flash").strip() \
         or "gemini-2.5-flash"
TIMEOUT = 30


def _load_sa_info() -> dict:
    raw = (os.environ.get("VERTEX_SERVICE_ACCOUNT")
           or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
           or "").strip()
    if not raw:
        sys.exit("ERROR: neither VERTEX_SERVICE_ACCOUNT nor "
                 "GOOGLE_APPLICATION_CREDENTIALS_JSON is set")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        sys.exit(f"ERROR: SA env var is not valid JSON ({e})")


def _mint_token(sa_info: dict) -> str:
    from google.oauth2 import service_account
    from google.auth.transport.requests import Request
    creds = service_account.Credentials.from_service_account_info(
        sa_info, scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    creds.refresh(Request())
    return creds.token


def _post(url: str, headers: dict, body: dict) -> tuple[int, dict, dict, float]:
    # gateway.ai.cloudflare.com's edge WAF rejects requests with the
    # default `Python-urllib/*` User-Agent (HTTP 403 + body
    # `error code: 1010` — Cloudflare bot-integrity / banned-browser
    # signature). Always send a real UA so we hit the gateway service
    # itself rather than its perimeter WAF.
    headers = dict(headers)
    headers.setdefault("User-Agent",
                       "syrabit-vertex-aig-test/1.0 (+https://syrabit.ai)")
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            resp_headers = {k.lower(): v for k, v in resp.headers.items()}
            payload = json.loads(resp.read().decode("utf-8") or "{}")
            return resp.status, resp_headers, payload, elapsed_ms
    except urllib.error.HTTPError as e:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        resp_headers = {k.lower(): v for k, v in e.headers.items()}
        try:
            payload = json.loads(e.read().decode("utf-8") or "{}")
        except Exception:
            payload = {}
        return e.code, resp_headers, payload, elapsed_ms


def _extract_text(payload: dict) -> str:
    try:
        cands = payload.get("candidates") or []
        if not cands:
            return ""
        parts = cands[0].get("content", {}).get("parts") or []
        return "".join(p.get("text", "") for p in parts).strip()
    except Exception:
        return ""


def _print_call(label: str, url: str, status: int, headers: dict,
                payload: dict, elapsed_ms: float) -> None:
    print(f"\n=== {label} ===")
    print(f"  URL    : {url}")
    print(f"  STATUS : {status}   ({elapsed_ms:7.1f} ms)")
    cf_keys = sorted(k for k in headers if k.startswith("cf-"))
    for k in cf_keys:
        print(f"  {k}: {headers[k]}")
    text = _extract_text(payload)
    if text:
        print(f"  REPLY  : {text!r}")
    elif payload.get("error"):
        print(f"  ERROR  : {json.dumps(payload['error'])[:400]}")
    else:
        print(f"  PAYLOAD: {json.dumps(payload)[:400]}")


def main() -> int:
    sa_info = _load_sa_info()
    project = (os.environ.get("VERTEX_PROJECT_ID") or
               sa_info.get("project_id") or "").strip()
    location = (os.environ.get("VERTEX_LOCATION") or "us-central1").strip()
    if not project:
        sys.exit("ERROR: VERTEX_PROJECT_ID not set and no project_id in SA")

    print(f"Project : {project}")
    print(f"Location: {location}")
    print(f"Model   : {MODEL}")

    token = _mint_token(sa_info)
    body = {
        "contents": [{"role": "user", "parts": [{"text": PROMPT}]}],
        "generationConfig": {"maxOutputTokens": 16, "temperature": 0.0},
    }

    direct_path = (f"v1/projects/{project}/locations/{location}"
                   f"/publishers/google/models/{MODEL}:generateContent")
    direct_url = f"https://{location}-aiplatform.googleapis.com/{direct_path}"
    direct_headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    d_status, d_h, d_body, d_ms = _post(direct_url, direct_headers, body)
    _print_call("DIRECT Vertex (baseline)", direct_url, d_status, d_h, d_body, d_ms)

    acct = (os.environ.get("CF_AI_GATEWAY_ACCOUNT_ID") or "").strip()
    gw   = (os.environ.get("CF_AI_GATEWAY_ID") or "").strip()
    tok  = (os.environ.get("CF_AI_GATEWAY_TOKEN") or "").strip()
    if not (acct and gw):
        print("\nFAIL: CF_AI_GATEWAY_ACCOUNT_ID / CF_AI_GATEWAY_ID not set; "
              "cannot test gateway path.")
        return 2

    gw_url = (f"https://gateway.ai.cloudflare.com/v1/{acct}/{gw}"
              f"/google-vertex-ai/{direct_path}")
    gw_headers = dict(direct_headers)
    if tok:
        gw_headers["cf-aig-authorization"] = f"Bearer {tok}"
    gw_headers["cf-aig-cache-ttl"] = "0"

    g_status, g_h, g_body, g_ms = _post(gw_url, gw_headers, body)
    _print_call("CF AI Gateway -> Vertex", gw_url, g_status, g_h, g_body, g_ms)

    print("\n--- summary ---")
    print(f"  direct  : {d_status}  {d_ms:7.1f} ms  reply={_extract_text(d_body)!r}")
    print(f"  gateway : {g_status}  {g_ms:7.1f} ms  reply={_extract_text(g_body)!r}")
    print(f"  overhead: {g_ms - d_ms:+7.1f} ms")

    if g_status != 200 or not _extract_text(g_body):
        print("\nFAIL: gateway call did not return a usable reply.")
        return 2
    print("\nPASS: Vertex AI is reachable through the Cloudflare AI Gateway.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
