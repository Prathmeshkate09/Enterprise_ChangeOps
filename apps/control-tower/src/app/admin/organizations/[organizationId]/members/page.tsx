import Link from "next/link";
import { updateMembership } from "@/app/access-actions";
import { AccessForm } from "@/app/ui/access-form";
import { PageHeading } from "@/app/ui/workspace-shell";
import {
  accessRequest,
  requireAdmin,
  type AccessMembership,
  type AccessPage,
} from "@/lib/enterprise-access";

export default async function MembersPage({
  params,
  searchParams,
}: {
  params: Promise<{ organizationId: string }>;
  searchParams: Promise<{ after?: string }>;
}) {
  const current = await requireAdmin();
  const { organizationId } = await params;
  const { after = "" } = await searchParams;
  const data = await accessRequest<AccessPage<AccessMembership>>(
    `/admin/organizations/${encodeURIComponent(organizationId)}/members?after=${encodeURIComponent(after)}`,
  );
  return (
    <div className="access-lifecycle">
      <PageHeading
        eyebrow="Admission"
        title="Organization members"
        description="Change a member's role or suspend access to this organization. Membership in other organizations stays active."
      />
      <p>{organizationId}</p>
      <p><Link href="/admin/organizations">Back to organizations</Link></p>
      <p>A suspended account or organization must be reactivated before a membership can be activated.</p>
      {data.items.length === 0 && <p>No members yet. Create an invitation from Users &amp; invitations.</p>}
      <div className="access-grid">
        {data.items.map((member) => (
          <section className="access-card" key={member.record_id}>
            <h2>{member.subject}</h2>
            <p><span className="access-pill">{member.active ? "Active membership" : "Suspended membership"}</span></p>
            {member.subject === current.subject ? (
              <p>Your membership is protected. Another admission administrator must change it.</p>
            ) : (
              <AccessForm key={member.version} action={updateMembership} submit="Save membership">
                <input type="hidden" name="organizationId" value={organizationId} />
                <input type="hidden" name="recordId" value={member.record_id} />
                <input type="hidden" name="version" value={member.version} />
                <label>
                  Role
                  <select name="role" defaultValue={member.role}>
                    <option value="auditor">Auditor</option>
                    <option value="requester">Requester</option>
                    <option value="approver">Approver</option>
                    <option value="organization_admin">Organization admin</option>
                  </select>
                </label>
                <label>
                  Membership status
                  <select name="active" defaultValue={String(member.active)}>
                    <option value="true">Active</option>
                    <option value="false">Suspended</option>
                  </select>
                </label>
              </AccessForm>
            )}
          </section>
        ))}
      </div>
      {data.next_cursor && <Link href={`?after=${encodeURIComponent(data.next_cursor)}`}>Next page</Link>}
    </div>
  );
}
