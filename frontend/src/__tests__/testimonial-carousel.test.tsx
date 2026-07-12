/**
 * TestimonialCarousel — landing-page carousel behavior.
 *
 * jsdom's matchMedia stub (setup.tsx) always reports matches:false, so
 * the carousel runs in mobile mode here: 1 card per view, no reduced
 * motion. That makes the math deterministic: 3 items → 3 dot positions.
 */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TestimonialCarousel } from "@/components/landing/TestimonialCarousel";
import type { TestimonialOut } from "@/types/api";

const ITEMS: TestimonialOut[] = [
  { id: 1, name: "Sarah T.", role: "AI Project Manager",
    quote: "The mock exams were spot on.", photo_url: null,
    link_url: "https://www.linkedin.com/in/sarah", display_order: 10 },
  { id: 2, name: "Niesha P.", role: "Product Owner",
    quote: "Structured and straightforward.", photo_url: null,
    link_url: null, display_order: 20 },
  { id: 3, name: "John D.", role: "AI Consultant",
    quote: "Detailed feedback was a game changer.", photo_url: null,
    link_url: null, display_order: 30 },
];

function dots() {
  return screen.getAllByRole("button", { name: /Go to testimonial/ });
}
function currentDotIndex() {
  return dots().findIndex(d => d.getAttribute("aria-current") === "true");
}

describe("TestimonialCarousel", () => {
  it("renders heading, all cards, and both arrows", () => {
    render(<TestimonialCarousel items={ITEMS} heading="What our aspirants say"
                                intervalMs={6000} />);
    expect(screen.getByText("What our aspirants say")).toBeInTheDocument();
    expect(screen.getByText("Sarah T.")).toBeInTheDocument();
    expect(screen.getByText("Niesha P.")).toBeInTheDocument();
    expect(screen.getByText("John D.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous testimonials" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next testimonials" })).toBeInTheDocument();
    expect(dots()).toHaveLength(3);   // 3 items, 1 per view
  });

  it("advances on next-arrow click and wraps around", () => {
    render(<TestimonialCarousel items={ITEMS} heading="Testimonials"
                                intervalMs={6000} />);
    const next = screen.getByRole("button", { name: "Next testimonials" });
    expect(currentDotIndex()).toBe(0);
    fireEvent.click(next);
    expect(currentDotIndex()).toBe(1);
    fireEvent.click(next);
    fireEvent.click(next);              // past the last slide → wraps to 0
    expect(currentDotIndex()).toBe(0);
  });

  it("previous from the first slide wraps to the last", () => {
    render(<TestimonialCarousel items={ITEMS} heading="Testimonials"
                                intervalMs={6000} />);
    fireEvent.click(screen.getByRole("button", { name: "Previous testimonials" }));
    expect(currentDotIndex()).toBe(2);
  });

  it("cards with link_url link out in a new tab; others don't", () => {
    render(<TestimonialCarousel items={ITEMS} heading="Testimonials"
                                intervalMs={6000} />);
    const link = screen.getByRole("link",
      { name: /Sarah T\.'s testimonial/ });
    expect(link).toHaveAttribute("href", "https://www.linkedin.com/in/sarah");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(screen.queryByRole("link", { name: /Niesha/ })).toBeNull();
  });

  it("renders nothing when there are no testimonials", () => {
    const { container } = render(
      <TestimonialCarousel items={[]} heading="Testimonials" intervalMs={6000} />);
    expect(container).toBeEmptyDOMElement();
  });

  describe("auto-rotate", () => {
    beforeEach(() => { vi.useFakeTimers(); });
    afterEach(() => { vi.useRealTimers(); });

    it("moves to the next slide after the configured interval", () => {
      render(<TestimonialCarousel items={ITEMS} heading="Testimonials"
                                  intervalMs={5000} />);
      expect(currentDotIndex()).toBe(0);
      act(() => { vi.advanceTimersByTime(5000); });
      expect(currentDotIndex()).toBe(1);
      act(() => { vi.advanceTimersByTime(5000); });
      expect(currentDotIndex()).toBe(2);
      act(() => { vi.advanceTimersByTime(5000); });   // wraps
      expect(currentDotIndex()).toBe(0);
    });

    it("clamps intervals below the 2s floor instead of strobing", () => {
      render(<TestimonialCarousel items={ITEMS} heading="Testimonials"
                                  intervalMs={1} />);
      act(() => { vi.advanceTimersByTime(1000); });
      expect(currentDotIndex()).toBe(0);              // not rotated yet
      act(() => { vi.advanceTimersByTime(1100); });   // past the 2s floor
      expect(currentDotIndex()).toBe(1);
    });
  });
});
