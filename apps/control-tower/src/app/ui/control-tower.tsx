import Link from "next/link";

import type {
  ApprovalRequest,
  ControlTowerAction,
  DashboardData,
  WorkflowTask,
} from "@/lib/changeops-types";

import { ApprovalDecisionForm } from "./approval-decision-form";
import { DemoChangeForm } from "./demo-change-form";
import { LiveUpdates } from "./live-updates";

const TERMINAL_STATES = new Set([
  "CANCELLED",
  "COMPLETED",
  "DEAD_LETTERED",
  "FAILED",
  "NEEDS_ATTENTION",
  "REJECTED",
]);

const DATE_FORMATTER = new Intl.DateTimeFormat("en-IN", {
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  month: "short",
  timeZone: "Asia/Kolkata",
});

type ControlTowerProps = Readonly<{
  data: DashboardData;
  createDemoAction: ControlTowerAction;
  decideApprovalAction: ControlTowerAction;
}>;

function formatDate(value: string | null): string {
  if (!value) return "Not recorded";
  const timestamp = Date.parse(value);
  return Number.isNaN(timestamp) ? "Invalid timestamp" : DATE_FORMATTER.format(timestamp);
}

function humanize(value: string): string {
  return value
    .toLowerCase()
    .replaceAll("_", " ")
    .replace(/(^|\s)\S/g, (letter) => letter.toUpperCase());
}

function shortHash(value: string | null): string {
  if (!value) return "Not available";
  return value.length > 24 ? `${value.slice(0, 17)}…${value.slice(-6)}` : value;
}

function statusTone(value: string): "positive" | "warning" | "negative" | "neutral" {
  if (["ACTIVE", "APPROVED", "COMPLETED", "SUCCEEDED", "success"].includes(value)) {
    return "positive";
  }
  if (
    [
      "ANALYZING",
      "AWAITING_APPROVAL",
      "EXECUTING",
      "PENDING",
      "RECEIVED",
      "RUNNING",
      "SCREENING",
      "VERIFYING",
      "WAITING_APPROVAL",
    ].includes(value)
  ) {
    return "warning";
  }
  if (
    [
      "BLOCKED",
      "CHANGES_REQUESTED",
      "DEAD_LETTERED",
      "FAILED",
      "NEEDS_ATTENTION",
      "REJECTED",
      "ROLLBACK_FAILED",
      "failure",
      "rejected",
    ].includes(value)
  ) {
    return "negative";
  }
  return "neutral";
}

function StatusBadge({ value }: Readonly<{ value: string }>) {
  return <span className={`status-badge status-${statusTone(value)}`}>{humanize(value)}</span>;
}

function Metric({ label, value, detail }: Readonly<{ label: string; value: number; detail: string }>) {
  return (
    <article className="metric-card">
      <p>{label}</p>
      <strong>{value}</strong>
      <span>{detail}</span>
    </article>
  );
}

function EmptyState({ title, detail }: Readonly<{ title: string; detail: string }>) {
  return (
    <div className="empty-state">
      <span aria-hidden="true">◇</span>
      <h3>{title}</h3>
      <p>{detail}</p>
    </div>
  );
}

function SectionHeading({
  eyebrow,
  title,
  detail,
}: Readonly<{ eyebrow: string; title: string; detail: string }>) {
  return (
    <div className="section-heading">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h2>{title}</h2>
      </div>
      <p>{detail}</p>
    </div>
  );
}

