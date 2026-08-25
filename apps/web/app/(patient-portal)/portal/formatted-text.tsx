import type { ReactNode } from "react";

/*
 * Lightweight markdown renderer for the patient concierge's agent answers —
 * bold, inline code, bullet lists, headings, paragraphs. No external library
 * (keeps the bundle small + CSP clean), matching the project's hand-rolled-
 * primitives approach. Extracted from concierge.tsx (D1) so it is unit-testable
 * and reusable.
 */

/** Inline formatting within one line: **bold** and `code`. */
export function renderInline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /\*\*(.+?)\*\*|`([^`]+?)`/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let k = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    if (m[1] != null) out.push(<strong key={k++}>{m[1]}</strong>);
    else if (m[2] != null) out.push(<code key={k++} className="mh-code">{m[2]}</code>);
    last = re.lastIndex;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

/** Block-level rendering: bullet lists, `#`-headings and paragraphs. */
export function FormattedText({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let bullets: string[] = [];
  const flush = () => {
    if (!bullets.length) return;
    const items = bullets;
    bullets = [];
    blocks.push(<ul key={`u${blocks.length}`}>{items.map((b, i) => <li key={i}>{renderInline(b)}</li>)}</ul>);
  };
  for (const ln of text.split("\n")) {
    const t = ln.trim();
    if (/^[-*•]\s+/.test(t)) { bullets.push(t.replace(/^[-*•]\s+/, "")); continue; }
    flush();
    if (!t) continue;
    if (/^#{1,4}\s+/.test(t)) { blocks.push(<p key={`h${blocks.length}`} className="mh-h">{renderInline(t.replace(/^#{1,4}\s+/, ""))}</p>); continue; }
    blocks.push(<p key={`p${blocks.length}`}>{renderInline(t)}</p>);
  }
  flush();
  return <div className="mh-rich">{blocks}</div>;
}
