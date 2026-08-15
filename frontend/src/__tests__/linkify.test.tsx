/**
 * linkifyText — admin text → safe clickable links, nothing else.
 * Used by the /pricing international-payments banner so the admin can
 * put WhatsApp / LinkedIn / email-page links in a runtime setting.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { linkifyText } from "@/lib/linkify";

function renderText(text: string) {
  return render(<p>{linkifyText(text)}</p>);
}

describe("linkifyText", () => {
  it("renders plain text unchanged (no links)", () => {
    renderText("International payments are temporarily unavailable.");
    expect(screen.getByText(/temporarily unavailable/)).toBeInTheDocument();
    expect(document.querySelectorAll("a")).toHaveLength(0);
  });

  it("auto-links a bare https URL (WhatsApp style)", () => {
    renderText("Ping us: https://wa.me/919876543210 anytime");
    const a = screen.getByRole("link");
    expect(a).toHaveAttribute("href", "https://wa.me/919876543210");
    expect(a).toHaveAttribute("target", "_blank");
    expect(a).toHaveAttribute("rel", expect.stringContaining("noopener"));
  });

  it("renders markdown-style [label](url) with the label as link text", () => {
    renderText("Reach me on [LinkedIn](https://www.linkedin.com/in/example) today");
    const a = screen.getByRole("link", { name: "LinkedIn" });
    expect(a).toHaveAttribute("href", "https://www.linkedin.com/in/example");
    // Raw markdown must not leak into the visible text.
    expect(screen.queryByText(/\]\(/)).not.toBeInTheDocument();
  });

  it("handles several links plus surrounding text", () => {
    renderText(
      "Write to [WhatsApp](https://wa.me/911234567890) or " +
      "https://www.linkedin.com/in/example — we reply fast.");
    expect(screen.getAllByRole("link")).toHaveLength(2);
    expect(screen.getByText(/we reply fast/)).toBeInTheDocument();
  });

  it("never becomes an anchor for javascript: or non-http schemes", () => {
    renderText("evil [click](javascript:alert(1)) and ftp://x.example");
    expect(document.querySelectorAll("a")).toHaveLength(0);
    // The malformed link stays as literal, harmless text.
    expect(screen.getByText(/javascript:alert/)).toBeInTheDocument();
  });

  it("escapes HTML — admin text cannot inject markup", () => {
    renderText('hello <img src=x onerror=alert(1)> world');
    expect(document.querySelector("img")).toBeNull();
    expect(screen.getByText(/<img src=x/)).toBeInTheDocument();
  });

  it("keeps trailing punctuation out of bare URLs", () => {
    renderText("Visit https://example.com/help, thanks!");
    expect(screen.getByRole("link"))
      .toHaveAttribute("href", "https://example.com/help");
    expect(screen.getByText(/, thanks!/)).toBeInTheDocument();
  });
});
