"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

type LiveUpdatesProps = Readonly<{
  tenantId: string;
  changeId: string;
  active: boolean;
}>;

export function LiveUpdates({ tenantId, changeId, active }: LiveUpdatesProps) {
  const router = useRouter();
  const [connection, setConnection] = useState<"connecting" | "live">("connecting");

  useEffect(() => {
    if (!active || typeof EventSource === "undefined") {
      return;
    }
    const query = new URLSearchParams({ tenant_id: tenantId, change_id: changeId });
    const source = new EventSource(`/api/change-stream?${query.toString()}`);
    let refreshTimer: ReturnType<typeof setTimeout> | undefined;
    source.onopen = () => setConnection("live");
    source.onerror = () => setConnection("connecting");
    source.addEventListener("audit", () => {
      if (refreshTimer !== undefined) clearTimeout(refreshTimer);
      refreshTimer = setTimeout(() => router.refresh(), 250);
    });
    return () => {
      if (refreshTimer !== undefined) clearTimeout(refreshTimer);
      source.close();
    };
  }, [active, changeId, router, tenantId]);

  const effectiveConnection = active ? connection : "paused";
  const label =
    effectiveConnection === "live"
      ? "Live audit stream connected"
      : effectiveConnection === "connecting"
        ? "Reconnecting live stream"
        : "Workflow stream paused";

  return (
    <span className={`live-indicator live-indicator-${effectiveConnection}`} aria-live="polite">
      <span className="live-dot" aria-hidden="true" />
      {label}
    </span>
  );
}
