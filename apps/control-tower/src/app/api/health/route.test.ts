import { describe, expect, it } from "vitest";

import { GET } from "./route";

describe("web health endpoint", () => {
  it("returns a non-cacheable healthy response", async () => {
    const response = GET();

    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    await expect(response.json()).resolves.toEqual({
      service: "control-tower-web",
      status: "ok",
    });
  });
});