function ChangeList({ data }: Readonly<{ data: DashboardData }>) {
  if (data.changes.length === 0) {
    return (
      <EmptyState
        title="No measured changes"
        detail="Run the golden sandbox change to create the first durable workflow for this tenant."
      />
    );
  }
  return (
    <div className="change-list" aria-label="Tenant changes">
      {data.changes.map((change) => {
        const query = new URLSearchParams({
          tenant_id: data.tenantId,
          change_id: change.change_id,
        });
        const selected = change.change_id === data.selectedChange?.change_id;
        return (
          <Link
            className={`change-row${selected ? " change-row-selected" : ""}`}
            href={`/?${query.toString()}`}
            key={change.change_id}
          >
            <span className={`risk-marker risk-${change.risk_level}`} aria-hidden="true" />
            <span className="change-row-copy">
              <strong>{change.title}</strong>
              <small>{change.change_id}</small>
            </span>
            <span className="change-row-meta">
              <StatusBadge value={change.status} />
              <small>{formatDate(change.updated_at)}</small>
            </span>
          </Link>
        );
      })}
    </div>
  );
}

function WorkflowTaskCard({
  task,
  order,
  toolName,
  dependencies,
}: Readonly<{
  task: WorkflowTask;
  order: number;
  toolName: string;
  dependencies: readonly string[];
}>) {
  return (
    <article className="task-card">
      <div className="task-number">{String(order).padStart(2, "0")}</div>
      <div className="task-copy">
        <div className="task-title-row">
          <div>
            <p className="eyebrow">{task.system_id} system</p>
            <h3>{humanize(task.step_id)}</h3>
          </div>
          <StatusBadge value={task.status} />
        </div>
        <dl className="compact-definition">
          <div><dt>Registered tool</dt><dd>{toolName}</dd></div>
          <div><dt>Attempts</dt><dd>{task.attempt_count}</dd></div>
          <div><dt>Depends on</dt><dd>{dependencies.length > 0 ? dependencies.join(", ") : "Entry step"}</dd></div>
          <div><dt>Snapshot</dt><dd className="mono">{shortHash(task.snapshot_hash)}</dd></div>
        </dl>
        {task.error_code ? <p className="inline-error">Error: {task.error_code}</p> : null}
      </div>
    </article>
  );
}

function ApprovalCard({
  approval,
  enabled,
  action,
}: Readonly<{
  approval: ApprovalRequest;
  enabled: boolean;
  action: ControlTowerAction;
}>) {
  return (
    <article className="approval-card">
      <div className="approval-card-header">
        <div>
          <p className="eyebrow">Exact-plan authorization</p>
          <h3>{approval.approval_id}</h3>
        </div>
        <StatusBadge value={approval.status} />
      </div>
      <dl className="detail-grid">
        <div><dt>Plan hash</dt><dd className="mono" title={approval.plan_hash}>{shortHash(approval.plan_hash)}</dd></div>
        <div><dt>Scope</dt><dd>{approval.scope.join(", ")}</dd></div>
        <div><dt>Requested by</dt><dd>{approval.requested_by}</dd></div>
        <div><dt>Expires</dt><dd>{formatDate(approval.expires_at)}</dd></div>
      </dl>
      {approval.status === "PENDING" ? (
        <ApprovalDecisionForm
          action={action}
          approvalId={approval.approval_id}
          enabled={enabled}
          expectedVersion={approval.version}
          tenantId={approval.tenant_id}
        />
      ) : (
        <div className="decision-summary">
          <strong>{approval.decided_by ?? "Unknown operator"}</strong>
          <span>{approval.comment ?? "No decision rationale recorded."}</span>
        </div>
      )}
    </article>
  );
}

