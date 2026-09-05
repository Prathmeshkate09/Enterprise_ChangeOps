import { cookies } from "next/headers";

import {
  AccessError,
  accessRequest,
  enterpriseEnabled,
  SESSION_COOKIE,
  trustedApplicationOrigin,
} from "@/lib/enterprise-access";

export const runtime = "nodejs";

function trustedOrigin(request: Request): boolean {
  const configured = trustedApplicationOrigin();
  return Boolean(configured && request.headers.get("origin") === configured);
}

export async function POST(request: Request): Promise<Response> {
  if (!enterpriseEnabled() || !trustedOrigin(request))
    return new Response(null, { status: 403 });
  if (!request.headers.get("content-type")?.startsWith("application/json")) {
    return new Response(null, { status: 415 });
  }
  const reader = request.body?.getReader();
  if (!reader) return new Response(null, { status: 400 });
  let length = 0;
  let text = "";
  const decoder = new TextDecoder();
  while (true) {
    const chunk = await reader.read();
    if (chunk.done) break;
    length += chunk.value.byteLength;
    if (length > 20_000) {
      await reader.cancel();
      return new Response(null, { status: 413 });
    }
    text += decoder.decode(chunk.value, { stream: true });
  }
  text += decoder.decode();
  let idToken: unknown;
  try {
    idToken = (JSON.parse(text) as { idToken?: unknown }).idToken;
  } catch {
    return new Response(null, { status: 400 });
  }
  if (typeof idToken !== "string" || idToken.length > 16384 || !idToken) {
    return new Response(null, { status: 400 });
  }
  try {
    const result = await accessRequest<{ session_cookie: string }>("/session", {
      method: "POST",
      body: { id_token: idToken },
      session: "",
    });
    (await cookies()).set(SESSION_COOKIE, result.session_cookie, {
      httpOnly: true,
      secure: new URL(process.env.CONTROL_TOWER_ORIGIN!).protocol === "https:",
      sameSite: "strict",
      path: "/",
      maxAge: 8 * 60 * 60,
    });
    return Response.json(
      { ok: true },
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch (error) {
    return Response.json(
      { error: "Sign-in could not be completed." },
      {
        status: error instanceof AccessError ? error.status : 503,
        headers: { "Cache-Control": "no-store" },
      },
    );
  }
}
