import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import {
  runCfBlockProbe,
  _readCfBlockProbeStateForTests,
  _CF_BLOCK_PROBE_STATE_KEY,
  type CfBlockProbeEnv,
} from "../src/cf-block-probe";

class FakeKv {
  private store = new Map<string, string>();
  async get(key: string): Promise<string | null> {
    return this.store.has(key) ? this.store.get(key)! : null;
  }
  async put(key: string, value: string, _opts?: unknown): Promise<void> {
    this.store.set(key, value);
  }
  async delete(key: string): Promise<void> {
    this.store.delete(key);
  }
  async list(): Promise<{ keys: { name: string }[]; list_complete: boolean }> {
    return { keys: [...this.store.keys()].map((name) => ({ name })), list_complete: true };
  }
}

function baseEnv(over: Partial<CfBlockProbeEnv> = {}): CfBlockProbeEnv & { RATE_LIMIT: FakeKv } {
  return {
    RATE_LIMIT: new FakeKv() as unknown as KVNamespace,
    CF_BLOCK_PROBE_TARGET_URL: "https://syrabit.ai/",
    SYNTHETIC_PROBE_WATCHDOG_WEBHOOK_URL: "https://hooks.example.com/watchdog",
    ...over,
  } as CfBlockProbeEnv & { RATE_LIMIT: FakeKv };
}

