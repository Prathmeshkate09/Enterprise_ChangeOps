import "server-only";

import { GoogleAuth } from "google-auth-library";

type ServiceAuthMode = "none" | "google_cloud";
type TokenFetcher = (audience: string) => Promise<string>;

interface CachedToken {
  readonly token: string;
  readonly expiresAt: number;
}

function configuredMode(): ServiceAuthMode {
  const value = process.env.SERVICE_AUTH_MODE?.trim() || "none";
  if (value !== "none" && value !== "google_cloud") {
    throw new Error("SERVICE_AUTH_MODE must be none or google_cloud.");
  }
  return value;
}

export function serviceAudience(url: string): string {
  const parsed = new URL(url);
  if (parsed.protocol !== "https:" || parsed.username || parsed.password) {
    throw new Error("Managed service audiences must be credential-free HTTPS URLs.");
  }
  return parsed.origin;
}

function tokenExpiry(token: string): number {
  const payload = token.split(".")[1];
  if (!payload) throw new Error("Google Cloud returned an invalid identity token.");
  let decoded: unknown;
  try {
    decoded = JSON.parse(Buffer.from(payload, "base64url").toString("utf8"));
  } catch {
    throw new Error("Google Cloud returned an invalid identity token.");
  }
  if (
    typeof decoded !== "object" ||
    decoded === null ||
    typeof (decoded as Record<string, unknown>).exp !== "number"
  ) {
    throw new Error("Google Cloud identity token expiry is invalid.");
  }
  return (decoded as { exp: number }).exp * 1_000;
}

const googleAuth = new GoogleAuth();
async function fetchGoogleIdentityToken(audience: string): Promise<string> {
  const client = await googleAuth.getIdTokenClient(audience);
  return client.idTokenProvider.fetchIdToken(audience);
}

export class ServiceAuthProvider {
  private readonly cache = new Map<string, CachedToken>();
  private readonly pending = new Map<string, Promise<CachedToken>>();

  constructor(
    private readonly options: {
      readonly mode?: ServiceAuthMode;
      readonly fetchToken?: TokenFetcher;
      readonly now?: () => number;
      readonly refreshMarginMs?: number;
    } = {},
  ) {}

  async headers(url: string): Promise<Record<string, string>> {
    const mode = this.options.mode ?? configuredMode();
    if (mode === "none") return {};
    const audience = serviceAudience(url);
    const token = await this.identityToken(audience);
    return { "X-Serverless-Authorization": `Bearer ${token}` };
  }

  private async identityToken(audience: string): Promise<string> {
    const now = (this.options.now ?? Date.now)();
    const margin = this.options.refreshMarginMs ?? 300_000;
    const cached = this.cache.get(audience);
    if (cached && cached.expiresAt - margin > now) return cached.token;

    const existing = this.pending.get(audience);
    if (existing) return (await existing).token;

    const refresh = this.refresh(audience, now);
    this.pending.set(audience, refresh);
    try {
      return (await refresh).token;
    } finally {
      this.pending.delete(audience);
    }
  }

  private async refresh(audience: string, now: number): Promise<CachedToken> {
    const token = await (this.options.fetchToken ?? fetchGoogleIdentityToken)(audience);
    const expiresAt = tokenExpiry(token);
    if (expiresAt <= now) throw new Error("Google Cloud identity token is expired.");
    const cached = { token, expiresAt };
    this.cache.set(audience, cached);
    return cached;
  }
}

const defaultProvider = new ServiceAuthProvider();

export async function serviceAuthHeaders(url: string): Promise<Record<string, string>> {
  return defaultProvider.headers(url);
}
