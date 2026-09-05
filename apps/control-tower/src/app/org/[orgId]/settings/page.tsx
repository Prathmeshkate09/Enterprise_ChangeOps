import { requireWorkspace } from "@/lib/enterprise-access";
import { PageHeading } from "@/app/ui/workspace-shell";

export default async function OrganizationSettings({
  params,
}: {
  params: Promise<{ orgId: string }>;
}) {
  const { orgId } = await params;
  const { organization, membership } = await requireWorkspace(orgId);
  return (
    <>
      <PageHeading
        eyebrow="Workspace settings"
        title="Access & boundaries"
        description="Your platform administrator manages admission. Connecting a company system requires separate permission from its owner."
      />
      <section className="access-card">
        <dl className="access-details">
          <div>
            <dt>Organization</dt>
            <dd>{organization.name}</dd>
          </div>
          <div>
            <dt>Organization ID</dt>
            <dd>{organization.organization_id}</dd>
          </div>
          <div>
            <dt>Your role</dt>
            <dd>{membership.role.replaceAll("_", " ")}</dd>
          </div>
          <div>
            <dt>Membership</dt>
            <dd>{membership.active ? "Active" : "Suspended"}</dd>
          </div>
        </dl>
      </section>
      <section className="access-card">
        <h2>Need to add someone?</h2>
        <p>
          Contact the platform administrator. Organization roles do not grant
          permission to invite or activate accounts.
        </p>
      </section>
    </>
  );
}
