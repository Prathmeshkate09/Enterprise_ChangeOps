import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

import { GET } from "./route";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Control Tower audit stream proxy", () => {
  it("rejects invalid tenant scope before opening the upstream stream", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const response = await GET(
      new Request("http://localhost/api/change-stream?tenant_id=../bad&change_id=chg_demo"),
    );

    expect(response.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("forwards tenant and Last-Event-ID while preserving streaming headers", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('id: audit_2\nevent: audit\ndata: {"status":"success"}\n\n', {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await GET(
      new Request(
        "http://localhost/api/change-stream?tenant_id=tenant_demo&change_id=chg_demo",
        { headers: { "Last-Event-ID": "audit_1" } },
      ),
    );

    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe("text/event-stream");
    const requestInit = fetchMock.mock.calls[0]?.[1] as RequestInit;
    const headers = new Headers(requestInit.headers);
    expect(headers.get("X-Tenant-ID")).toBe("tenant_demo");
    expect(headers.get("Last-Event-ID")).toBe("audit_1");
    await expect(response.text()).resolves.toContain("audit_2");
  });
});
