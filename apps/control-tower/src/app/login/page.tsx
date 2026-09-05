import { publicAuthConfig } from "@/lib/enterprise-access";
import { LoginForm } from "@/app/ui/login-form";

export const dynamic = "force-dynamic";

export default function LoginPage() {
  return (
    <main className="access-root access-login">
      <section className="access-login-story">
        <div className="workspace-brand">
          <span className="workspace-mark">C</span>
          <span>
            ChangeOps<small>Enterprise operations</small>
          </span>
        </div>
        <div>
          <p className="access-eyebrow">Change with confidence</p>
          <h1>
            Every change.
            <br />
            Under control.
          </h1>
          <p>
            Connect your systems, understand the impact, and put every decision
            in the right hands.
          </p>
        </div>
        <div className="access-login-principles">
          <span>Scoped access</span>
          <span>Human approval</span>
          <span>Traceable decisions</span>
        </div>
      </section>
      <section className="access-login-panel">
        <div className="access-login-card">
          <span className="access-pill">Private workspace</span>
          <h2>Welcome back</h2>
          <p>
            Sign in with the account invited by your platform administrator.
          </p>
          <LoginForm config={publicAuthConfig()} />
          <div className="access-login-note">
            <strong>Access is granted personally.</strong>
            <p>
              Signing in does not create an organization or grant access. If you
              need an invitation, contact your platform administrator.
            </p>
          </div>
        </div>
        <small className="access-footer">
          Enterprise ChangeOps · Governed operations
        </small>
      </section>
    </main>
  );
}
