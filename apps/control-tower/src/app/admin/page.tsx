import Link from "next/link";
import { requireAdmin } from "@/lib/enterprise-access";
import { PageHeading } from "@/app/ui/workspace-shell";

export default async function AdminPage() {
  await requireAdmin();
  return (
    <>
      <PageHeading
        eyebrow="Platform overview"
        title="The right access. The right people."
        description="Control who can enter ChangeOps. Organization access and customer data permissions remain separate."
      />
      <div className="access-grid">
        <Link href="/admin/organizations" className="access-card">
          <span className="access-step">01</span>
          <h2>Create an organization</h2>
          <p>Establish an approved workspace before inviting its team.</p>
          <strong>Manage organizations →</strong>
        </Link>
        <Link href="/admin/users" className="access-card">
          <span className="access-step">02</span>
          <h2>Invite the right people</h2>
          <p>
            Grant a specific role to a verified individual. There is no
            automatic admission.
          </p>
          <strong>Manage invitations →</strong>
        </Link>
        <Link href="/admin/audit" className="access-card">
          <span className="access-step">03</span>
          <h2>Review access decisions</h2>
          <p>
            See when access was granted or suspended, and who made the decision.
          </p>
          <strong>View access audit →</strong>
        </Link>
      </div>
      <section className="access-card access-callout">
        <h2>Customer information stays in its workspace</h2>
        <p>
          Platform administration does not grant access to an organization’s
          workflow content. A separate membership is required.
        </p>
      </section>
    </>
  );
}
