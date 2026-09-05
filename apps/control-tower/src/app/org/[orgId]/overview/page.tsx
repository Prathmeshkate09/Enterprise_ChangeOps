import Link from "next/link";
import { requireWorkspace } from "@/lib/enterprise-access";
import { PageHeading } from "@/app/ui/workspace-shell";

export default async function OrganizationOverview({
  params,
}: {
  params: Promise<{ orgId: string }>;
}) {
  const { orgId } = await params;
  const { organization, membership } = await requireWorkspace(orgId);
  return (
    <>
      <PageHeading
        eyebrow="Your workspace"
        title={`Welcome to ${organization.name}`}
        description="Your organization has a private workspace. External connections will become available after the integration acceptance checks."
      />
      <section className="access-card access-callout">
        <span className="access-pill">Access ready</span>
        <h2>Start with a verified connection</h2>
        <p>
          Real enterprise connectors are not enabled in this release. No
          external system is being monitored and no company data has been
          imported by this workspace.
        </p>
        <Link href={`/org/${orgId}/settings`} className="access-button">
          Review workspace access
        </Link>
      </section>
      <div className="access-grid">
        <section className="access-card">
          <h2>Your role</h2>
          <p>{membership.role.replaceAll("_", " ")}</p>
        </section>
        <section className="access-card">
          <h2>Execution policy</h2>
          <p>
            Production writes remain disabled. Future actions require an exact
            reviewed plan.
          </p>
        </section>
      </div>
    </>
  );
}
