import { createHash } from "node:crypto";

import { canonicalPlanJson, type RemediationPlan } from "./index.js";

export function calculatePlanHash(plan: RemediationPlan): string {
  const digest = createHash("sha256").update(canonicalPlanJson(plan), "utf8").digest("hex");
  return `sha256:${digest}`;
}