export function ControlTower({ data, createDemoAction, decideApprovalAction }: ControlTowerProps) {
  const selected = data.selectedChange;
  const workflow = data.workflow;
  const openChanges = data.changes.filter((change) => !TERMINAL_STATES.has(change.status)).length;
  const pendingApprovals = data.approvals.filter((item) => item.status === "PENDING").length;
  const criticalChanges = data.changes.filter((change) =>
    ["critical", "high"].includes(change.risk_level),
  ).length;
  const activeStream = workflow !== null && !TERMINAL_STATES.has(workflow.status);
  const uniqueIssues = data.issues.filter(
    (issue, index, items) =>
      items.findIndex(
        (candidate) => candidate.service === issue.service && candidate.message === issue.message,
      ) === index,
  );

  return (
    <div className="control-tower-shell">
      <aside className="nav-rail">
        <Link className="brand" href={`/?tenant_id=${encodeURIComponent(data.tenantId)}`}>
          <span className="brand-mark" aria-hidden="true">CO</span>
          <span><strong>ChangeOps</strong><small>Control Tower</small></span>
        </Link>
        <nav aria-label="Control Tower sections">
          <a href="#overview"><span aria-hidden="true">⌂</span>Overview</a>
          <a href="#workflow"><span aria-hidden="true">⌁</span>Workflow</a>
          <a href="#fleet"><span aria-hidden="true">⌘</span>Agent fleet</a>
          <a href="#approvals"><span aria-hidden="true">✓</span>Approvals</a>
          <a href="#security"><span aria-hidden="true">◇</span>Security</a>
          <a href="#audit"><span aria-hidden="true">≡</span>Audit trail</a>
        </nav>
        <div className="sandbox-lock">
          <span className="lock-icon" aria-hidden="true">◆</span>
          <div><strong>Sandbox locked</strong><small>Production writes off</small></div>
        </div>
      </aside>

      <div className="tower-main">
        <header className="command-bar">
          <div><p className="eyebrow">Enterprise operations</p><h1>Enterprise ChangeOps</h1></div>
          <form className="tenant-switcher" method="get">
            <label htmlFor="tenant-id">Tenant</label>
            <input
              defaultValue={data.tenantId}
              id="tenant-id"
              maxLength={128}
              name="tenant_id"
              pattern="[A-Za-z0-9][A-Za-z0-9._:-]{0,127}"
              required
            />
            <button className="button button-secondary" type="submit">Load</button>
          </form>
          <div className="operator-chip" aria-label="Local sandbox operator">
            <span>CT</span>
            <div><strong>Local operator</strong><small>Approver · Auditor</small></div>
          </div>
        </header>

        <main>
          <section className="hero-panel" id="overview">
            <div className="hero-copy">
              <div className="hero-kicker">
                <span className="environment-badge">Sandbox</span>
                <span>Phase 7 · Operational command</span>
              </div>
              <h2>{selected?.title ?? "Govern every change from evidence to rollback."}</h2>
              <p>
                {selected?.description ??
                  "Start the golden change to watch the durable workflow analyze impact, request exact-plan approval, execute bounded tools, and preserve audit evidence."}
              </p>
              <div className="hero-actions">
                <DemoChangeForm action={createDemoAction} enabled={data.sandboxActionsEnabled} tenantId={data.tenantId} />
                {selected ? <LiveUpdates active={activeStream} changeId={selected.change_id} tenantId={data.tenantId} /> : null}
              </div>
              {!data.sandboxActionsEnabled ? (
                <p className="action-boundary">
                  Interactive mutations are disabled in this deployment. Set the explicit local sandbox action flag to enable the demo.
                </p>
              ) : null}
            </div>
            <div className="hero-signal" aria-label="Selected change status">
              <span className="signal-orbit" aria-hidden="true"><span /></span>
              <div>
                <p>Current state</p>
                <strong>{humanize(workflow?.status ?? selected?.status ?? "Ready")}</strong>
                <small>{selected ? `Updated ${formatDate(selected.updated_at)}` : "No change selected"}</small>
              </div>
            </div>
          </section>

          {uniqueIssues.length > 0 ? (
            <section className="service-alert" aria-label="Service availability issues">
              <div><strong>Some operational evidence is unavailable</strong><p>No unavailable source is being treated as successful.</p></div>
              <ul>
                {uniqueIssues.map((issue) => (
                  <li key={`${issue.service}-${issue.message}`}><strong>{issue.service}</strong>: {issue.message}</li>
                ))}
              </ul>
            </section>
          ) : null}

          <section className="metrics-grid" aria-label="Measured tenant metrics">
            <Metric label="Tracked changes" value={data.changes.length} detail="Durable tenant records" />
            <Metric label="Open workflows" value={openChanges} detail="Measured non-terminal state" />
            <Metric label="Pending approvals" value={pendingApprovals} detail="Exact-plan decisions" />
            <Metric label="High-risk changes" value={criticalChanges} detail="High or critical classification" />
          </section>

          <section className="dashboard-section">
            <SectionHeading detail="Select a durable tenant-scoped record to inspect its governed execution." eyebrow="Change portfolio" title="Operational queue" />
            <ChangeList data={data} />
          </section>

          <section className="dashboard-section" id="workflow">
            <SectionHeading detail="Every task is scheduled from the persisted dependency graph and executed through the Tool Gateway." eyebrow="Durable orchestration" title="Workflow execution" />
            {selected && workflow ? (
              <>
                <div className="workflow-summary">
                  <div><p className="eyebrow">Execution</p><h3>{workflow.workflow_execution_id}</h3><p>{workflow.plan?.summary ?? "Analysis is still producing the remediation plan."}</p></div>
                  <dl>
                    <div><dt>Status</dt><dd><StatusBadge value={workflow.status} /></dd></div>
                    <div><dt>Delivery attempts</dt><dd>{workflow.delivery_attempts}</dd></div>
                    <div><dt>Plan version</dt><dd>{workflow.plan?.version ?? "Pending"}</dd></div>
                    <div><dt>Last error</dt><dd>{workflow.last_error_code ?? "None"}</dd></div>
                  </dl>
                </div>
                {workflow.tasks.length > 0 ? (
                  <div className="task-grid">
                    {workflow.tasks.map((task) => {
                      const planStep = workflow.plan?.steps.find((step) => step.step_id === task.step_id);
                      return <WorkflowTaskCard dependencies={planStep?.depends_on ?? []} key={task.step_id} order={planStep?.order ?? 0} task={task} toolName={planStep?.tool_name ?? "Plan pending"} />;
                    })}
                  </div>
                ) : (
                  <EmptyState title="Analysis in progress" detail="The seven-agent fleet is gathering authoritative sandbox evidence before a plan can be scheduled." />
                )}
              </>
            ) : (
              <EmptyState title={selected ? "Workflow record is not ready" : "Select or start a change"} detail="Workflow evidence will appear here as soon as the durable coordinator persists it." />
            )}
          </section>

          <section className="dashboard-section" id="fleet">
            <SectionHeading detail="Registered analysis agents have bounded tools, resources, risk ceilings, and invocation budgets." eyebrow="Google ADK fleet" title={`${data.agents.length} registered agents`} />
            {data.agents.length > 0 ? (
              <div className="agent-grid">
                {data.agents.map((agent) => (
                  <article className="agent-card" key={agent.agent_id}>
                    <div className="agent-card-top">
                      <span className="agent-monogram" aria-hidden="true">{agent.display_name.split(" ").map((part) => part[0]).join("").slice(0, 2)}</span>
                      <StatusBadge value={agent.status.toUpperCase()} />
                    </div>
                    <h3>{agent.display_name}</h3>
                    <p>{agent.description}</p>
                    <div className="tag-row">{agent.capabilities.slice(0, 2).map((capability) => <span key={capability}>{capability}</span>)}</div>
                    <dl className="agent-budget">
                      <div><dt>Model calls</dt><dd>{agent.budget.max_model_calls}</dd></div>
                      <div><dt>Tool calls</dt><dd>{agent.budget.max_tool_calls}</dd></div>
                      <div><dt>Risk ceiling</dt><dd>{humanize(agent.risk_ceiling)}</dd></div>
                    </dl>
                  </article>
                ))}
              </div>
            ) : <EmptyState title="Agent registry unavailable" detail="No agent registration is being inferred." />}
          </section>

          <section className="dashboard-section" id="approvals">
            <SectionHeading detail="Decisions bind the authoritative plan hash, version, environment, scope, and independent operator." eyebrow="Human control point" title="Approval workspace" />
            {data.approvals.length > 0 ? (
              <div className="approval-list">
                {data.approvals.map((approval) => <ApprovalCard action={decideApprovalAction} approval={approval} enabled={data.sandboxActionsEnabled} key={approval.approval_id} />)}
              </div>
            ) : (
              <EmptyState title={workflow?.status === "ANALYZING" ? "Plan analysis is still running" : "No approval request"} detail="An approval card appears only after the workflow persists an exact plan and enters its approval wait state." />
            )}
          </section>

          <section className="dashboard-section" id="security">
            <SectionHeading detail="These values come from the current workflow and closed registries—not a model-generated assurance." eyebrow="Deterministic guardrails" title="Security posture" />
            <div className="guardrail-grid">
              <article className="guardrail-card guardrail-locked"><span aria-hidden="true">◆</span><div><p>Production mutations</p><strong>Hard disabled</strong><small>Sandbox tools only</small></div></article>
              <article className="guardrail-card"><span aria-hidden="true">#</span><div><p>Authoritative plan</p><strong>{shortHash(workflow?.plan_hash ?? null)}</strong><small>SHA-256 bound approval</small></div></article>
              <article className="guardrail-card"><span aria-hidden="true">⌁</span><div><p>Closed tool registry</p><strong>{data.tools.length} tools</strong><small>No caller-selected endpoints</small></div></article>
              <article className={`guardrail-card${data.deadLetters.length > 0 ? " guardrail-alert" : ""}`}><span aria-hidden="true">!</span><div><p>Dead letters</p><strong>{data.deadLetters.length}</strong><small>Permanent events retained</small></div></article>
            </div>
            {data.tools.length > 0 ? (
              <div className="registry-table-wrap">
                <table className="registry-table">
                  <caption>Executable registry enforced by the Tool Gateway</caption>
                  <thead><tr><th>Tool</th><th>Owner</th><th>Resource scope</th><th>Risk</th><th>Policies</th></tr></thead>
                  <tbody>
                    {data.tools.map((tool) => (
                      <tr key={tool.tool_name}>
                        <td className="mono">{tool.tool_name}</td><td>{tool.owning_agent_id}</td><td className="mono">{tool.resource_pattern}</td><td><StatusBadge value={tool.risk_level.toUpperCase()} /></td><td>{tool.policy_ids.join(", ")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </section>

          <section className="dashboard-section" id="audit">
            <SectionHeading detail="Control-plane transitions and gateway decisions are merged by timestamp for the selected change." eyebrow="Evidence ledger" title={`${data.audit.length} audit events`} />
            {data.audit.length > 0 ? (
              <ol className="audit-timeline">
                {data.audit.map((event) => (
                  <li key={event.audit_event_id}>
                    <span className={`audit-marker audit-marker-${statusTone(event.status)}`} aria-hidden="true" />
                    <div className="audit-card">
                      <div className="audit-card-header"><div><strong>{humanize(event.event_type)}</strong><span>{formatDate(event.created_at)}</span></div><StatusBadge value={event.status} /></div>
                      <p>{event.redacted_summary}</p>
                      <dl>
                        <div><dt>Actor</dt><dd>{event.actor_id} · {event.actor_type}</dd></div>
                        <div><dt>Action</dt><dd>{event.action}</dd></div>
                        <div><dt>Resource</dt><dd className="mono">{event.resource}</dd></div>
                        <div><dt>Trace</dt><dd className="mono">{event.trace_id}</dd></div>
                      </dl>
                    </div>
                  </li>
                ))}
              </ol>
            ) : <EmptyState title="No audit evidence yet" detail="No audit event is being fabricated for this view." />}
          </section>
        </main>
        <footer className="tower-footer"><span>Enterprise ChangeOps · local sandbox</span><span>Deterministic control · tenant isolation · production writes disabled</span></footer>
      </div>
    </div>
  );
}
