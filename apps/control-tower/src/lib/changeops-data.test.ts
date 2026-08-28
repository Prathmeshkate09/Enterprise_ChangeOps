import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { startDemoWorkflow } from "./changeops-data";

describe("startDemoWorkflow", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    process.env.CONTROL_TOWER_ENVIRONMENT = "sandbox";
    process.env.CONTROL_TOWER_SANDBOX_ACTIONS_ENABLED = "true";
    process.env.PRODUCTION_WRITES_ENABLED = "false";
    process.env.EVENT_GATEWAY_WEBHOOK_SECRET = "event-secret-with-at-least-thirty-two-bytes";
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("waits for the durable control-plane projection before returning", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ change_id: "chg_demo" }), {
          status: 202,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "The change was not found." }), {
          status: 404,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ change_id: "chg_demo" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const resultPromise = startDemoWorkflow("tenant_demo");
    await vi.advanceTimersByTimeAsync(150);

    await expect(resultPromise).resolves.toEqual({ changeId: "chg_demo" });
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toMatchObject({
      event_type: "api.contract.changed",
      tenant_id: "tenant_demo",
    });
    expect(fetchMock.mock.calls[2]?.[0]).toBe(
      "http://127.0.0.1:8000/v1/changes/chg_demo",
    );
  });
});
