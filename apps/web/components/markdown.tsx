"use client";

/*
 * Markdown renderer for the clinical agent's answers (06 §6). The agent emits
 * GitHub-flavoured markdown — headings, tables, lists, bold — plus two inline
 * conventions we surface specially:
 *   [source: ResourceType/id]  -> a teal citation chip (grounding, FR-3.4)
 *   [general knowledge]        -> a muted "general knowledge" tag
 * Everything is theme-aware via the semantic tokens; no palette literals.
 */
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";

// Turn our inline conventions into links carrying a private scheme, so the
// `a` renderer below can style them. Done as text so react-markdown still
// parses surrounding markdown normally.
function preprocess(text: string): string {
  return text
    .replace(/\[source:\s*([^\]]+)\]/gi, (_m, ref: string) => `[${ref.trim()}](cite:${ref.trim()})`)
    .replace(/\[general knowledge\]/gi, "[general knowledge](tag:gk)");
}

const components: Components = {
  h1: ({ children }) => <h1 className="mt-4 mb-2 text-base font-semibold first:mt-0">{children}</h1>,
  h2: ({ children }) => (
    <h2 className="mt-4 mb-1.5 text-sm font-semibold tracking-tight text-foreground first:mt-0">{children}</h2>
  ),
  h3: ({ children }) => <h3 className="mt-3 mb-1 text-sm font-semibold text-muted-foreground first:mt-0">{children}</h3>,
  p: ({ children }) => <p className="my-1.5 leading-relaxed first:mt-0 last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="my-1.5 ml-4 list-disc space-y-0.5 marker:text-muted-foreground">{children}</ul>,
  ol: ({ children }) => <ol className="my-1.5 ml-4 list-decimal space-y-0.5 marker:text-muted-foreground">{children}</ol>,
  li: ({ children }) => <li className="leading-relaxed">{children}</li>,
  strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
  em: ({ children }) => <em className="italic">{children}</em>,
  hr: () => <hr className="my-3 border-border" />,
  code: ({ children }) => (
    <code className="rounded bg-muted px-1 py-0.5 font-mono text-[0.8em] text-foreground">{children}</code>
  ),
  // Scrollable, bordered tables — the workspace is dense, never let a wide
  // table break the layout.
  table: ({ children }) => (
    <div className="my-2 w-full overflow-x-auto rounded-md border border-border">
      <table className="w-full border-collapse text-xs">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-muted">{children}</thead>,
  tbody: ({ children }) => <tbody>{children}</tbody>,
  tr: ({ children }) => <tr className="border-b border-border last:border-0">{children}</tr>,
  th: ({ children }) => (
    <th className="px-2.5 py-1.5 text-left font-semibold text-muted-foreground">{children}</th>
  ),
  td: ({ children }) => <td className="px-2.5 py-1.5 align-top">{children}</td>,
  a: ({ href, children }) => {
    if (href?.startsWith("cite:")) {
      return (
        <span className="mx-0.5 inline-flex items-center gap-1 rounded border border-primary/30 bg-primary/10 px-1.5 py-0.5 align-baseline text-[0.7rem] font-medium text-primary">
          <span aria-hidden className="text-[0.6rem]">◆</span>
          {children}
        </span>
      );
    }
    if (href === "tag:gk") {
      return (
        <span className="mx-0.5 inline-flex items-center rounded border border-border bg-muted px-1.5 py-0.5 align-baseline text-[0.7rem] font-medium text-muted-foreground">
          {children}
        </span>
      );
    }
    return (
      <a href={href} className="text-primary underline underline-offset-2" target="_blank" rel="noreferrer">
        {children}
      </a>
    );
  },
};

export function AssistantMarkdown({ text }: { text: string }) {
  return (
    <div className="text-sm text-foreground">
      <Markdown
        remarkPlugins={[remarkGfm]}
        urlTransform={(url) => url /* keep our cite:/tag: schemes */}
        components={components}
      >
        {preprocess(text)}
      </Markdown>
    </div>
  );
}
