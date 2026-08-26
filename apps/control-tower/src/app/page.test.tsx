import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import HomePage from "./page";

describe("Control Tower durable control API", () => {
  it("shows the sandbox boundary without fabricated metrics", () => {
    render(<HomePage />);

    expect(screen.getByRole("heading", { level: 1, name: "Enterprise ChangeOps" })).toBeVisible();
    expect(screen.getByLabelText("Sandbox environment")).toBeVisible();
    expect(screen.getByText("Production writes remain disabled.")).toBeVisible();
    expect(screen.getByText(/metrics will appear only after measured workflow execution/i)).toBeVisible();
    expect(screen.getByText("Last-Event-ID stream recovery")).toBeVisible();
  });
});
