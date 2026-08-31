import "server-only";

import { createHmac, randomUUID } from "node:crypto";

import type {
  AgentRegistration,
  ApprovalRequest,
  AuditEvent,
  ChangeRecord,
  DashboardData,
  DeadLetterRecord,
  ServiceIssue,
  ToolRegistration,
  WorkflowExecution,
} from "./changeops-types";
import { serviceAuthHeaders } from "./service-auth";

const IDENTIFIER_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const REQUEST_TIMEOUT_MS = 6_000;
const CHANGE_PROJECTION_TIMEOUT_MS = 10_000;
const CHANGE_PROJECTION_RETRY_MS = 150;
const APPROVAL_CALLBACK_RETRY_MS = 500;

type UpstreamName =
  | "Agent Fleet"
  | "Control API"
  | "Event Gateway"
  | "Tool Gateway"
  | "Workflow Coordinator";

class UpstreamError extends Error {
  constructor(
    readonly service: UpstreamName,
    message: string,
    readonly status: number | null = null,
  ) {
    super(message);
    this.name = "UpstreamError";
  }
}

function serviceUrl(environmentName: string, fallback: string): string {
  const configured = process.env[environmentName]?.trim();
  return (configured || fallback).replace(/\/$/, "");
}

export function controlApiBaseUrl(): string {
  return serviceUrl("CONTROL_API_BASE_URL", "http://127.0.0.1:8000");
}

function agentFleetBaseUrl(): string {
  return serviceUrl("AGENT_FLEET_BASE_URL", "http://127.0.0.1:8200");
}

function toolGatewayBaseUrl(): string {
  return serviceUrl("TOOL_GATEWAY_BASE_URL", "http://127.0.0.1:8300");
}

function eventGatewayBaseUrl(): string {
  return serviceUrl("EVENT_GATEWAY_BASE_URL", "http://127.0.0.1:8400");
}

function workflowCoordinatorBaseUrl(): string {
  return serviceUrl("WORKFLOW_COORDINATOR_BASE_URL", "http://127.0.0.1:8500");
}

function requiredSecret(name: "EVENT_GATEWAY_WEBHOOK_SECRET" | "TOOL_GATEWAY_AUTH_SECRET") {
  const value = process.env[name];
  if (value === undefined || Buffer.byteLength(value, "utf8") < 32) {
    throw new Error(`${name} must contain at least 32 bytes.`);
  }
  return value;
}

function authAudience(): string {
  const value = process.env.AUTH_AUDIENCE?.trim();
  if (!value) {
    throw new Error("AUTH_AUDIENCE is required for governed Control Tower reads and actions.");
  }
  return value;
}

function encodeBase64Url(value: object): string {
  return Buffer.from(JSON.stringify(value), "utf8").toString("base64url");
}

function issueOperatorToken(tenantId: string, roles: readonly string[]): string {
  const now = Math.floor(Date.now() / 1_000);
  const header = encodeBase64Url({ alg: "HS256", typ: "JWT" });
  const payload = encodeBase64Url({
    aud: authAudience(),
    exp: now + 15 * 60,
    iat: now,
    kind: "user",
    roles,
    sub: "control-tower-local-operator",
    tenant_id: tenantId,
  });
  const signingInput = `${header}.${payload}`;
  const signature = createHmac("sha256", requiredSecret("TOOL_GATEWAY_AUTH_SECRET"))
    .update(signingInput, "ascii")
    .digest("base64url");
  return `${signingInput}.${signature}`;
}

function operatorHeaders(tenantId: string, roles: readonly string[]): HeadersInit {
  return {
    Authorization: `Bearer ${issueOperatorToken(tenantId, roles)}`,
    "X-Request-ID": `tower_${randomUUID().replaceAll("-", "")}`,
  };
}

function describeUpstreamError(payload: unknown, fallback: string): string {
  if (typeof payload !== "object" || payload === null) return fallback;
  const record = payload as Record<string, unknown>;
  if (typeof record.detail === "string") return record.detail;
  const nested = record.error;
  if (typeof nested === "object" && nested !== null) {
    const message = (nested as Record<string, unknown>).message;
    if (typeof message === "string") return message;
  }
  return fallback;
}

