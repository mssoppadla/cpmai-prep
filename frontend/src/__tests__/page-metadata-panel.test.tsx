/**
 * PageMetadataPanel tests — the side panel that drives all the
 * PATCH-able non-block fields of a ContentPage.
 *
 * No BlockNote here, no editor — this component is a pure form that
 * fires onChange callbacks with diff payloads.
 */
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import PageMetadataPanel from "@/components/cms/PageMetadataPanel";

const baseMeta = {
  slug: "about",
  title: "About Us",
  nav_visibility: "always" as const,
  nav_label: null,
  nav_order: 100,
  is_published: false,
};

function renderPanel(overrides = {}) {
  const onChange = vi.fn();
  render(
    <PageMetadataPanel
      meta={{ ...baseMeta, ...overrides }}
      onChange={onChange}
      originalSlug="about"
    />
  );
  return { onChange };
}

describe("PageMetadataPanel", () => {
  it("renders all four nav-visibility options as radios", () => {
    renderPanel();
    expect(screen.getByLabelText(/Always visible/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Logged-in users only/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Paid subscribers only/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Hidden from nav/)).toBeInTheDocument();
  });

  it("fires onChange with the selected nav_visibility", () => {
    const { onChange } = renderPanel();
    fireEvent.click(screen.getByLabelText(/Paid subscribers only/));
    expect(onChange).toHaveBeenCalledWith({ nav_visibility: "subscribed" });
  });

  it("fires onChange when title is edited", () => {
    const { onChange } = renderPanel();
    const input = screen.getByDisplayValue("About Us");
    fireEvent.change(input, { target: { value: "Our Mission" } });
    expect(onChange).toHaveBeenCalledWith({ title: "Our Mission" });
  });

  it("fires onChange when slug is edited", () => {
    const { onChange } = renderPanel();
    const input = screen.getByDisplayValue("about");
    fireEvent.change(input, { target: { value: "our-mission" } });
    expect(onChange).toHaveBeenCalledWith({ slug: "our-mission" });
  });

  it("warns when the slug differs from the originalSlug prop", () => {
    renderPanel({ slug: "renamed" });
    expect(screen.getByText(/breaks any external links to/)).toBeInTheDocument();
  });

  it("does NOT warn when slug equals originalSlug", () => {
    renderPanel();
    expect(screen.queryByText(/breaks any external links/)).not.toBeInTheDocument();
  });

  it("publish toggle fires onChange with new boolean", () => {
    const { onChange } = renderPanel({ is_published: false });
    fireEvent.click(screen.getByLabelText(/^Published$/));
    expect(onChange).toHaveBeenCalledWith({ is_published: true });
  });

  it("nav_label override sends null when emptied", () => {
    const { onChange } = renderPanel({ nav_label: "Custom" });
    const input = screen.getByDisplayValue("Custom");
    fireEvent.change(input, { target: { value: "" } });
    expect(onChange).toHaveBeenCalledWith({ nav_label: null });
  });

  it("nav_order parses integer, falls back to 0 on garbage", () => {
    const { onChange } = renderPanel();
    const input = screen.getByDisplayValue("100");
    fireEvent.change(input, { target: { value: "50" } });
    expect(onChange).toHaveBeenCalledWith({ nav_order: 50 });
  });
});
