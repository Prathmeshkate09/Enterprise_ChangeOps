import Link from "next/link";
import { revokeInvitation } from "@/app/access-actions";
import { AccessForm } from "@/app/ui/access-form";
import { PageHeading } from "@/app/ui/workspace-shell";
import {
  accessRequest,
  requireAdmin,
  type AccessInvitation,
  type AccessPage,
} from "@/lib/enterprise-access";

export default async function InvitationsPage({
  searchParams,
}: {
  searchParams: Promise<{ after?: string }>;
}) {
  await requireAdmin();
  const { after = "" } = await searchParams;
  const data = await accessRequest<AccessPage<AccessInvitation>>(
    `/admin/invitations?after=${encodeURIComponent(after)}`,
  );
  return (
    <div className="access-lifecycle">
      <PageHeading
        eyebrow="Admission"
        title="Invitation history"
        description="Revoke a pending invitation to prevent its code from granting access. To change an existing member, use Organizations."
      />
      <p><Link href="/admin/users">Create an invitation</Link></p>
      {data.items.length === 0 && <p>No invitations yet.</p>}
      <div className="access-grid">
        {data.items.map((invitation) => {
          const status = invitation.status;
          return (
            <section className="access-card" key={invitation.record_id}>
              <h2>{invitation.email}</h2>
              <p><span className="access-pill">{status[0]!.toUpperCase() + status.slice(1)}</span></p>
              <p>Role: {invitation.role.replaceAll("_", " ")}</p>
              <p>Organization: {invitation.organization_id}</p>
              <p>Expires: <time dateTime={invitation.expires_at}>{invitation.expires_at}</time></p>
              {status === "pending" && (
                <AccessForm action={revokeInvitation} submit="Revoke invitation">
                  <input type="hidden" name="recordId" value={invitation.record_id} />
                  <input type="hidden" name="version" value={invitation.version} />
                </AccessForm>
              )}
            </section>
          );
        })}
      </div>
      {data.next_cursor && <Link href={`?after=${encodeURIComponent(data.next_cursor)}`}>Next page</Link>}
    </div>
  );
}
