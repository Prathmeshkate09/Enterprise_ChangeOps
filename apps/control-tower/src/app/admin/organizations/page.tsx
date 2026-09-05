import Link from "next/link";
import {
  accessRequest,
  requireAdmin,
  type AccessPage,
  type Organization,
} from "@/lib/enterprise-access";
import { createOrganization, setAccessStatus } from "@/app/access-actions";
import { AccessForm } from "@/app/ui/access-form";
import { PageHeading } from "@/app/ui/workspace-shell";

export default async function OrganizationsPage({
  searchParams,
}: {
  searchParams: Promise<{ after?: string }>;
}) {
  await requireAdmin();
  const { after = "" } = await searchParams;
  const data = await accessRequest<AccessPage<Organization>>(
    `/admin/organizations?after=${encodeURIComponent(after)}`,
  );
  return (
    <>
      <PageHeading
        eyebrow="Admission"
        title="Organizations"
        description="Create a workspace and decide whether it remains active. Suspending an organization removes access for all its members."
      />
      <div className="access-split">
        <section className="access-card">
          <h2>Approved organizations</h2>
          {data.items.length === 0 ? (
            <p>No organizations yet. Create the first workspace to begin.</p>
          ) : (
            <div className="access-table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Organization</th>
                    <th>Status</th>
                    <th>Access</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((org) => (
                    <tr key={org.organization_id}>
                      <td>
                        <strong>{org.name}</strong>
                        <small>{org.organization_id}</small>
                      </td>
                      <td>
                        <span className="access-pill">
                          {org.active ? "Active" : "Suspended"}
                        </span>
                      </td>
                      <td>
                        <AccessForm
                          action={setAccessStatus}
                          submit={org.active ? "Suspend" : "Reactivate"}
                        >
                          <input
                            type="hidden"
                            name="kind"
                            value="organizations"
                          />
                          <input
                            type="hidden"
                            name="recordId"
                            value={org.organization_id}
                          />
                          <input
                            type="hidden"
                            name="version"
                            value={org.version}
                          />
                          <input
                            type="hidden"
                            name="active"
                            value={String(!org.active)}
                          />
                        </AccessForm>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {data.next_cursor && (
            <Link href={`?after=${data.next_cursor}`}>Next page →</Link>
          )}
        </section>
        <section className="access-card">
          <h2>Create organization</h2>
          <AccessForm action={createOrganization} submit="Create workspace">
            <label>
              Organization name
              <input
                name="name"
                minLength={2}
                maxLength={120}
                required
                placeholder="Acme Operations"
              />
            </label>
          </AccessForm>
          <p>
            Creating a workspace does not grant users access or connect any
            external system.
          </p>
        </section>
      </div>
    </>
  );
}
