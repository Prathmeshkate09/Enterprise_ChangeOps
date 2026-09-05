import Link from "next/link";
import {
  accessRequest,
  requireAdmin,
  type AccessPage,
  type AccessAudit,
} from "@/lib/enterprise-access";
import { PageHeading } from "@/app/ui/workspace-shell";

export default async function AccessAuditPage({
  searchParams,
}: {
  searchParams: Promise<{ after?: string }>;
}) {
  await requireAdmin();
  const { after = "" } = await searchParams;
  const audit = await accessRequest<AccessPage<AccessAudit>>(
    `/admin/audit?after=${encodeURIComponent(after)}`,
  );
  return (
    <>
      <PageHeading
        eyebrow="Accountability"
        title="Access audit"
        description="Admission events are committed with their corresponding access changes. Invitation codes and credentials are never included."
      />
      <section className="access-card">
        <div className="access-table-wrap">
          <table>
            <thead>
              <tr>
                <th>Action</th>
                <th>Actor</th>
                <th>Resource</th>
                <th>Time (UTC)</th>
              </tr>
            </thead>
            <tbody>
              {audit.items.map((event) => (
                <tr key={event.event_id}>
                  <td>{event.action.replaceAll("_", " ")}</td>
                  <td>{event.actor}</td>
                  <td>{event.resource_id}</td>
                  <td>{event.occurred_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {audit.next_cursor && (
          <Link href={`?after=${audit.next_cursor}`}>Next page →</Link>
        )}
      </section>
    </>
  );
}
