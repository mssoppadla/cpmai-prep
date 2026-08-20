/**
 * WhatsApp bubble — renders only when configured; builds a correct
 * wa.me deep link with encoded prefill, page context, and logged-in
 * identity; never overlaps the assistant panel (z-order + bottom strip).
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import type { UserOut } from "@/types/api";

const mockSite = vi.fn();
vi.mock("@/lib/api", async (importOriginal) => {
  const orig = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...orig,
    content: { ...orig.content, site: (...a: unknown[]) => mockSite(...a) },
  };
});

import { WhatsAppBubble } from "@/components/assistant/WhatsAppBubble";

const USER: UserOut = {
  id: 7, email: "geethu@example.com", name: "Geethu Rs", role: "user",
} as UserOut;

beforeEach(() => {
  mockSite.mockReset();
  // Reset the module-level config cache between tests.
  vi.resetModules();
});

async function renderFresh(user: UserOut | null, pathname: string) {
  const { WhatsAppBubble: Fresh } =
    await import("@/components/assistant/WhatsAppBubble");
  return render(<Fresh user={user} pathname={pathname} />);
}

describe("WhatsAppBubble", () => {
  it("renders nothing when the number is empty (disabled)", async () => {
    mockSite.mockResolvedValue({ whatsapp_number: "",
                                 whatsapp_prefill: "Hi" });
    const { container } = await renderFresh(null, "/pricing");
    await waitFor(() => expect(mockSite).toHaveBeenCalled());
    expect(container.querySelector("a")).toBeNull();
  });

  it("renders nothing when the config fetch fails", async () => {
    mockSite.mockRejectedValue(new Error("network down"));
    const { container } = await renderFresh(null, "/pricing");
    await waitFor(() => expect(mockSite).toHaveBeenCalled());
    expect(container.querySelector("a")).toBeNull();
  });

  it("anonymous visitor gets wa.me link with prefill + page context", async () => {
    mockSite.mockResolvedValue({
      whatsapp_number: "919876543210",
      whatsapp_prefill: "Hi! Question about CPMAI prep.",
    });
    await renderFresh(null, "/pricing");
    const link = await screen.findByRole("link",
      { name: /Chat with us on WhatsApp/ });
    const href = link.getAttribute("href")!;
    expect(href.startsWith("https://wa.me/919876543210?text=")).toBe(true);
    const text = decodeURIComponent(href.split("text=")[1]);
    expect(text).toContain("Hi! Question about CPMAI prep.");
    expect(text).toContain("[via /pricing]");
    expect(text).not.toContain("I'm");        // no identity when anon
    expect(link).toHaveAttribute("target", "_blank");
    expect(link.getAttribute("rel")).toContain("noopener");
  });

  it("logged-in visitor gets name + email appended", async () => {
    mockSite.mockResolvedValue({
      whatsapp_number: "919876543210",
      whatsapp_prefill: "Hi!",
    });
    await renderFresh(USER, "/courses");
    const link = await screen.findByRole("link",
      { name: /Chat with us on WhatsApp/ });
    const text = decodeURIComponent(link.getAttribute("href")!.split("text=")[1]);
    expect(text).toContain("I'm Geethu Rs (geethu@example.com)");
    expect(text).toContain("[via /courses]");
  });

  it("sits in the bottom strip left of the assistant, below the panel z-order", async () => {
    mockSite.mockResolvedValue({
      whatsapp_number: "919876543210", whatsapp_prefill: "Hi!",
    });
    await renderFresh(null, "/");
    const link = await screen.findByRole("link",
      { name: /Chat with us on WhatsApp/ });
    // z-30 = same layer as the assistant bubble, BELOW the panel (z-40)
    // and site modals (z-50) — the no-overlap invariant.
    expect(link.className).toContain("z-30");
    expect(link.className).toContain("fixed");
    // Shifted left of the assistant bubble's right-1.25rem slot.
    expect(link.style.right).toContain("5.5rem");
  });
});
