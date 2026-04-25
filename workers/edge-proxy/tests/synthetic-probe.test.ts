import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import {
  runSyntheticProbe,
  _readSyntheticProbeStateForTests,
  _SYNTHETIC_PROBE_STATE_KEY,
  type SyntheticProbeEnv,
} from "../src/synthetic-probe";

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

function baseEnv(over: Partial<SyntheticProbeEnv> = {}): SyntheticProbeEnv & { RATE_LIMIT: FakeKv } {
  const kv = new FakeKv();
  return {
    RATE_LIMIT: kv as unknown as KVNamespace,
    BACKEND_URL: "https://backend.example.com",
    BACKEND_ORIGIN_SECRET: "origin-shared-secret",
    SYNTHETIC_PROBE_CF_ACCESS_CLIENT_ID: "client-id",
    SYNTHETIC_PROBE_CF_ACCESS_CLIENT_SECRET: "client-secret",
    SYNTHETIC_PROBE_ADMIN_JWT: "admin-jwt-token",
    SYNTHETIC_PROBE_WATCHDOG_WEBHOOK_URL: "https://hooks.example.com/watchdog",
    ...over,
  } as SyntheticProbeEnv & { RATE_LIMIT: FakeKv };
}

describe("synthetic probe", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("hits ${BACKEND_URL}/api/admin/diagnostics with all required headers", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    );
    const env = baseEnv();
    const res = await runSyntheticProbe(env);
    expect(res.ok).toBe(true);
    expect(res.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    // Task #877 — must include the FastAPI `/api` prefix; bare
    // `/admin/diagnostics` returns 404 in production.
    expect(url).toBe("https://backend.example.com/api/admin/diagnostics");
    const headers = (init as RequestInit).headers as Record<string, string>;
    expect(headers["CF-Access-Client-Id"]).toBe("client-id");
    expect(headers["CF-Access-Client-Secret"]).toBe("client-secret");
    expect(headers["Authorization"]).toBe("Bearer admin-jwt-token");
    expect(headers["X-Origin-Auth"]).toBe("origin-shared-secret");
  });

  it("honours SYNTHETIC_PROBE_TARGET_URL override", async () => {
    fetchMock.mockResolvedValueOnce(new Response("{}", { status: 200 }));
    const env = baseEnv({ SYNTHETIC_PROBE_TARGET_URL: "https://probe.example.com/diagnostics" });
    await runSyntheticProbe(env);
    expect(fetchMock.mock.calls[0][0]).toBe("https://probe.example.com/diagnostics");
  });

  it("records last_success_at and resets failure counter on 200", async () => {
    fetchMock.mockResolvedValueOnce(new Response("{}", { status: 200 }));
    const env = baseEnv();
    // pre-seed state with 3 prior failures to confirm reset on success.
    await env.RATE_LIMIT.put(
      _SYNTHETIC_PROBE_STATE_KEY,
      JSON.stringify({ consecutive_failures: 3 }),
    );
    const now = new Date("2026-04-23T10:00:00Z");
    const res = await runSyntheticProbe(env, now);
    expect(res.ok).toBe(true);
    expect(res.consecutive_failures).toBe(0);
    const state = await _readSyntheticProbeStateForTests(env.RATE_LIMIT as unknown as KVNamespace);
    expect(state.consecutive_failures).toBe(0);
    expect(state.last_success_at).toBe("2026-04-23T10:00:00.000Z");
    expect(state.last_status).toBe(200);
    expect(state.last_error).toBeNull();
  });

  it("increments consecutive_failures on non-2xx and does NOT fire watchdog before threshold", async () => {
    const env = baseEnv();
    for (let i = 1; i <= 4; i++) {
      fetchMock.mockResolvedValueOnce(new Response("denied", { status: 401 }));
      const res = await runSyntheticProbe(env, new Date(2026, 3, 23, 10, i));
      expect(res.ok).toBe(false);
      expect(res.consecutive_failures).toBe(i);
      expect(res.watchdog_fired).toBe(false);
    }
    // Only 4 fetch calls (all to the diagnostics endpoint), no watchdog
    // POST yet.
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it("fires watchdog webhook after 5 consecutive failures", async () => {
    const env = baseEnv();
    // 5 failures in a row.
    for (let i = 0; i < 4; i++) {
      fetchMock.mockResolvedValueOnce(new Response("denied", { status: 401 }));
      await runSyntheticProbe(env, new Date(Date.UTC(2026, 3, 23, 10, i)));
    }
    // 5th attempt: probe failure + watchdog POST.
    fetchMock.mockResolvedValueOnce(new Response("denied", { status: 401 }));
    fetchMock.mockResolvedValueOnce(new Response("ok", { status: 200 })); // watchdog webhook
    const res = await runSyntheticProbe(env, new Date(Date.UTC(2026, 3, 23, 10, 4)));
    expect(res.ok).toBe(false);
    expect(res.consecutive_failures).toBe(5);
    expect(res.watchdog_fired).toBe(true);

    // The 6th call to fetch should have been the watchdog POST.
    const watchdogCall = fetchMock.mock.calls[fetchMock.mock.calls.length - 1];
    expect(watchdogCall[0]).toBe("https://hooks.example.com/watchdog");
    const init = watchdogCall[1] as RequestInit;
    expect(init.method).toBe("POST");
    const body = JSON.parse(init.body as string);
    expect(body.alert_type).toBe("synthetic_probe_dark");
    expect(body.consecutive_failures).toBe(5);
    expect(body.target_url).toBe("https://backend.example.com/api/admin/diagnostics");
  });

  it("respects watchdog cooldown (does not re-fire every minute while still failing)", async () => {
    const env = baseEnv();
    // Drive to 5 failures and fire watchdog.
    for (let i = 0; i < 4; i++) {
      fetchMock.mockResolvedValueOnce(new Response("x", { status: 500 }));
      await runSyntheticProbe(env, new Date(Date.UTC(2026, 3, 23, 10, i)));
    }
    fetchMock.mockResolvedValueOnce(new Response("x", { status: 500 }));
    fetchMock.mockResolvedValueOnce(new Response("ok", { status: 200 }));
    await runSyntheticProbe(env, new Date(Date.UTC(2026, 3, 23, 10, 4)));
    expect(fetchMock).toHaveBeenCalledTimes(6);

    // 6th probe attempt 1 minute later — still failing, but watchdog is
    // in cooldown so no new POST should go out.
    fetchMock.mockResolvedValueOnce(new Response("x", { status: 500 }));
    const res = await runSyntheticProbe(env, new Date(Date.UTC(2026, 3, 23, 10, 5)));
    expect(res.consecutive_failures).toBe(6);
    expect(res.watchdog_fired).toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(7); // only the probe call

    // 5 minutes after the first watchdog: cooldown elapsed, should re-fire.
    for (let m = 6; m < 9; m++) {
      fetchMock.mockResolvedValueOnce(new Response("x", { status: 500 }));
      await runSyntheticProbe(env, new Date(Date.UTC(2026, 3, 23, 10, m)));
    }
    fetchMock.mockResolvedValueOnce(new Response("x", { status: 500 }));
    fetchMock.mockResolvedValueOnce(new Response("ok", { status: 200 })); // watchdog repost
    const res2 = await runSyntheticProbe(env, new Date(Date.UTC(2026, 3, 23, 10, 9)));
    expect(res2.consecutive_failures).toBe(10);
    expect(res2.watchdog_fired).toBe(true);
  });

  it("treats network errors as failures", async () => {
    fetchMock.mockRejectedValueOnce(new Error("fetch failed: ECONNRESET"));
    const env = baseEnv();
    const res = await runSyntheticProbe(env);
    expect(res.ok).toBe(false);
    expect(res.status).toBe(0);
    expect(res.consecutive_failures).toBe(1);
    const state = await _readSyntheticProbeStateForTests(env.RATE_LIMIT as unknown as KVNamespace);
    expect(state.last_error).toContain("ECONNRESET");
  });

  it("skips when SYNTHETIC_PROBE_DISABLED=true", async () => {
    const env = baseEnv({ SYNTHETIC_PROBE_DISABLED: "true" });
    const res = await runSyntheticProbe(env);
    expect(res.skipped).toBe(true);
    expect(res.reason).toBe("disabled_by_var");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("skips with no_target_url when neither BACKEND_URL nor TARGET_URL set", async () => {
    const env = baseEnv({ BACKEND_URL: "", SYNTHETIC_PROBE_TARGET_URL: "" });
    const res = await runSyntheticProbe(env);
    expect(res.skipped).toBe(true);
    expect(res.reason).toBe("no_target_url");
  });

  it("skips with no_kv_binding when RATE_LIMIT is absent", async () => {
    const env = baseEnv();
    delete (env as Partial<SyntheticProbeEnv>).RATE_LIMIT;
    const res = await runSyntheticProbe(env);
    expect(res.skipped).toBe(true);
    expect(res.reason).toBe("no_kv_binding");
  });

  it("logs but does not crash when watchdog webhook is unset", async () => {
    const env = baseEnv({ SYNTHETIC_PROBE_WATCHDOG_WEBHOOK_URL: "" });
    for (let i = 0; i < 5; i++) {
      fetchMock.mockResolvedValueOnce(new Response("x", { status: 500 }));
      await runSyntheticProbe(env, new Date(Date.UTC(2026, 3, 23, 10, i)));
    }
    // No webhook was posted (only 5 fetch calls — one per probe attempt).
    expect(fetchMock).toHaveBeenCalledTimes(5);
    const state = await _readSyntheticProbeStateForTests(env.RATE_LIMIT as unknown as KVNamespace);
    expect(state.consecutive_failures).toBe(5);
    expect(state.watchdog_last_fired_at).toBeNull();
  });

  it("honours SYNTHETIC_PROBE_WATCHDOG_THRESHOLD_MIN override", async () => {
    const env = baseEnv({ SYNTHETIC_PROBE_WATCHDOG_THRESHOLD_MIN: "2" });
    fetchMock.mockResolvedValueOnce(new Response("x", { status: 500 }));
    const r1 = await runSyntheticProbe(env, new Date(Date.UTC(2026, 3, 23, 10, 0)));
    expect(r1.watchdog_fired).toBe(false);
    fetchMock.mockResolvedValueOnce(new Response("x", { status: 500 }));
    fetchMock.mockResolvedValueOnce(new Response("ok", { status: 200 }));
    const r2 = await runSyntheticProbe(env, new Date(Date.UTC(2026, 3, 23, 10, 1)));
    expect(r2.consecutive_failures).toBe(2);
    expect(r2.watchdog_fired).toBe(true);
  });
});
