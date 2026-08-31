import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { startDemoWorkflow, submitApprovalDecision } from "./changeops-data";

describe("startDemoWorkflow", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    process.env.CONTROL_TOWER_ENVIRONMENT = "sandbox";
    process.env.CONTROL_TOWER_SANDBOX_ACTIONS_ENABLED = "true";
    process.env.PRODUCTION_WRITES_ENABLED = "false";
    process.env.SERVICE_AUTH_MODE = "none";
    process.env.AUTH_AUDIENCE = "enterprise-changeops-tool-gateway";
    process.env.EVENT_GATEWAY_WEBHOOK_SECRET = "event-secret-with-at-least-thirty-two-bytes";
    process.env.TOOL_GATEWAY_AUTH_SECRET = "tool-secret-with-at-least-thirty-two-bytes";
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

  it("retries the exact approval decision when callback delivery is transiently unavailable", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            tenant_id: "tenant_demo",
            approval_id: "approval_demo",
            status: "PENDING",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            error: { message: "The decision was stored, but the callback is unavailable." },
          }),
          { status: 503, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ status: "APPROVED" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const decision = submitApprovalDecision({
      tenantId: "tenant_demo",
      approvalId: "approval_demo",
      expectedVersion: 1,
      decision: "approve",
      comment: "Evidence verified.",
    });
    await vi.advanceTimersByTimeAsync(500);

    await expect(decision).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls[1]?.[0]).toBe(fetchMock.mock.calls[2]?.[0]);
    expect(fetchMock.mock.calls[1]?.[1]?.body).toBe(fetchMock.mock.calls[2]?.[1]?.body);
  });
});
