import Link from "next/link";
import { requireAccess } from "@/lib/enterprise-access";
import { redeemInvitation } from "@/app/access-actions";
import { AccessForm } from "@/app/ui/access-form";
import { PageHeading } from "@/app/ui/workspace-shell";

export const dynamic = "force-dynamic";

export default async function AcceptInvitationPage() {
  const access = await requireAccess();
  return (
    <main className="access-root access-standalone">
      <Link href="/access-status">← Your workspaces</Link>
      <PageHeading
        eyebrow="Invitation"
        title="Your next workspace"
        description={`An invitation can only be used by its intended recipient. You are signed in as ${access.email}.`}
      />
      <section className="access-card">
        <AccessForm action={redeemInvitation} submit="Accept invitation">
          <label>
            Invitation code
            <input
              name="token"
              required
              minLength={40}
              maxLength={128}
              autoComplete="off"
              spellCheck={false}
            />
          </label>
        </AccessForm>
        <p>Codes expire after 24 hours and can be redeemed once.</p>
      </section>
    </main>
  );
}
