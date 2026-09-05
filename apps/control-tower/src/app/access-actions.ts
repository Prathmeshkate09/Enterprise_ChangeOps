"use server";

import { cookies, headers } from "next/headers";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import {
  accessErrorMessage,
  accessRequest,
  requireAccess,
  requireAdmin,
  SESSION_COOKIE,
  trustedApplicationOrigin,
} from "@/lib/enterprise-access";

export type FormResult = { message: string; token?: string; ok?: boolean };

async function checkOrigin() {
  const origin = (await headers()).get("origin");
  const expected = trustedApplicationOrigin();
  if (!expected || origin !== expected)
    throw new Error("Request origin rejected.");
}

function field(form: FormData, name: string): string {
  const value = form.get(name);
  return typeof value === "string" ? value.trim() : "";
}

export async function createOrganization(
  _state: FormResult,
  form: FormData,
): Promise<FormResult> {
  await checkOrigin();
  await requireAdmin();
  try {
    await accessRequest("/admin/organizations", {
      method: "POST",
      body: { name: field(form, "name") },
    });
    revalidatePath("/admin/organizations");
    return {
      message: "Organization created. Invite its users to grant access.",
      ok: true,
    };
  } catch (error) {
    return { message: accessErrorMessage(error) };
  }
}

export async function createInvitation(
  _state: FormResult,
  form: FormData,
): Promise<FormResult> {
  await checkOrigin();
  await requireAdmin();
  try {
    const result = await accessRequest<{ token: string }>(
      "/admin/invitations",
      {
        method: "POST",
        body: {
          email: field(form, "email"),
          organization_id: field(form, "organizationId"),
          role: field(form, "role"),
        },
      },
    );
    return {
      message:
        "Invitation created. Share this single-use code securely with the intended recipient. It expires in 24 hours.",
      token: result.token,
      ok: true,
    };
  } catch (error) {
    return { message: accessErrorMessage(error) };
  }
}

export async function redeemInvitation(
  _state: FormResult,
  form: FormData,
): Promise<FormResult> {
  await checkOrigin();
  await requireAccess();
  try {
    await accessRequest("/invitations/redeem", {
      method: "POST",
      body: { token: field(form, "token") },
    });
  } catch (error) {
    return { message: accessErrorMessage(error) };
  }
  redirect("/access-status");
}

export async function setAccessStatus(
  _state: FormResult,
  form: FormData,
): Promise<FormResult> {
  await checkOrigin();
  await requireAdmin();
  const kind = field(form, "kind");
  if (kind !== "users" && kind !== "organizations")
    return { message: "Invalid record type." };
  try {
    await accessRequest(
      `/admin/${kind}/${encodeURIComponent(field(form, "recordId"))}`,
      {
        method: "PATCH",
        body: {
          active: field(form, "active") === "true",
          expected_version: Number(field(form, "version")),
        },
      },
    );
    revalidatePath(`/admin/${kind}`);
    return { message: "Access status updated.", ok: true };
  } catch (error) {
    return { message: accessErrorMessage(error) };
  }
}

export async function logout() {
  await checkOrigin();
  // Revocation must succeed before declaring a completed sign-out.
  await accessRequest("/logout", { method: "POST" });
  (await cookies()).delete(SESSION_COOKIE);
  redirect("/login");
}

export async function setAdministrator(
  _state: FormResult,
  form: FormData,
): Promise<FormResult> {
  await checkOrigin();
  if (!(await requireAdmin()).owner)
    return { message: "Only the platform owner can appoint administrators." };
  try {
    await accessRequest(
      `/admin/administrators/${encodeURIComponent(field(form, "recordId"))}`,
      {
        method: "PATCH",
        body: {
          active: field(form, "active") === "true",
          expected_version: Number(field(form, "version")),
        },
      },
    );
    revalidatePath("/admin/users");
    return {
      message:
        "Administrator access updated. MFA is required for privileged access.",
      ok: true,
    };
  } catch (error) {
    return { message: accessErrorMessage(error) };
  }
}
