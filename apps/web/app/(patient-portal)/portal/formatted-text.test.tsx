import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FormattedText, renderInline } from "./formatted-text";

describe("renderInline", () => {
  it("renders **bold** and `code` spans, leaving plain text between", () => {
    const nodes = renderInline("take **2** with `water` now");
    render(<p data-testid="p">{nodes}</p>);
    const p = document.querySelector('[data-testid="p"]')!;
    expect(p.querySelector("strong")?.textContent).toBe("2");
    expect(p.querySelector("code.mh-code")?.textContent).toBe("water");
    expect(p.textContent).toBe("take 2 with water now");
  });

  it("leaves text with no markers untouched", () => {
    render(<p data-testid="plain">{renderInline("just plain text")}</p>);
    expect(document.querySelector('[data-testid="plain"]')!.textContent).toBe("just plain text");
  });
});

describe("FormattedText", () => {
  it("renders headings, bullet lists and paragraphs", () => {
    const { container } = render(
      <FormattedText text={"# Your results\nAll normal.\n- glucose ok\n- BP ok"} />,
    );
    const root = container.querySelector(".mh-rich")!;
    expect(root.querySelector("p.mh-h")?.textContent).toBe("Your results");
    const items = root.querySelectorAll("ul li");
    expect(items).toHaveLength(2);
    expect(items[0]!.textContent).toBe("glucose ok");
    // the non-heading, non-bullet line is a paragraph
    expect([...root.querySelectorAll("p:not(.mh-h)")].some((p) => p.textContent === "All normal.")).toBe(true);
  });

  it("groups consecutive bullets into one list and ignores blank lines", () => {
    const { container } = render(<FormattedText text={"- a\n- b\n\n- c"} />);
    // two separate lists (blank line breaks the group)
    expect(container.querySelectorAll("ul")).toHaveLength(2);
    expect(container.querySelectorAll("ul li")).toHaveLength(3);
  });

  it("renders inline markers inside bullets", () => {
    const { container } = render(<FormattedText text={"- take **2** tablets"} />);
    expect(container.querySelector("ul li strong")?.textContent).toBe("2");
  });
});
