import { describe, expect, it, vi } from "vitest";

import { ServiceAuthProvider, serviceAudience } from "./service-auth";

function token(expirySeconds: number): string {
  const payload = Buffer.from(JSON.stringify({ exp: expirySeconds }), "utf8").toString("base64url");
  return `header.${payload}.signature`;
}

describe("ServiceAuthProvider", () => {
  it("uses X-Serverless-Authorization and caches tokens by origin", async () => {
    const fetchToken = vi.fn(async () => token(2_000));
    const provider = new ServiceAuthProvider({
      mode: "google_cloud",
      fetchToken,
      now: () => 1_000_000,
    });

    const first = await provider.headers("https://service.example.run.app/v1/items");
    const second = await provider.headers("https://service.example.run.app/v1/other");

    expect(first).toEqual({ "X-Serverless-Authorization": `Bearer ${token(2_000)}` });
    expect(second).toEqual(first);
    expect(fetchToken).toHaveBeenCalledOnce();
    expect(fetchToken).toHaveBeenCalledWith("https://service.example.run.app");
  });

  it("adds no header in local mode", async () => {
    const provider = new ServiceAuthProvider({ mode: "none" });
    await expect(provider.headers("http://127.0.0.1:8000")).resolves.toEqual({});
  });

  it("rejects insecure and credentialed managed audiences", () => {
    expect(() => serviceAudience("http://service.example.run.app")).toThrow(/HTTPS/);
    expect(() => serviceAudience("https://user:pass@service.example.run.app")).toThrow(
      /credential-free/,
    );
  });
});
