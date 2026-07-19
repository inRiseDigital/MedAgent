/*
 * S1 smoke test — proves the toolchain (vitest + jsdom + Testing Library +
 * workspace @medagent/ui source transpilation) end to end. The real suite
 * (06 §12: MSW-mocked containers, 100% branch on proposal-card/verdict
 * state logic, axe assertions) grows from S2.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Badge, Button } from "@medagent/ui";
import { computeBackoffDelay } from "@/lib/sse";

describe("S1 scaffold smoke", () => {
  it("renders design-system components from @medagent/ui", () => {
    render(
      <div>
        <Button>Sign &amp; commit</Button>
        <Badge variant="warn">WARN</Badge>
      </div>,
    );
    expect(screen.getByRole("button", { name: "Sign & commit" })).toBeInTheDocument();
    expect(screen.getByText("WARN")).toBeInTheDocument();
  });

  it("computes bounded exponential backoff for SSE reconnects", () => {
    for (let attempt = 0; attempt < 12; attempt++) {
      const delay = computeBackoffDelay(attempt, 1_000, 30_000);
      expect(delay).toBeGreaterThanOrEqual(1_000);
      expect(delay).toBeLessThanOrEqual(30_000);
    }
  });
});
