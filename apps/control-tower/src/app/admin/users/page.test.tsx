import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import UsersPage from "./page";

vi.mock("@/lib/enterprise-access", () => ({
  requireAdmin: async () => ({ owner: true, subject: "owner" }),
  accessRequest: async () => ({
    items: [
      { subject: "owner", record_id: "owner-record", version: 1, owner: true, active: true },
      { subject: "member", record_id: "member-record", version: 2, active: true },
      { subject: "inactive-member", record_id: "inactive-record", version: 3, active: false },
    ],
    next_cursor: null,
  }),
}));

vi.mock("@/app/access-actions", () => ({
  createInvitation: vi.fn(),
  setAccessStatus: vi.fn(),
  setAdministrator: vi.fn(),
  logout: vi.fn(),
}));

afterEach(cleanup);

describe("admission users page", () => {
  it("renders a Unicode Sets compatible identifier constraint aligned with the API", async () => {
    render(await UsersPage({ searchParams: Promise.resolve({}) }));
    const input = screen.getByRole("textbox", { name: "Organization ID" }) as HTMLInputElement;
    const pattern = new RegExp(`^(?:${input.pattern})$`, "v");
    expect(input).toBeRequired();
    expect(input.maxLength).toBe(128);
    expect(input).toHaveAccessibleDescription(/Start with a letter or number/);
    for (const value of ["a", "0", "org_example-2", "a".repeat(128)]) {
      expect(pattern.test(value)).toBe(true);
      fireEvent.change(input, { target: { value } });
      expect(input.checkValidity()).toBe(true);
    }
    for (const value of ["", "invalid/id!", "-org", "_org", "has space", "é", "a".repeat(129)]) {
      expect(pattern.test(value)).toBe(false);
      fireEvent.change(input, { target: { value } });
      expect(input.checkValidity()).toBe(false);
    }
  });

  it("keeps labeled table semantics and a single correctly bound action per account", async () => {
    render(await UsersPage({ searchParams: Promise.resolve({}) }));
    const table = screen.getByRole("table", { name: "Admitted accounts" });
    expect(within(table).getAllByRole("columnheader")).toHaveLength(3);
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(4);
    expect(within(rows[1]!).queryByRole("button")).not.toBeInTheDocument();
    for (const [index, label, record, version, active] of [
      [2, "Suspend", "member-record", "2", "false"],
      [3, "Reactivate", "inactive-record", "3", "true"],
    ] as const) {
      const row = rows[index]!;
      expect(within(row).getAllByRole("cell")).toHaveLength(3);
      const form = within(row).getByRole("button", { name: label }).closest("form")!;
      expect(new FormData(form).get("recordId")).toBe(record);
      expect(new FormData(form).get("version")).toBe(version);
      expect(new FormData(form).get("active")).toBe(active);
      expect(row.querySelectorAll(".access-mobile-label")).toHaveLength(3);
    }
  });
});
