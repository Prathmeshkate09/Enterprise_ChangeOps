import Link from "next/link";
import {
  accessRequest,
  requireAdmin,
  type AccessPage,
  type AccessUser,
} from "@/lib/enterprise-access";
import {
  createInvitation,
  setAccessStatus,
  setAdministrator,
} from "@/app/access-actions";
import { AccessForm } from "@/app/ui/access-form";
import { PageHeading } from "@/app/ui/workspace-shell";

export default async function UsersPage({
  searchParams,
}: {
  searchParams: Promise<{ after?: string }>;
}) {
  const current = await requireAdmin();
  const { after = "" } = await searchParams;
  const users = await accessRequest<AccessPage<AccessUser>>(
    `/admin/users?after=${encodeURIComponent(after)}`,
  );
  return (
    <>
      <PageHeading
        eyebrow="Central access control"
        title="Users & invitations"
        description="Only appointed platform administrators can admit users. Each invitation grants one role in one organization."
      />
      <div className="access-split">
        <section className="access-card">
          <h2>Admitted accounts</h2>
          <div className="access-table-wrap access-accounts-wrap">
            <table
              className="access-accounts-table"
              role="table"
              aria-label="Admitted accounts"
            >
              <thead role="rowgroup">
                <tr role="row">
                  <th scope="col" role="columnheader">
                    Account ID
                  </th>
                  <th scope="col" role="columnheader">
                    Status
                  </th>
                  <th scope="col" role="columnheader">
                    Access
                  </th>
                </tr>
              </thead>
              <tbody role="rowgroup">
                {users.items.map((user) => (
                  <tr key={user.record_id} role="row">
                    <td role="cell">
                      <span className="access-mobile-label" aria-hidden="true">
                        Account ID
                      </span>
                      <strong>{user.subject}</strong>
                      {current.owner && (
                        <small>
                          Record: {user.record_id} · Version: {user.version}
                        </small>
                      )}
                      <small>
                        {user.owner
                          ? "Platform owner"
                          : user.platform_admin
                            ? "Platform administrator"
                            : "Organization member"}
                      </small>
                    </td>
                    <td role="cell" className="access-account-status">
                      <span className="access-mobile-label" aria-hidden="true">
                        Status
                      </span>
                      {user.active ? "Active" : "Suspended"}
                    </td>
                    <td role="cell">
                      <span className="access-mobile-label" aria-hidden="true">
                        Access
                      </span>
                      {user.owner || user.subject === current.subject ? (
                        <span className="access-muted">Protected account</span>
                      ) : (
                        <AccessForm
                          action={setAccessStatus}
                          submit={user.active ? "Suspend" : "Reactivate"}
                        >
                          <input type="hidden" name="kind" value="users" />
                          <input
                            type="hidden"
                            name="recordId"
                            value={user.record_id}
                          />
                          <input
                            type="hidden"
                            name="version"
                            value={user.version}
                          />
                          <input
                            type="hidden"
                            name="active"
                            value={String(!user.active)}
                          />
                        </AccessForm>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {users.next_cursor && (
            <Link href={`?after=${users.next_cursor}`}>Next page →</Link>
          )}
        </section>
        <section className="access-card">
          <h2>Invite a member</h2>
          <AccessForm action={createInvitation} submit="Create invitation">
            <label>
              Verified email
              <input
                name="email"
                type="email"
                autoComplete="off"
                required
                maxLength={254}
              />
            </label>
            <label>
              Organization ID
              <input
                name="organizationId"
                required
                // HTML patterns use Unicode Sets; escape the literal hyphen.
                pattern={"[A-Za-z0-9][A-Za-z0-9_\\-]{0,127}"}
                maxLength={128}
                aria-describedby="organization-id-help"
                placeholder="Copy from Organizations"
              />
            </label>
            <p id="organization-id-help">
              Use 1–128 letters, numbers, underscores or hyphens. Start with a
              letter or number.
            </p>
            <label>
              Role
              <select name="role" defaultValue="auditor">
                <option value="auditor">Auditor · review access</option>
                <option value="requester">Requester · propose changes</option>
                <option value="approver">Approver · review plans</option>
                <option value="organization_admin">
                  Organization admin · manage workspace
                </option>
              </select>
            </label>
          </AccessForm>
          <p>
            Organization administrators cannot invite or activate other members.
          </p>
        </section>
      </div>
      {current.owner && (
        <section className="access-card">
          <h2>Appoint an admission administrator</h2>
          <p>
            This grants platform admission authority, not additional tenant
            access. The account must already be admitted and active. MFA is
            required.
          </p>
          <AccessForm
            action={setAdministrator}
            submit="Update administrator access"
          >
            <label>
              Account record ID
              <input name="recordId" required maxLength={128} />
            </label>
            <label>
              Current record version
              <input name="version" type="number" min={1} required />
            </label>
            <label>
              Authority
              <select name="active">
                <option value="true">Appoint administrator</option>
                <option value="false">Revoke administrator</option>
              </select>
            </label>
          </AccessForm>
        </section>
      )}
    </>
  );
}
