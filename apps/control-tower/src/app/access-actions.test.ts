import { beforeEach, describe, expect, it, vi } from "vitest";
import { revokeInvitation, updateMembership } from "./access-actions";
import { accessRequest, requireAdmin, AccessError } from "@/lib/enterprise-access";
import { revalidatePath } from "next/cache";

const requestHeaders = vi.hoisted(() => ({ origin: "http://127.0.0.1:3011" }));
vi.mock("next/headers", () => ({
  headers: async () => new Headers({ origin: requestHeaders.origin }),
  cookies: vi.fn(),
}));
vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));
vi.mock("@/lib/enterprise-access", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/enterprise-access")>(),
  trustedApplicationOrigin: () => "http://127.0.0.1:3011",
  requireAdmin: vi.fn(),
  accessRequest: vi.fn(),
}));

function membershipForm() {
  const form = new FormData();
  for (const [key, value] of Object.entries({
    organizationId: "org_one", recordId: "member-record", version: "3", role: "approver", active: "false",
  })) form.set(key, value);
  return form;
}

beforeEach(() => {
  vi.resetAllMocks();
  requestHeaders.origin = "http://127.0.0.1:3011";
});

describe("admission lifecycle actions", () => {
  it("sends the exact organization, member and version then revalidates", async () => {
    expect(await updateMembership({ message: "" }, membershipForm())).toMatchObject({ ok: true });
    expect(accessRequest).toHaveBeenCalledWith("/admin/organizations/org_one/members/member-record", {
      method: "PATCH", body: { role: "approver", active: false, expected_version: 3 },
    });
    expect(requireAdmin).toHaveBeenCalledOnce();
    expect(revalidatePath).toHaveBeenCalledWith("/admin/organizations/org_one/members");
  });

  it("rejects a foreign origin before authorization or mutation", async () => {
    requestHeaders.origin = "https://untrusted.example";
    await expect(updateMembership({ message: "" }, membershipForm())).rejects.toThrow("origin rejected");
    await expect(revokeInvitation({ message: "" }, membershipForm())).rejects.toThrow("origin rejected");
    expect(accessRequest).not.toHaveBeenCalled();
    expect(requireAdmin).not.toHaveBeenCalled();
  });

  it("requires admission authorization and validates the status", async () => {
    vi.mocked(requireAdmin).mockRejectedValueOnce(new Error("not an administrator"));
    await expect(updateMembership({ message: "" }, membershipForm())).rejects.toThrow("administrator");
    expect(accessRequest).not.toHaveBeenCalled();
    const invalid = membershipForm();
    invalid.set("active", "anything");
    expect(await updateMembership({ message: "" }, invalid)).not.toHaveProperty("ok");
    expect(accessRequest).not.toHaveBeenCalled();
  });

  it("shows a stale-write conflict without declaring success", async () => {
    vi.mocked(accessRequest).mockRejectedValueOnce(new AccessError(409));
    const result = await updateMembership({ message: "" }, membershipForm());
    expect(result.ok).toBeUndefined();
    expect(result.message).toMatch(/Refresh/);
    expect(revalidatePath).not.toHaveBeenCalled();
  });

  it("revokes by record and expected version; reports a persistence outage", async () => {
    expect(await revokeInvitation({ message: "" }, membershipForm())).toMatchObject({ ok: true });
    expect(accessRequest).toHaveBeenCalledWith("/admin/invitations/member-record/revoke", {
      method: "POST", body: { expected_version: 3 },
    });
    vi.mocked(accessRequest).mockRejectedValueOnce(new AccessError(503));
    const result = await revokeInvitation({ message: "" }, membershipForm());
    expect(result.ok).toBeUndefined();
    expect(result.message).toMatch(/No success/);
  });
});
