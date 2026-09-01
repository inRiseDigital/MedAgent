import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Widget, WIDGET_KINDS, type WidgetSpec } from "@/components/widgets";

const spec = (kind: string, data: Record<string, unknown>, extra: Partial<WidgetSpec> = {}): WidgetSpec => ({
  id: "w1", kind, title: "T", data, ...extra,
});

describe("Widget registry", () => {
  it("exposes the expected kinds", () => {
    expect(WIDGET_KINDS).toEqual(
      expect.arrayContaining(["safety-alert", "record-links", "metric-trend", "stat-grid", "next-best-action", "timeline", "summary", "access-log", "consent-panel"]),
    );
  });

  it("renders an unknown kind as nothing", () => {
    const { container } = render(<Widget spec={spec("does-not-exist", {})} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("safety-alert renders items and strips [source] into a chip", () => {
    render(<Widget spec={spec("safety-alert", { severity: "block", items: ["Penicillin allergy [source: AllergyIntolerance/5]"] })} />);
    expect(screen.getByText(/Penicillin allergy/)).toBeInTheDocument();
    expect(screen.getByText("AllergyIntolerance")).toBeInTheDocument(); // ref chip = resource type
  });

  it("record-links renders tappable items and fires onAction with the ref", () => {
    const onAction = vi.fn();
    render(<Widget spec={spec("record-links", { items: [{ label: "Metformin", ref: "MedicationRequest/2" }] })} onAction={onAction} />);
    fireEvent.click(screen.getByRole("button", { name: /Metformin/ }));
    expect(onAction).toHaveBeenCalledWith("MedicationRequest/2");
  });

  it("metric-trend shows the latest value + unit", () => {
    render(<Widget spec={spec("metric-trend", { label: "Systolic", unit: "mmHg", points: [{ t: "a", v: 120 }, { t: "b", v: 134 }] })} />);
    expect(screen.getByText("134")).toBeInTheDocument();
    expect(screen.getByText("mmHg")).toBeInTheDocument();
  });

  it("next-best-action fires onAction with the action id", () => {
    const onAction = vi.fn();
    render(<Widget spec={spec("next-best-action", { actions: [{ id: "book", label: "Book a follow-up" }] })} onAction={onAction} />);
    fireEvent.click(screen.getByRole("button", { name: "Book a follow-up" }));
    expect(onAction).toHaveBeenCalledWith("book");
  });

  it("summary renders its points", () => {
    render(<Widget spec={spec("summary", { tone: "good", points: ["All results normal", "Keep taking metformin"] })} />);
    expect(screen.getByText("All results normal")).toBeInTheDocument();
  });

  it("confirm-action runs onConfirm on tap and advances to the done state (HITL)", async () => {
    const onConfirm = vi.fn().mockResolvedValue(true);
    render(
      <Widget
        spec={spec("confirm-action", {
          action: "refill", params: { medication: "Metformin" },
          prompt: "Request a refill for Metformin?", confirmLabel: "Confirm refill",
          doneLabel: "Refill requested for Metformin",
        })}
        onConfirm={onConfirm}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Confirm refill/ }));
    expect(onConfirm).toHaveBeenCalledWith("refill", { medication: "Metformin" });
    // the model only proposed; the tap is what commits — the done receipt reflects that
    expect(await screen.findByText(/Refill requested for Metformin/)).toBeInTheDocument();
  });

  it("access-log renders its viewers and marks the you:true row", () => {
    render(
      <Widget
        spec={spec("access-log", {
          items: [
            { who: "Dr. Amara Okoye", when: "2h ago", kind: "Encounter" },
            { who: "You", when: "just now", you: true },
          ],
        })}
      />,
    );
    expect(screen.getByText("Dr. Amara Okoye")).toBeInTheDocument();
    expect(screen.getByText("2h ago")).toBeInTheDocument();
    expect(screen.getByText("Encounter")).toBeInTheDocument(); // kind chip
    expect(screen.getByText("you")).toBeInTheDocument(); // self pill
  });

  it("consent-panel renders scopes and fires onAction with the scope id on tap", () => {
    const onAction = vi.fn();
    render(
      <Widget
        spec={spec("consent-panel", {
          scopes: [
            { id: "care-team", label: "Your care team", detail: "Doctors treating you", granted: true },
            { id: "research", label: "Anonymised research", granted: false },
          ],
        })}
        onAction={onAction}
      />,
    );
    expect(screen.getByText("Your care team")).toBeInTheDocument();
    expect(screen.getByText("Anonymised research")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Anonymised research/ }));
    expect(onAction).toHaveBeenCalledWith("research");
  });
});
