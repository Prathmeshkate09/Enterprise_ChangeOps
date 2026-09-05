import type { ReactNode } from "react";
import { requireWorkspace } from "@/lib/enterprise-access";
import { WorkspaceShell } from "@/app/ui/workspace-shell";

export const dynamic = "force-dynamic";

export default async function OrganizationLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ orgId: string }>;
}) {
  const { orgId } = await params;
  const { organization } = await requireWorkspace(orgId);
  return (
    <WorkspaceShell
      title={organization.name}
      subtitle="Enterprise workspace"
      links={[
        { href: `/org/${orgId}/overview`, label: "Overview" },
        { href: `/org/${orgId}/settings`, label: "Access & settings" },
      ]}
    >
      {children}
    </WorkspaceShell>
  );
}
