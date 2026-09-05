// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  set: vi.fn(),
  get: vi.fn(),
  fetch: vi.fn(),
}));
vi.mock("next/headers", () => ({
  cookies: async () => ({ set: mocks.set, get: mocks.get }),
}));
vi.mock("@/lib/service-auth", () => ({
  serviceAuthHeaders: async () => ({
    "X-Serverless-Authorization": "Bearer service-fixture",
  }),
}));

import { POST } from "./route";

beforeEach(() => {
  vi.stubEnv("ENTERPRISE_ACCESS_ENABLED", "true");
  vi.stubEnv("CONTROL_TOWER_ORIGIN", "https://changeops.example.test");
  vi.stubEnv("CONTROL_API_BASE_URL", "https://api.example.test");
  vi.stubGlobal("fetch", mocks.fetch);
  mocks.fetch.mockResolvedValue(
    Response.json({ session_cookie: "session-fixture" }),
  );
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.resetAllMocks();
});

function request(
  body = JSON.stringify({ idToken: "identity-fixture" }),
  origin = "https://changeops.example.test",
) {
  return new Request("https://changeops.example.test/api/session", {
    method: "POST",
    headers: { origin, "Content-Type": "application/json" },
    body,
  });
}

describe("enterprise cookie boundary", () => {
  it("never sends identity tokens over remote plaintext HTTP", async () => {
    vi.stubEnv("CONTROL_API_BASE_URL", "http://api.example.test");
    expect((await POST(request())).status).toBe(503);
    expect(mocks.fetch).not.toHaveBeenCalled();
    expect(mocks.set).not.toHaveBeenCalled();
  });
  it("sets only an HttpOnly secure same-site cookie and retains service authentication", async () => {
    expect((await POST(request())).status).toBe(200);
    expect(mocks.set).toHaveBeenCalledWith(
      "changeops_session",
      "session-fixture",
      {
        httpOnly: true,
        secure: true,
        sameSite: "strict",
        path: "/",
        maxAge: 28800,
      },
    );
    const headers = mocks.fetch.mock.calls[0]?.[1].headers as Headers;
    expect(headers.get("X-Serverless-Authorization")).toBe(
      "Bearer service-fixture",
    );
    expect(headers.has("Authorization")).toBe(false);
  });
  it.each(["https://attacker.example.test", "null", ""])(
    "rejects origin %s before calling identity",
    async (origin) => {
      expect((await POST(request(undefined, origin))).status).toBe(403);
      expect(mocks.fetch).not.toHaveBeenCalled();
    },
  );
  it.each(["null", "{}", "not json", JSON.stringify({ idToken: 123 })])(
    "rejects malformed login input",
    async (body) => {
      expect((await POST(request(body))).status).toBe(400);
      expect(mocks.set).not.toHaveBeenCalled();
    },
  );
  it("bounds the body", async () => {
    expect((await POST(request("x".repeat(20001)))).status).toBe(413);
    expect(mocks.fetch).not.toHaveBeenCalled();
  });
  it("fails closed for insecure deployed origins", async () => {
    vi.stubEnv("CONTROL_TOWER_ORIGIN", "http://changeops.example.test");
    expect(
      (await POST(request(undefined, "http://changeops.example.test"))).status,
    ).toBe(403);
  });
  it("does not set a cookie when identity persistence is unavailable", async () => {
    mocks.fetch.mockResolvedValue(new Response(null, { status: 503 }));
    expect((await POST(request())).status).toBe(503);
    expect(mocks.set).not.toHaveBeenCalled();
  });
  it("cannot activate enterprise login while disabled", async () => {
    vi.stubEnv("ENTERPRISE_ACCESS_ENABLED", "false");
    expect((await POST(request())).status).toBe(403);
    expect(mocks.fetch).not.toHaveBeenCalled();
  });
});
