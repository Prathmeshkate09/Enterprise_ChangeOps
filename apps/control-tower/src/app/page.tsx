import { createDemoChangeAction, decideApprovalAction } from "./actions";
import { ControlTower } from "./ui/control-tower";
import { redirect } from "next/navigation";
import { enterpriseEnabled } from "@/lib/enterprise-access";

import {
  defaultTenantId,
  getDashboardData,
  isValidIdentifier,
} from "@/lib/changeops-data";

export const dynamic = "force-dynamic";

type HomePageProps = Readonly<{
  searchParams: Promise<{ tenant_id?: string; change_id?: string }>;
}>;

export default async function HomePage({ searchParams }: HomePageProps) {
  if (enterpriseEnabled()) redirect("/access-status");
  const query = await searchParams;
  const requestedTenant = query.tenant_id?.trim();
  const tenantId =
    requestedTenant && isValidIdentifier(requestedTenant) ? requestedTenant : defaultTenantId();
  const requestedChange = query.change_id?.trim();
  const changeId =
    requestedChange && isValidIdentifier(requestedChange) ? requestedChange : undefined;
  const data = await getDashboardData(tenantId, changeId);

  return (
    <ControlTower
      createDemoAction={createDemoChangeAction}
      data={data}
      decideApprovalAction={decideApprovalAction}
    />
  );
}
