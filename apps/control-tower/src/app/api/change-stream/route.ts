import { controlApiBaseUrl, isValidIdentifier } from "@/lib/changeops-data";
import { serviceAuthHeaders } from "@/lib/service-auth";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  const requestUrl = new URL(request.url);
  const tenantId = requestUrl.searchParams.get("tenant_id") ?? "";
  const changeId = requestUrl.searchParams.get("change_id") ?? "";
  if (!isValidIdentifier(tenantId) || !isValidIdentifier(changeId)) {
    return Response.json(
      { code: "INVALID_STREAM_SCOPE", detail: "Tenant and change identifiers are required." },
      { status: 400 },
    );
  }

  const headers = new Headers({ Accept: "text/event-stream", "X-Tenant-ID": tenantId });
  const lastEventId = request.headers.get("Last-Event-ID");
  if (lastEventId) headers.set("Last-Event-ID", lastEventId);

  let upstream: Response;
  try {
    const platformHeaders = await serviceAuthHeaders(controlApiBaseUrl());
    for (const [name, value] of Object.entries(platformHeaders)) headers.set(name, value);
    upstream = await fetch(
      `${controlApiBaseUrl()}/v1/changes/${encodeURIComponent(changeId)}/stream?follow=true`,
      { cache: "no-store", headers, signal: request.signal },
    );
  } catch (error) {
    console.error("control_tower_stream_unavailable", { tenantId, changeId, error });
    return Response.json(
      { code: "STREAM_UNAVAILABLE", detail: "The audit stream is unavailable." },
      { status: 503 },
    );
  }
  if (!upstream.ok || upstream.body === null) {
    console.error("control_tower_stream_rejected", {
      tenantId,
      changeId,
      status: upstream.status,
    });
    return Response.json(
      { code: "STREAM_REJECTED", detail: "The audit stream could not be opened." },
      { status: upstream.status },
    );
  }
  return new Response(upstream.body, {
    headers: {
      "Cache-Control": "no-cache, no-transform",
      "Content-Type": "text/event-stream",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
