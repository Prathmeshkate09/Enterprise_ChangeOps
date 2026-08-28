"use client";

import { useEffect } from "react";

export default function ErrorPage({
  error,
  reset,
}: Readonly<{ error: Error & { digest?: string }; reset: () => void }>) {
  useEffect(() => {
    console.error("control_tower_render_failure", error);
  }, [error]);

  return (
    <main className="error-shell">
      <span className="error-symbol" aria-hidden="true">!</span>
      <p className="eyebrow">Control Tower unavailable</p>
      <h1>The operational view could not be rendered.</h1>
      <p>The failure was not treated as a successful or empty response. Retry after checking service health.</p>
      <button className="button button-primary" onClick={reset} type="button">Try again</button>
    </main>
  );
}
