import type { ReactNode } from "react";
import { requireAdmin } from "@/lib/enterprise-access";
import { WorkspaceShell } from "@/app/ui/workspace-shell";

export const dynamic = "force-dynamic";

export default async function AdminLayout({
  children,
}: {
  children: ReactNode;
}) {
  await requireAdmin();
  return (
    <WorkspaceShell
      title="Administration"
      subtitle="Platform console"
      links={[
        { href: "/admin", label: "Overview" },
        { href: "/admin/organizations", label: "Organizations" },
        { href: "/admin/users", label: "Users & invitations" },
        { href: "/admin/audit", label: "Access audit" },
      ]}
    >
      {children}
    </WorkspaceShell>
  );
}
