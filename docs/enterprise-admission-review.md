# E0/E1 admission foundation: review and rollout notes

Status: local implementation and fixture review, **not a completed enterprise release**.
This guide covers the implemented admission foundation, local review steps and remaining
release gates. Internal planning and session checkpoints are maintained separately.

## What Prathmesh can review now

The isolated preview uses synthetic accounts, memory persistence and no cloud credentials.
Its fixture switch routes exist only in `services/control-api/tests/manual_admission_preview.py`,
never in the deployed application factory. It binds only `127.0.0.1` and resets on restart.
Do not enter customer data or use this harness for a pilot/deployment.

While the preview processes are running:

- [Owner preview](http://127.0.0.1:8011/__fixture/owner): platform administration.
- [Organization-admin preview](http://127.0.0.1:8011/__fixture/member): Alice's workspace.
- [Unapproved-account preview](http://127.0.0.1:8011/__fixture/pending): Bob, initially no workspace.
- [Real login screen, unconfigured](http://127.0.0.1:3011/login): no fake Google sign-in button.

Switching a fixture replaces the preview cookie in that browser. Use only this local
preview, not another ChangeOps instance on the same loopback hostname. The fixture
owner simulates MFA; this does **not** verify Google login, MFA or session revocation.

### Restart the preview if needed

Run from the nested repository root in two PowerShell terminals. Dependencies must
already be installed with the repository's normal setup task. No `.env` edits are needed.

Terminal 1:

```powershell
.venv\Scripts\python.exe services/control-api/tests/manual_admission_preview.py
```

Terminal 2:

```powershell
$env:ENTERPRISE_ACCESS_ENABLED='true'
$env:CONTROL_TOWER_ORIGIN='http://127.0.0.1:3011'
$env:CONTROL_API_BASE_URL='http://127.0.0.1:8011'
$env:SERVICE_AUTH_MODE='none'
node node_modules/next/dist/bin/next dev apps/control-tower --hostname 127.0.0.1 --port 3011
```

Stop each preview terminal with Ctrl+C. This does not stop existing Docker services.

### Hands-on acceptance checklist

Record expected/actual results and feedback below; do not paste invitation codes,
session cookies, real emails or credentials into the repository/context log.

| Check | Expected | Owner review |
| --- | --- | --- |
| Open the owner preview | Admin console available; no automatic customer workspace | Pending |
| Create a second organization | Appears in the list, but has no members or connections | Pending |
| Invite `bob@example.test` to the second organization as auditor | Single-use code shown once; expires after 24 hours | Pending |
| Switch to the unapproved preview before redemption | No active workspace; no admin console | Pending |
| Redeem Bob's code | Only his invited organization appears | Pending |
| Redeem the same code again | Rejected; no role or membership change | Pending |
| Try Bob's invitation as Alice | Rejected without activating access | Pending |
| Open `/admin/users` as Alice | Redirect to access status; backend admin calls denied | Pending |
| Open the other organization's URL as Alice | No access to that organization | Pending |
| Suspend Alice or her organization as owner, then refresh Alice's view | Access removed without waiting for cookie expiry | Pending |
| Open Organizations > Manage members; change Alice's role and suspend her membership | Updated role persists; only that organization's access is suspended | Pending |
| Reactivate that membership | Access returns with its current role, provided account and organization are active | Pending |
| Save an older member form from a second tab | Conflict shown; newer membership is preserved | Pending |
| Create a new invitation, open Invitation history and revoke it | Status becomes Revoked; redemption fails; an audit event is present | Pending |
| Appoint an admitted account as platform administrator | Only owner can do this; no admin access without MFA | Pending |
| Inspect Access audit | Positive actions and rejected API access; no invitation/session plaintext | Pending |
| Review desktop and narrow/mobile screens | Readable content, visible focus, usable forms/tables | Pending |

Roles for requesting and approving changes are recorded, but their workflow routes are
not enabled yet. This slice cannot pass E1's end-to-end two-person workflow approval
gate until those routes propagate verified actor/membership to the workflow and tool gateway.

## Implemented data and trust boundaries

The identity provider verifies issuer/audience/signature through the Google Admin SDK,
verified email and revoked sessions. A provider account alone does not admit a user.
Administrator access additionally requires a verified second-factor claim. Session
creation requires recent authentication. Browser cookies are HttpOnly, SameSite Strict
and Secure in production; same-origin checks protect session creation and server actions.
Frontend service IAM uses a separate `X-Serverless-Authorization` header from the user's
session bearer. Production origins and enterprise API transport must use HTTPS.

These choices follow [Google's server-session guidance](https://firebase.google.com/docs/auth/admin/manage-cookies).
Provider account/sign-in restrictions using [Identity Platform blocking functions](https://docs.cloud.google.com/identity-platform/docs/blocking-functions)
remain an additional deployment task; per-request backend membership is mandatory regardless.

### Access record layout (implemented, version 1)

| Collection/path | Contents and policy |
| --- | --- |
| `admission_metadata/bootstrap` | Singleton owner reference and schema version; explicit bootstrap only |
| `admission_users/{sha256(subject)}` | Active status, owner/admin flags, organization IDs, optimistic version |
| `admission_organizations/{orgId}` | Name, active status, version |
| `admission_organizations/{orgId}/members/{sha256(subject)}` | Verified subject, exact organization, role, active status, version |
| `admission_invitations/{sha256(random_token)}` | Intended email, organization, role, inviter, expiry, redemption subject, revoked flag and optimistic version; no plaintext token |
| `admission_audit/{eventId}` | Actor identifier, action, resource identifier and timestamp; no raw request body |

Firestore transactions commit admission changes and their audit together; redemption
rechecks inviter/org/user status inside the transaction. Lists use bounded document-ID
pagination. Audit lists are **not** guaranteed timestamp order yet. Invitation email is
personal data still requiring a deployment retention/deletion policy. Hashing a subject
or token does not anonymize other stored identity data.

### Invitation and membership lifecycle

Only an active platform admission administrator with MFA may list/revoke invitations or
list/change organization memberships. Organization administrators cannot do either.
Admins cannot change their own membership; another admission administrator must do it.
An update addresses an existing membership and cannot create access. Account/organization
suspension takes precedence over membership activation. Invitation redemption cannot
overwrite a suspended or existing membership. Suspension takes effect on the next
authorized request; enterprise workflow execution is still disabled in this slice.

- `GET /v1/access/admin/invitations`: bounded history with server-computed status.
- `POST /v1/access/admin/invitations/{recordId}/revoke`: requires `expected_version`.
- `GET /v1/access/admin/organizations/{orgId}/members`: bounded organization membership list.
- `PATCH /v1/access/admin/organizations/{orgId}/members/{recordId}`: requires `role`,
  `active` and `expected_version`.

Use the opaque `record_id` returned by each list, never a plaintext invitation code.
Revoke and redeem transact against the same invitation document. A stale version,
revoked/redeemed invitation or expired invitation produces a conflict for revocation.
Positive mutations and their audit commit together. Validation rejections are audited
with a fixed reason only; submitted values and attacker-controlled field names are not
returned or recorded. Audit storage failure fails the request.

Existing invitation documents load with `revoked=false` and `version=1`; the next write
persists those fields. This requires no bulk rewrite or new query index locally. It is
not a live Firestore migration verification. Deploy admission API readers/writers as one
compatible revision before enabling this UI. The previous strict model rejects documents
containing the new fields: do not roll back to that binary after lifecycle writes without
a reviewed compatibility release. Never remove revocation state to make a downgrade work.

### Threats and current controls

| Threat | Current control / remaining gate |
| --- | --- |
| Self-signup or organization-admin self-admission | No membership creation outside central invitation redemption; owner alone appoints platform administrators |
| Forged role/tenant header | Enterprise mode does not mount legacy demo/header-authorized APIs; membership required server-side |
| Wrong recipient or invitation replay | Email binding, random 256-bit token, hashed storage, expiry and transactional single redemption |
| Suspended access with an old cookie | User and organization status re-read on each authorized request |
| Cross-site login/mutation | Exact origin checks; SameSite/HttpOnly cookie; bounded login body |
| Partial mutation without audit | Atomic Firestore writes; storage failures are not successful responses |
| Privileged identity compromise | MFA claim required, revocation checks; real MFA recovery/step-up and provider tests still open |
| Direct database/service access | Deployment IAM, no browser database access and no public backend must be verified before rollout |
| Identity/admission abuse and audit flooding | Frontend/edge limits and provider blocking hooks still required before external users |
| Legacy sandbox endpoints | Excluded in enterprise API mode; old deployment remains private and unchanged |

## Next release work, in order

1. Complete managed persistence acceptance for the implemented invitation/member lifecycle;
   finish privilege step-up, abuse limits, retention and audit navigation.
2. Prepare the Identity Platform/provider/MFA setup and access-store deployment change
   packet. Obtain explicit owner authority before cloud API enablement, IAM or deployment.
   Confirm the exact owner UID out of band; never choose the first signed-in user as owner.
3. Review the one-time `scripts/bootstrap_enterprise_owner.py` operation against an
   approved existing verified provider account. It writes a durable owner singleton and
   audit; it is not a user-registration endpoint. It has not been run against cloud data.
4. Test real invited and uninvited accounts, wrong project/issuer, MFA, revocation,
   two-organization isolation and outage behavior in the private managed test environment.
5. Complete E1 connector contracts and user R1 review; then E2 read-only GitHub onboarding
   for owner-approved test repositories. Do not repoint sandbox connectors at real systems.

Before any public beta: provider hooks and abuse limits, least-privilege IAM, direct
Firestore client denial, schema/bootstrap controls, backup/restore, retention/deletion,
monitoring, approved resource scope and owner acceptance must all have evidence.
