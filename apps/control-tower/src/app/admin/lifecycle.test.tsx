import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import InvitationsPage from "./invitations/page";
import MembersPage from "./organizations/[organizationId]/members/page";
import { accessRequest } from "@/lib/enterprise-access";

vi.mock("@/lib/enterprise-access", () => ({
  requireAdmin: async () => ({ subject: "owner", owner: true }),
  accessRequest: vi.fn(),
}));
vi.mock("@/app/access-actions", () => ({
  revokeInvitation: vi.fn(), updateMembership: vi.fn(), logout: vi.fn(),
}));
afterEach(() => { cleanup(); vi.clearAllMocks(); });

it("allows revocation only for pending invitations and binds the current version", async () => {
  vi.mocked(accessRequest).mockResolvedValue({
    next_cursor: null,
    items: ["Pending", "Revoked", "Redeemed", "Expired"].map((status, index) => ({
      status: status.toLowerCase(),
      email: `${status.toLowerCase()}@example.test`, record_id: `record-${index}`,
      invitation_id: `invite_${index}`, organization_id: "org_one", role: "auditor",
      expires_at: status === "Expired" ? "2000-01-01T00:00:00Z" : "2099-01-01T00:00:00Z",
      revoked: status === "Revoked", redeemed_by: status === "Redeemed" ? "alice" : null, version: 4,
    })),
  });
  render(await InvitationsPage({ searchParams: Promise.resolve({}) }));
  for (const status of ["Pending", "Revoked", "Redeemed", "Expired"]) expect(screen.getByText(status)).toBeVisible();
  const buttons = screen.getAllByRole("button", { name: "Revoke invitation" });
  expect(buttons).toHaveLength(1);
  const data = new FormData(buttons[0]!.closest("form")!);
  expect(data.get("recordId")).toBe("record-0");
  expect(data.get("version")).toBe("4");
});

it("binds member changes to the organization and protects the administrator's own membership", async () => {
  vi.mocked(accessRequest).mockResolvedValue({
    next_cursor: null,
    items: ["owner", "alice"].map((subject) => ({
      subject, record_id: `${subject}-record`, organization_id: "org_one", role: "auditor", active: false, version: 2,
    })),
  });
  render(await MembersPage({ params: Promise.resolve({ organizationId: "org_one" }), searchParams: Promise.resolve({}) }));
  expect(screen.getByText(/Your membership is protected/)).toBeVisible();
  const buttons = screen.getAllByRole("button", { name: "Save membership" });
  expect(buttons).toHaveLength(1);
  const form = new FormData(buttons[0]!.closest("form")!);
  expect(Object.fromEntries(form)).toEqual({
    organizationId: "org_one", recordId: "alice-record", version: "2", role: "auditor", active: "false",
  });
});