async function requestJson<T>(
  service: UpstreamName,
  url: string,
  init: RequestInit = {},
): Promise<T> {
  let response: Response;
  try {
    const headers = new Headers(init.headers);
    const platformHeaders = await serviceAuthHeaders(url);
    for (const [name, value] of Object.entries(platformHeaders)) headers.set(name, value);
    response = await fetch(url, {
      ...init,
      headers,
      cache: "no-store",
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
  } catch (error) {
    console.error("control_tower_upstream_unavailable", { service, error });
    throw new UpstreamError(service, `${service} is unavailable.`);
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch (error) {
    console.error("control_tower_invalid_json", { service, status: response.status, error });
    throw new UpstreamError(service, `${service} returned an invalid response.`, response.status);
  }
  if (!response.ok) {
    throw new UpstreamError(
      service,
      describeUpstreamError(payload, `${service} request failed.`),
      response.status,
    );
  }
  return payload as T;
}

function listItems<T>(service: UpstreamName, payload: unknown): readonly T[] {
  if (typeof payload !== "object" || payload === null) {
    throw new UpstreamError(service, `${service} returned an invalid list response.`);
  }
  const items = (payload as Record<string, unknown>).items;
  if (!Array.isArray(items)) {
    throw new UpstreamError(service, `${service} returned an invalid list response.`);
  }
  return items as readonly T[];
}

function resultOrIssue<T>(
  result: PromiseSettledResult<T>,
  fallback: T,
  issues: ServiceIssue[],
  service: UpstreamName,
): T {
  if (result.status === "fulfilled") return result.value;
  const error = result.reason;
  const message = error instanceof Error ? error.message : `${service} request failed.`;
  issues.push({ service, message });
  return fallback;
}

export function isValidIdentifier(value: string): boolean {
  return IDENTIFIER_PATTERN.test(value);
}

export function defaultTenantId(): string {
  const configured = process.env.DEMO_TENANT_ID?.trim();
  return configured && isValidIdentifier(configured) ? configured : "tenant_control_tower_demo";
}

export function sandboxActionsEnabled(): boolean {
  return (
    process.env.CONTROL_TOWER_ENVIRONMENT === "sandbox" &&
    process.env.CONTROL_TOWER_SANDBOX_ACTIONS_ENABLED === "true" &&
    process.env.PRODUCTION_WRITES_ENABLED === "false"
  );
}

export function assertSandboxActionsEnabled(): void {
  if (!sandboxActionsEnabled()) {
    throw new Error("Sandbox actions are disabled for this Control Tower deployment.");
  }
}

async function listChanges(tenantId: string): Promise<readonly ChangeRecord[]> {
  const payload = await requestJson<unknown>(
    "Control API",
    `${controlApiBaseUrl()}/v1/changes?limit=100`,
    { headers: { "X-Tenant-ID": tenantId } },
  );
  return listItems<ChangeRecord>("Control API", payload).toSorted((left, right) =>
    right.updated_at.localeCompare(left.updated_at),
  );
}

async function getChange(tenantId: string, changeId: string): Promise<ChangeRecord> {
  return requestJson<ChangeRecord>(
    "Control API",
    `${controlApiBaseUrl()}/v1/changes/${encodeURIComponent(changeId)}`,
    { headers: { "X-Tenant-ID": tenantId } },
  );
}

async function waitForChangeProjection(tenantId: string, changeId: string): Promise<void> {
  const deadline = Date.now() + CHANGE_PROJECTION_TIMEOUT_MS;
  while (true) {
    try {
      await getChange(tenantId, changeId);
      return;
    } catch (error) {
      if (!(error instanceof UpstreamError) || error.status !== 404) throw error;
      if (Date.now() >= deadline) {
        throw new UpstreamError(
          "Control API",
          "The event was accepted, but its durable change record was not available within 10 seconds.",
        );
      }
      await new Promise((resolve) => setTimeout(resolve, CHANGE_PROJECTION_RETRY_MS));
    }
  }
}

async function listChangeAudit(
  tenantId: string,
  changeId: string,
): Promise<readonly AuditEvent[]> {
  const payload = await requestJson<unknown>(
    "Control API",
    `${controlApiBaseUrl()}/v1/changes/${encodeURIComponent(changeId)}/audit?limit=500`,
    { headers: { "X-Tenant-ID": tenantId } },
  );
  return listItems<AuditEvent>("Control API", payload);
}

async function getWorkflow(
  tenantId: string,
  changeId: string,
  workflowId: string,
): Promise<WorkflowExecution> {
  const query = new URLSearchParams({ change_id: changeId });
  return requestJson<WorkflowExecution>(
    "Workflow Coordinator",
    `${workflowCoordinatorBaseUrl()}/v1/workflows/${encodeURIComponent(workflowId)}?${query}`,
    { headers: { "X-Tenant-ID": tenantId } },
  );
}

async function listDeadLetters(tenantId: string): Promise<readonly DeadLetterRecord[]> {
  const payload = await requestJson<unknown>(
    "Workflow Coordinator",
    `${workflowCoordinatorBaseUrl()}/v1/dead-letters?limit=100`,
    { headers: { "X-Tenant-ID": tenantId } },
  );
  return listItems<DeadLetterRecord>("Workflow Coordinator", payload);
}

async function listAgents(tenantId: string): Promise<readonly AgentRegistration[]> {
  const payload = await requestJson<unknown>("Agent Fleet", `${agentFleetBaseUrl()}/v1/agents`, {
    headers: { "X-Tenant-ID": tenantId },
  });
  if (!Array.isArray(payload)) {
    throw new UpstreamError("Agent Fleet", "Agent Fleet returned an invalid registry response.");
  }
  return payload as readonly AgentRegistration[];
}

async function listApprovals(tenantId: string): Promise<readonly ApprovalRequest[]> {
  const payload = await requestJson<unknown>(
    "Tool Gateway",
    `${toolGatewayBaseUrl()}/v1/approvals?limit=100`,
    { headers: operatorHeaders(tenantId, ["APPROVER", "AUDITOR"]) },
  );
  return listItems<ApprovalRequest>("Tool Gateway", payload);
}

async function listGatewayAudit(tenantId: string): Promise<readonly AuditEvent[]> {
  const payload = await requestJson<unknown>(
    "Tool Gateway",
    `${toolGatewayBaseUrl()}/v1/audit?limit=500`,
    { headers: operatorHeaders(tenantId, ["AUDITOR"]) },
  );
  return listItems<AuditEvent>("Tool Gateway", payload);
}

async function listTools(tenantId: string): Promise<readonly ToolRegistration[]> {
  const payload = await requestJson<unknown>("Tool Gateway", `${toolGatewayBaseUrl()}/v1/tools`, {
    headers: operatorHeaders(tenantId, ["AUDITOR"]),
  });
  if (!Array.isArray(payload)) {
    throw new UpstreamError("Tool Gateway", "Tool Gateway returned an invalid registry response.");
  }
  return payload as readonly ToolRegistration[];
}

export async function getDashboardData(
  tenantId: string,
  requestedChangeId?: string,
): Promise<DashboardData> {
  if (!isValidIdentifier(tenantId)) throw new Error("Tenant identifier is invalid.");
  if (requestedChangeId !== undefined && !isValidIdentifier(requestedChangeId)) {
    throw new Error("Change identifier is invalid.");
  }

  const issues: ServiceIssue[] = [];
  const [changesResult, agentsResult, approvalsResult, gatewayAuditResult, toolsResult, dlqResult] =
    await Promise.allSettled([
      listChanges(tenantId),
      listAgents(tenantId),
      listApprovals(tenantId),
      listGatewayAudit(tenantId),
      listTools(tenantId),
      listDeadLetters(tenantId),
    ]);

  const changes = resultOrIssue(changesResult, [], issues, "Control API");
  const agents = resultOrIssue(agentsResult, [], issues, "Agent Fleet");
  const approvals = resultOrIssue(approvalsResult, [], issues, "Tool Gateway");
  const gatewayAudit = resultOrIssue(gatewayAuditResult, [], issues, "Tool Gateway");
  const tools = resultOrIssue(toolsResult, [], issues, "Tool Gateway");
  const deadLetters = resultOrIssue(dlqResult, [], issues, "Workflow Coordinator");

  let selectedChange =
    (requestedChangeId
      ? changes.find((change) => change.change_id === requestedChangeId)
      : changes[0]) ?? null;
  if (selectedChange === null && requestedChangeId !== undefined) {
    const detailResult = await Promise.allSettled([getChange(tenantId, requestedChangeId)]);
    selectedChange = resultOrIssue(detailResult[0], null, issues, "Control API");
  }

  let workflow: WorkflowExecution | null = null;
  let changeAudit: readonly AuditEvent[] = [];
  if (selectedChange !== null) {
    const [auditResult, workflowResult] = await Promise.allSettled([
      listChangeAudit(tenantId, selectedChange.change_id),
      selectedChange.workflow_execution_id
        ? getWorkflow(tenantId, selectedChange.change_id, selectedChange.workflow_execution_id)
        : Promise.resolve(null),
    ]);
    changeAudit = resultOrIssue(auditResult, [], issues, "Control API");
    workflow = resultOrIssue(workflowResult, null, issues, "Workflow Coordinator");
  }

  const selectedId = selectedChange?.change_id;
  const combinedAudit = [...changeAudit, ...gatewayAudit.filter((item) => item.change_id === selectedId)]
    .filter(
      (item, index, all) =>
        all.findIndex((candidate) => candidate.audit_event_id === item.audit_event_id) === index,
    )
    .toSorted((left, right) => right.created_at.localeCompare(left.created_at));

  return {
    tenantId,
    sandboxActionsEnabled: sandboxActionsEnabled(),
    changes,
    selectedChange,
    workflow,
    approvals: approvals.filter((item) => item.change_id === selectedId),
    agents,
    tools,
    audit: combinedAudit,
    deadLetters: deadLetters.filter(
      (item) => selectedChange === null || item.workflow_execution_id === selectedChange.workflow_execution_id,
    ),
    issues,
  };
}

export async function startDemoWorkflow(tenantId: string): Promise<{ changeId: string }> {
  assertSandboxActionsEnabled();
  if (!isValidIdentifier(tenantId)) throw new Error("Tenant identifier is invalid.");

  const compactId = randomUUID().replaceAll("-", "");
  const timestamp = new Date().toISOString();
  const eventId = `evt_ui_${compactId}`;
  const event = {
    schema_version: "1.0",
    event_id: eventId,
    tenant_id: tenantId,
    event_type: "api.contract.changed",
    source: {
      type: "github",
      external_id: `pr-${eventId}`,
      url: "https://example.invalid/changeops/control-tower",
    },
    occurred_at: timestamp,
    received_at: timestamp,
    subject: {
      system_id: "customer-api",
      resource_type: "api-contract",
      resource_id: "customer-api-v2",
    },
    change: {
      summary: "Rename customer_id to customer_uuid",
      old_version: "1.4.0",
      new_version: "2.0.0",
      artifact_refs: ["artifact://contracts/customer-v2-diff.json"],
    },
    correlation_id: `correlation-${eventId}`,
    trace_id: `trace-${eventId}`,
  };
  const body = JSON.stringify(event);
  const signature = createHmac("sha256", requiredSecret("EVENT_GATEWAY_WEBHOOK_SECRET"))
    .update(body, "utf8")
    .digest("hex");
  const accepted = await requestJson<{ change_id?: unknown }>(
    "Event Gateway",
    `${eventGatewayBaseUrl()}/v1/events/change`,
    {
      method: "POST",
      body,
      headers: {
        "Content-Type": "application/json",
        "X-ChangeOps-Signature": `sha256=${signature}`,
        "X-Request-ID": `tower_${compactId}`,
      },
    },
  );
  if (typeof accepted.change_id !== "string" || !isValidIdentifier(accepted.change_id)) {
    throw new UpstreamError("Event Gateway", "Event Gateway returned an invalid change ID.");
  }
  await waitForChangeProjection(tenantId, accepted.change_id);
  return { changeId: accepted.change_id };
}

export async function submitApprovalDecision(input: {
  tenantId: string;
  approvalId: string;
  expectedVersion: number;
  decision: "approve" | "reject" | "request-changes";
  comment: string;
}): Promise<void> {
  assertSandboxActionsEnabled();
  if (!isValidIdentifier(input.tenantId) || !isValidIdentifier(input.approvalId)) {
    throw new Error("Approval scope is invalid.");
  }
  if (!Number.isSafeInteger(input.expectedVersion) || input.expectedVersion < 1) {
    throw new Error("Approval version is invalid.");
  }
  const comment = input.comment.trim();
  if (comment.length < 2 || comment.length > 512) {
    throw new Error("Decision rationale must contain between 2 and 512 characters.");
  }

  const headers = operatorHeaders(input.tenantId, ["APPROVER"]);
  const current = await requestJson<ApprovalRequest>(
    "Tool Gateway",
    `${toolGatewayBaseUrl()}/v1/approvals/${encodeURIComponent(input.approvalId)}`,
    { headers },
  );
  if (current.tenant_id !== input.tenantId || current.approval_id !== input.approvalId) {
    throw new Error("Approval scope does not match the selected tenant.");
  }
  if (current.status !== "PENDING") throw new Error("This approval is no longer pending.");

  const decisionUrl = `${toolGatewayBaseUrl()}/v1/approvals/${encodeURIComponent(input.approvalId)}/${input.decision}`;
  const decisionRequest = () =>
    requestJson<ApprovalRequest>("Tool Gateway", decisionUrl, {
      method: "POST",
      headers: { ...headers, "Content-Type": "application/json" },
      body: JSON.stringify({ expected_version: input.expectedVersion, comment }),
    });
  try {
    await decisionRequest();
  } catch (error) {
    if (!(error instanceof UpstreamError) || error.status !== 503) throw error;
    // The gateway stores the decision before delivering its workflow callback.
    // Its exact-retry contract makes this safe while preventing a divergent
    // second decision from being accepted.
    await new Promise((resolve) => setTimeout(resolve, APPROVAL_CALLBACK_RETRY_MS));
    await decisionRequest();
  }
}

export function safeActionError(error: unknown, fallback: string): string {
  if (error instanceof UpstreamError) return error.message;
  if (error instanceof Error && error.message.length <= 180) return error.message;
  return fallback;
}
