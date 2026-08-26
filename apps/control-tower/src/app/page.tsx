const establishedControls = [
  "Firestore-authoritative workflow state",
  "Tenant-scoped change and audit APIs",
  "Transactional optimistic transitions",
  "Last-Event-ID stream recovery",
] as const;

export default function HomePage() {
  return (
    <main className="page-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Enterprise operations</p>
          <h1>Enterprise ChangeOps</h1>
        </div>
        <span className="environment-badge" aria-label="Sandbox environment">
          Sandbox
        </span>
      </header>

      <section className="hero" aria-labelledby="control-heading">
        <div>
          <p className="phase-label">Phase 3 / Durable control API</p>
          <h2 id="control-heading">Operational state survives service restarts.</h2>
          <p className="hero-copy">
            Tenant-partitioned Firestore state, transactional audit evidence, and resumable change
            streams now back the functional enterprise sandbox. Workflow metrics will appear only
            after measured workflow execution exists.
          </p>
        </div>

        <aside className="status-card" aria-label="Durable control API status">
          <span className="status-dot" aria-hidden="true" />
          <div>
            <p className="status-title">Durable state ready</p>
            <p className="status-detail">Production writes remain disabled.</p>
          </div>
        </aside>
      </section>

      <section className="capabilities" aria-labelledby="capabilities-heading">
        <div className="section-heading">
          <p className="eyebrow">Runnable capabilities</p>
          <h2 id="capabilities-heading">Runnable without fabricated operational data</h2>
        </div>
        <ul>
          {establishedControls.map((capability) => (
            <li key={capability}>{capability}</li>
          ))}
        </ul>
      </section>
    </main>
  );
}
