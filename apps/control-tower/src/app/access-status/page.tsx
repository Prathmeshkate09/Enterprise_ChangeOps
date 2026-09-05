import Link from "next/link";
import { requireAccess } from "@/lib/enterprise-access";
import { PageHeading } from "@/app/ui/workspace-shell";
import { logout } from "@/app/access-actions";

export const dynamic = "force-dynamic";

export default async function AccessStatusPage() {
  const access = await requireAccess();
  return (
    <main className="access-root access-standalone">
      <PageHeading
        eyebrow="Your access"
        title="Choose your workspace"
        description={`Signed in as ${access.email}. Only approved workspaces appear here.`}
      />
      {access.status === "mfa_required" && (
        <p className="access-notice">
          Administrator access requires multi-factor authentication. Complete
          authenticator enrollment in Identity Platform, then sign in again.
        </p>
      )}
      {access.status === "suspended" && (
        <p className="access-notice">
          Your access is suspended. Contact the platform administrator.
        </p>
      )}
      <div className="access-grid">
        {access.platform_admin && (
          <Link className="access-card" href="/admin">
            <span className="access-eyebrow">Platform</span>
            <h2>Administration</h2>
            <p>Manage organizations, invitations and access.</p>
            <strong>Open console →</strong>
          </Link>
        )}
        {access.workspaces.map(({ organization, membership }) => (
          <Link
            className="access-card"
            key={organization.organization_id}
            href={`/org/${organization.organization_id}/overview`}
          >
            <span className="access-eyebrow">
              {membership.role.replaceAll("_", " ")}
            </span>
            <h2>{organization.name}</h2>
            <p>Your organization workspace.</p>
            <strong>Open workspace →</strong>
          </Link>
        ))}
      </div>
      {!access.platform_admin && access.workspaces.length === 0 && (
        <section className="access-card">
          <h2>No active workspace</h2>
          <p>
            An administrator must approve your access before you can use
            enterprise features.
          </p>
        </section>
      )}
      <div className="access-inline">
        <Link href="/accept-invite" className="access-button">
          Redeem invitation
        </Link>
        <form action={logout}>
          <button className="access-text-button">Sign out</button>
        </form>
      </div>
    </main>
  );
}
