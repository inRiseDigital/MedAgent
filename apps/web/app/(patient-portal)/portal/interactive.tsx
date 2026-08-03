"use client";
/*
 * Small client helpers that let server-rendered record rows be interactive.
 * Clicking an `Ask` row switches to the Concierge tab and asks the live agent
 * about that item — decoupled via window CustomEvents so server components can
 * stay server components (the concierge + shell listen for these events).
 */
import type { ReactNode } from "react";

export function Ask({ question, className, children }: { question: string; className?: string; children: ReactNode }) {
  return (
    <button
      type="button"
      className={className}
      onClick={() => {
        window.dispatchEvent(new CustomEvent("mh:tab", { detail: "chat" }));
        window.dispatchEvent(new CustomEvent("mh:ask", { detail: question }));
      }}
    >
      {children}
    </button>
  );
}