describe("cf-block-probe", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("passes when the homepage returns 200 with normal HTML", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response("<!doctype html><html><body>Syrabit</body></html>", {
        status: 200,
        headers: { "content-type": "text/html", "cf-ray": "9aaa1111bbbb2222-FRA" },
      }),
    );
    const env = baseEnv();
    const res = await runCfBlockProbe(env);
    expect(res.ok).toBe(true);
    expect(res.blocked).toBe(false);
    expect(res.status).toBe(200);
    expect(res.consecutive_failures).toBe(0);
  });

  it("detects a CF block via the cf-mitigated response header", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response("denied", {
        status: 403,
        headers: { "cf-mitigated": "block", "cf-ray": "9f14bccc891a6ebf-BOM" },
      }),
    );
    const env = baseEnv();
    const res = await runCfBlockProbe(env);
    expect(res.ok).toBe(false);
    expect(res.blocked).toBe(true);
    expect(res.signal).toContain("cf-mitigated");
    expect(res.ray_id).toBe("9f14bccc891a6ebf");
    expect(res.consecutive_failures).toBe(1);
  });

  it("detects a CF block via the 'Sorry, you have been blocked' body marker", async () => {
    const body =
      "<html><head><title>Attention Required! | Cloudflare</title></head>" +
      "<body><h1>Sorry, you have been blocked</h1>" +
      "<p>You are unable to access syrabit.ai</p>" +
      "<div>Cloudflare Ray ID: 9f14bccc891a6ebf</div></body></html>";
    fetchMock.mockResolvedValueOnce(
      new Response(body, {
        status: 403,
        headers: { "content-type": "text/html", "cf-ray": "9f14bccc891a6ebf-FRA" },
      }),
    );
    const env = baseEnv();
    const res = await runCfBlockProbe(env);
    expect(res.ok).toBe(false);
    expect(res.blocked).toBe(true);
    // Match is case-insensitive — the lower-cased marker is what we recorded.
    expect(res.signal).toContain("body:");
    expect(res.ray_id).toBe("9f14bccc891a6ebf");
  });

  it("flags a non-2xx that is NOT a CF block with a distinct non-cf signal", async () => {
    fetchMock.mockResolvedValueOnce(new Response("upstream-died", { status: 502 }));
    const env = baseEnv();
    const res = await runCfBlockProbe(env);
    expect(res.ok).toBe(false);
    expect(res.blocked).toBe(true);
    expect(res.signal).toBe("non-cf:non-2xx-status:502");
  });

  it("does NOT match body markers on a 200 response (avoids false positives)", async () => {
    // A help-doc-style homepage that legitimately mentions Cloudflare.
    // Status is 200, no cf-mitigated header — must pass.
    const body =
      "<html><body>FAQ: If you ever see 'Sorry, you have been blocked', " +
      "note your Cloudflare Ray ID and email support@syrabit.ai.</body></html>";
    fetchMock.mockResolvedValueOnce(
      new Response(body, {
        status: 200,
        headers: { "content-type": "text/html", "cf-ray": "9aaaa1111bbbb22-AMS" },
      }),
    );
    const env = baseEnv();
    const res = await runCfBlockProbe(env);
    expect(res.ok).toBe(true);
    expect(res.blocked).toBe(false);
    expect(res.signal).toBeUndefined();
    expect(res.consecutive_failures).toBe(0);
  });

  it("uses alert_type=public_homepage_probe_failed for non-CF outages", async () => {
    const env = baseEnv();
    fetchMock.mockResolvedValueOnce(new Response("up-down", { status: 502 }));
    await runCfBlockProbe(env, new Date(Date.UTC(2026, 3, 24, 12, 0)));
    fetchMock.mockResolvedValueOnce(new Response("up-down", { status: 502 }));
    fetchMock.mockResolvedValueOnce(new Response("ok", { status: 200 })); // watchdog
    const res = await runCfBlockProbe(env, new Date(Date.UTC(2026, 3, 24, 12, 1)));
    expect(res.watchdog_fired).toBe(true);
    const watchdogCall = fetchMock.mock.calls[fetchMock.mock.calls.length - 1];
    const body = JSON.parse((watchdogCall[1] as RequestInit).body as string);
    expect(body.alert_type).toBe("public_homepage_probe_failed");
    expect(body.cf_block_signal).toBe(false);
    expect(body.last_signal).toBe("non-cf:non-2xx-status:502");
    // Wording must NOT claim users are seeing a CF block.
    expect(body.text).toContain("non-CF signal");
    expect(body.text).not.toContain("Sorry, you have been blocked");
  });

  it("does NOT fire the watchdog before the threshold, and DOES fire on the threshold", async () => {
    const env = baseEnv(); // default threshold = 2
    fetchMock.mockResolvedValueOnce(
      new Response("blocked", { status: 403, headers: { "cf-mitigated": "block" } }),
    );
    const r1 = await runCfBlockProbe(env, new Date(Date.UTC(2026, 3, 24, 12, 0)));
    expect(r1.consecutive_failures).toBe(1);
    expect(r1.watchdog_fired).toBe(false);

    fetchMock.mockResolvedValueOnce(
      new Response("blocked", { status: 403, headers: { "cf-mitigated": "block" } }),
    );
    fetchMock.mockResolvedValueOnce(new Response("ok", { status: 200 })); // watchdog webhook
    const r2 = await runCfBlockProbe(env, new Date(Date.UTC(2026, 3, 24, 12, 1)));
    expect(r2.consecutive_failures).toBe(2);
    expect(r2.watchdog_fired).toBe(true);
    const watchdogCall = fetchMock.mock.calls[fetchMock.mock.calls.length - 1];
    expect(watchdogCall[0]).toBe("https://hooks.example.com/watchdog");
    const body = JSON.parse((watchdogCall[1] as RequestInit).body as string);
    expect(body.alert_type).toBe("cf_public_block_detected");
    expect(body.cf_block_signal).toBe(true);
    expect(body.consecutive_failures).toBe(2);
    expect(body.target_url).toBe("https://syrabit.ai/");
    expect(body.endpoint_path).toBe("/");
    expect(body.probe_leg).toBe("homepage");
  });

  it("respects the watchdog cooldown and only re-pages after `threshold` minutes", async () => {
    const env = baseEnv({ CF_BLOCK_PROBE_THRESHOLD: "2" });
    // Fail twice → fires watchdog at minute 1.
    fetchMock.mockResolvedValueOnce(
      new Response("x", { status: 403, headers: { "cf-mitigated": "block" } }),
    );
    await runCfBlockProbe(env, new Date(Date.UTC(2026, 3, 24, 12, 0)));
    fetchMock.mockResolvedValueOnce(
      new Response("x", { status: 403, headers: { "cf-mitigated": "block" } }),
    );
    fetchMock.mockResolvedValueOnce(new Response("ok", { status: 200 })); // watchdog
    const fired = await runCfBlockProbe(env, new Date(Date.UTC(2026, 3, 24, 12, 1)));
    expect(fired.watchdog_fired).toBe(true);

    // Minute 2: still failing, still inside cooldown — must NOT re-fire.
    fetchMock.mockResolvedValueOnce(
      new Response("x", { status: 403, headers: { "cf-mitigated": "block" } }),
    );
    const stillCooling = await runCfBlockProbe(env, new Date(Date.UTC(2026, 3, 24, 12, 2)));
    expect(stillCooling.consecutive_failures).toBe(3);
    expect(stillCooling.watchdog_fired).toBe(false);

    // Minute 3: ≥ threshold (2 min) since last fire — should re-fire.
    fetchMock.mockResolvedValueOnce(
      new Response("x", { status: 403, headers: { "cf-mitigated": "block" } }),
    );
    fetchMock.mockResolvedValueOnce(new Response("ok", { status: 200 })); // watchdog repost
    const reFired = await runCfBlockProbe(env, new Date(Date.UTC(2026, 3, 24, 12, 3)));
    expect(reFired.consecutive_failures).toBe(4);
    expect(reFired.watchdog_fired).toBe(true);
  });

  it("resets consecutive_failures and clears last_signal on a 200", async () => {
    const env = baseEnv();
    await env.RATE_LIMIT.put(
      _CF_BLOCK_PROBE_STATE_KEY,
      JSON.stringify({
        consecutive_failures: 5,
        last_signal: "cf-mitigated:block",
        last_status: 403,
        last_ray_id: "9f14bccc891a6ebf",
      }),
    );
    fetchMock.mockResolvedValueOnce(new Response("<html>ok</html>", { status: 200 }));
    const res = await runCfBlockProbe(env, new Date("2026-04-24T12:30:00Z"));
    expect(res.ok).toBe(true);
    expect(res.consecutive_failures).toBe(0);
    const state = await _readCfBlockProbeStateForTests(env.RATE_LIMIT as unknown as KVNamespace);
    expect(state.last_success_at).toBe("2026-04-24T12:30:00.000Z");
    expect(state.last_signal).toBeNull();
  });

  it("treats a network error as a block and increments the counter", async () => {
    fetchMock.mockRejectedValueOnce(new Error("ECONNRESET"));
    const env = baseEnv();
    const res = await runCfBlockProbe(env);
    expect(res.ok).toBe(false);
    expect(res.blocked).toBe(true);
    expect(res.signal).toBe("non-cf:fetch-error");
    expect(res.consecutive_failures).toBe(1);
  });

  it("skips when CF_BLOCK_PROBE_DISABLED=true", async () => {
    const env = baseEnv({ CF_BLOCK_PROBE_DISABLED: "true" });
    const res = await runCfBlockProbe(env);
    expect(res.skipped).toBe(true);
    expect(res.reason).toBe("disabled_by_var");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("skips with no_kv_binding when RATE_LIMIT is absent", async () => {
    const env = baseEnv();
    delete (env as Partial<CfBlockProbeEnv>).RATE_LIMIT;
    const res = await runCfBlockProbe(env);
    expect(res.skipped).toBe(true);
    expect(res.reason).toBe("no_kv_binding");
  });

  it("logs but does not crash when watchdog webhook is unset", async () => {
    const env = baseEnv({ SYNTHETIC_PROBE_WATCHDOG_WEBHOOK_URL: "" });
    fetchMock.mockResolvedValueOnce(
      new Response("x", { status: 403, headers: { "cf-mitigated": "block" } }),
    );
    await runCfBlockProbe(env, new Date(Date.UTC(2026, 3, 24, 12, 0)));
    fetchMock.mockResolvedValueOnce(
      new Response("x", { status: 403, headers: { "cf-mitigated": "block" } }),
    );
    const res = await runCfBlockProbe(env, new Date(Date.UTC(2026, 3, 24, 12, 1)));
    // Threshold reached, but no webhook posted (only 2 fetch calls in total).
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(res.consecutive_failures).toBe(2);
    expect(res.watchdog_fired).toBe(false);
  });

  it("honours CF_BLOCK_PROBE_TARGET_URL override", async () => {
    fetchMock.mockResolvedValueOnce(new Response("<html>ok</html>", { status: 200 }));
    const env = baseEnv({ CF_BLOCK_PROBE_TARGET_URL: "https://canary.syrabit.ai/" });
    await runCfBlockProbe(env);
    expect(fetchMock.mock.calls[0][0]).toBe("https://canary.syrabit.ai/");
  });

  it("strips the cf-ray POP suffix when persisting last_ray_id", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response("<html>ok</html>", {
        status: 200,
        headers: { "cf-ray": "9aaaa1111bbbb22-AMS" },
      }),
    );
    const env = baseEnv();
    const res = await runCfBlockProbe(env);
    expect(res.ray_id).toBe("9aaaa1111bbbb22");
  });
});
