import "server-only";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { serviceAuthHeaders } from "@/lib/service-auth";

export const SESSION_COOKIE = "changeops_session";

export type Organization = {
  organization_id: string;
  name: string;
  active: boolean;
  version: number;
};
export type Workspace = {
  organization: Organization;
  membership: {
    subject: string;
    organization_id: string;
    role: string;
    active: boolean;
    version: number;
  };
};
export type AccessView = {
  subject: string;
  email: string;
  platform_admin: boolean;
  owner: boolean;
  status: string;
  workspaces: Workspace[];
};
export type AccessPage<T> = {
  items: (T & { record_id: string })[];
  next_cursor: string | null;
};
export type AccessUser = {
  subject: string;
  active: boolean;
  owner: boolean;
  platform_admin: boolean;
  version: number;
};
export type AccessAudit = {
  event_id: string;
  actor: string;
  action: string;
  resource_id: string;
  occurred_at: string;
};

export function enterpriseEnabled(): boolean {
  const value = process.env.ENTERPRISE_ACCESS_ENABLED;
  if (value !== undefined && value !== "true" && value !== "false") {
    throw new Error("ENTERPRISE_ACCESS_ENABLED must be true or false.");
  }
  return value === "true";
}

export class AccessError extends Error {
  constructor(readonly status: number) {
    super("Enterprise access request failed.");
  }
}

export async function accessRequest<T>(
  path: string,
  options: { method?: string; body?: unknown; session?: string } = {},
): Promise<T> {
  if (!enterpriseEnabled()) throw new AccessError(503);
  const base = process.env.CONTROL_API_BASE_URL;
  if (!base) throw new AccessError(503);
  const endpoint = new URL(base);
  const local = ["localhost", "127.0.0.1", "[::1]"].includes(endpoint.hostname);
  if (
    endpoint.username ||
    endpoint.password ||
    endpoint.search ||
    endpoint.hash ||
    (endpoint.protocol !== "https:" &&
      !(
        endpoint.protocol === "http:" &&
        local &&
        process.env.NODE_ENV !== "production"
      ))
  )
    throw new AccessError(503);
  const session =
    options.session ?? (await cookies()).get(SESSION_COOKIE)?.value;
  const headers = new Headers(await serviceAuthHeaders(base));
  if (session) headers.set("Authorization", `Bearer ${session}`);
  headers.set("Content-Type", "application/json");
  let response: Response;
  try {
    response = await fetch(`${base.replace(/\/$/, "")}/v1/access${path}`, {
      method: options.method ?? "GET",
      headers,
      cache: "no-store",
      ...(options.body === undefined
        ? {}
        : { body: JSON.stringify(options.body) }),
      signal: AbortSignal.timeout(15_000),
    });
  } catch {
    throw new AccessError(503);
  }
  if (!response.ok) throw new AccessError(response.status);
  return response.status === 204
    ? (undefined as T)
    : ((await response.json()) as T);
}

export async function requireAccess(): Promise<AccessView> {
  if (!enterpriseEnabled() || !(await cookies()).get(SESSION_COOKIE)?.value)
    redirect("/login");
  try {
    return await accessRequest<AccessView>("/me");
  } catch (error) {
    if (error instanceof AccessError && error.status === 401)
      redirect("/login");
    throw error;
  }
}

export async function requireAdmin(): Promise<AccessView> {
  const access = await requireAccess();
  if (!access.platform_admin) redirect("/access-status");
  return access;
}

export async function requireWorkspace(
  organizationId: string,
): Promise<Workspace> {
  await requireAccess();
  try {
    return await accessRequest<Workspace>(
      `/organizations/${encodeURIComponent(organizationId)}`,
    );
  } catch (error) {
    if (error instanceof AccessError && error.status === 403)
      redirect("/access-status");
    throw error;
  }
}

export function publicAuthConfig() {
  const apiKey = process.env.FIREBASE_WEB_API_KEY;
  const authDomain = process.env.FIREBASE_WEB_AUTH_DOMAIN;
  const projectId = process.env.IDENTITY_PLATFORM_PROJECT;
  return enterpriseEnabled() && apiKey && authDomain && projectId
    ? { apiKey, authDomain, projectId }
    : null;
}

export function trustedApplicationOrigin(): string | null {
  const configured = process.env.CONTROL_TOWER_ORIGIN;
  if (!configured) return null;
  try {
    const url = new URL(configured);
    const loopback = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
    if (
      url.username ||
      url.password ||
      url.search ||
      url.hash ||
      url.pathname !== "/"
    )
      return null;
    if (
      url.protocol !== "https:" &&
      !(
        url.protocol === "http:" &&
        loopback &&
        process.env.NODE_ENV !== "production"
      )
    )
      return null;
    return url.origin;
  } catch {
    return null;
  }
}

export function accessErrorMessage(error: unknown): string {
  if (!(error instanceof AccessError))
    return "The operation could not be completed. Try again.";
  if (error.status === 401)
    return "Your session expired. Please sign in again.";
  if (error.status === 403)
    return "This action is not permitted, or the invitation is no longer valid.";
  if (error.status === 409)
    return "This record changed. Refresh the page before trying again.";
  if (error.status === 422) return "Check the values and try again.";
  return "The access service is unavailable. No success has been recorded.";
}
