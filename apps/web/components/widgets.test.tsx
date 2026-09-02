import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(cleanup);

import { Widget, WIDGET_KINDS, type WidgetSpec } from "@/components/widgets";

const spec = (kind: string, data: Record<string, unknown>, extra: Partial<WidgetSpec> = {}): WidgetSpec => ({
  id: "w1", kind, title: "T", data, ...extra,
});

describe("Widget registry", () => {
  it("exposes the expected kinds", () => {
    expect(WIDGET_KINDS).toEqual(
      expect.arrayContaining(["safety-alert", "record-links", "metric-trend", "stat-grid", "next-best-action", "timeline", "summary", "access-log", "consent-panel", "consult-session", "order-status", "plan-steps", "receipt"]),
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

  const consultData = {
    items: [
      { id: "i1", type: "reason", label: "Chest tightness on exertion" },
      { id: "i2", type: "medication", label: "Atorvastatin 20mg", detail: "Started 3 months ago", ref: "MedicationRequest/7" },
      { id: "i3", type: "overdue", label: "HbA1c due" },
    ],
  };

  it("consult-session renders its items and the type chips", () => {
    render(<Widget spec={spec("consult-session", consultData)} />);
    expect(screen.getByText("Chest tightness on exertion")).toBeInTheDocument();
    expect(screen.getByText("Atorvastatin 20mg")).toBeInTheDocument();
    expect(screen.getByText("reason")).toBeInTheDocument(); // type chip
    expect(screen.getByText("medication")).toBeInTheDocument();
    expect(screen.getByText("overdue")).toBeInTheDocument();
    expect(screen.getByText("MedicationRequest")).toBeInTheDocument(); // ref chip
    expect(screen.getByText("0 of 3 confirmed")).toBeInTheDocument();
  });

  it("consult-session toggles an item's confirmed state on tap", () => {
    render(<Widget spec={spec("consult-session", consultData)} />);
    const row = screen.getByRole("button", { name: /Chest tightness/ });
    expect(row).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(row);
    expect(row).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("1 of 3 confirmed")).toBeInTheDocument();
    fireEvent.click(row); // toggles back off
    expect(row).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText("0 of 3 confirmed")).toBeInTheDocument();
  });

  it("consult-session's Complete button is gated until an item is confirmed, then fires onConfirm (HITL)", async () => {
    const onConfirm = vi.fn().mockResolvedValue(true);
    render(<Widget spec={spec("consult-session", consultData)} onConfirm={onConfirm} />);
    const complete = screen.getByRole("button", { name: /Complete consultation/ });
    expect(complete).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /Atorvastatin 20mg/ }));
    fireEvent.click(screen.getByRole("button", { name: /HbA1c due/ }));
    expect(complete).toBeEnabled();
    fireEvent.click(complete);
    expect(onConfirm).toHaveBeenCalledWith("consult-complete", { confirmed: ["i2", "i3"], count: 2 });
    expect(await screen.findByText(/Consultation summarised/)).toBeInTheDocument();
  });

  it("order-status renders its step labels and marks the active step (aria-current)", () => {
    render(
      <Widget
        spec={spec("order-status", {
          label: "Metformin 500mg",
          ref: "MedicationRequest/9",
          steps: [
            { key: "ordered", label: "Ordered", state: "done" },
            { key: "dispensing", label: "Dispensing", state: "active" },
            { key: "ready", label: "Ready for pickup", state: "pending" },
          ],
        })}
      />,
    );
    expect(screen.getByText("Metformin 500mg")).toBeInTheDocument();
    expect(screen.getByText("MedicationRequest")).toBeInTheDocument(); // ref chip = resource type
    expect(screen.getByText("Ordered")).toBeInTheDocument();
    expect(screen.getByText("Ready for pickup")).toBeInTheDocument();
    // the active step is the one marked aria-current="step"
    const active = screen.getByText("Dispensing").closest("li");
    expect(active).toHaveAttribute("aria-current", "step");
  });

  it("plan-steps renders its step labels in order with numbered badges", () => {
    render(
      <Widget
        spec={spec("plan-steps", {
          steps: [
            { label: "Check your allergy list" },
            { label: "Review the new prescription" },
            { label: "Flag any interactions" },
          ],
        })}
      />,
    );
    expect(screen.getByText("Check your allergy list")).toBeInTheDocument();
    expect(screen.getByText("Review the new prescription")).toBeInTheDocument();
    expect(screen.getByText("Flag any interactions")).toBeInTheDocument();
    // a clean plan (no per-step state) shows the ordered numbers 1..N in its badges
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("plan-steps reflects an active step distinctly (aria-current)", () => {
    render(
      <Widget
        spec={spec("plan-steps", {
          steps: [
            { label: "Pull your record", state: "done" },
            { label: "Check interactions", state: "active" },
            { label: "Summarise for you", state: "pending" },
          ],
        })}
      />,
    );
    expect(screen.getByText("Check interactions")).toBeInTheDocument();
    // the active step is the one marked aria-current="step"
    const active = screen.getByText("Check interactions").closest("li");
    expect(active).toHaveAttribute("aria-current", "step");
    // a done step is not marked active
    expect(screen.getByText("Pull your record").closest("li")).not.toHaveAttribute("aria-current");
  });

  it("receipt renders its lines (label + value) and the title", () => {
    render(
      <Widget
        spec={spec(
          "receipt",
          {
            lines: [
              { label: "Medication", value: "Metformin 500mg" },
              { label: "Quantity", value: "60 tablets" },
              { label: "Total", value: "$0.00" },
            ],
            ref: "MedicationDispense/12",
          },
          { title: "Refill confirmed" },
        )}
      />,
    );
    expect(screen.getByText("Refill confirmed")).toBeInTheDocument();
    expect(screen.getByText("Medication")).toBeInTheDocument();
    expect(screen.getByText("Metformin 500mg")).toBeInTheDocument();
    expect(screen.getByText("Quantity")).toBeInTheDocument();
    expect(screen.getByText("60 tablets")).toBeInTheDocument();
    expect(screen.getByText("$0.00")).toBeInTheDocument();
    expect(screen.getByText("MedicationDispense")).toBeInTheDocument(); // ref chip
  });
});
