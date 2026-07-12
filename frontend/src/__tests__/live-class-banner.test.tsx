/** LiveClassBanner — two independently-toggleable buttons + colors. */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LiveClassBanner } from "@/components/landing/LiveClassBanner";

const BASE = {
  live_banner_enabled: true,
  live_banner_text: "Live classes are open!",
  live_banner_link_url: "https://zoom.us/register/x",
  live_banner_link_label: "Register now",
  live_banner_font_size: 16,
  live_banner_font_style: "normal" as const,
  live_banner_font_color: "#312e81",
  live_banner_bg_color: "#e0e7ff",
  live_banner_animation: "none" as const,
};

describe("LiveClassBanner buttons", () => {
  it("shows both buttons when both are enabled with URLs", () => {
    render(<LiveClassBanner landing={{
      ...BASE,
      live_banner_link_enabled: true,
      live_banner_ondemand_enabled: true,
      live_banner_ondemand_label: "Request on-demand training",
      live_banner_ondemand_url: "https://forms.gle/abc",
    }} />);
    expect(screen.getByRole("link", { name: "Register now" }))
      .toHaveAttribute("href", "https://zoom.us/register/x");
    const ondemand = screen.getByRole("link", { name: "Request on-demand training" });
    expect(ondemand).toHaveAttribute("href", "https://forms.gle/abc");
    expect(ondemand).toHaveAttribute("target", "_blank");
  });

  it("hides the registration button when toggled off, keeps on-demand", () => {
    render(<LiveClassBanner landing={{
      ...BASE,
      live_banner_link_enabled: false,
      live_banner_ondemand_enabled: true,
      live_banner_ondemand_label: "Custom training",
      live_banner_ondemand_url: "https://forms.gle/abc",
    }} />);
    expect(screen.queryByRole("link", { name: "Register now" })).toBeNull();
    expect(screen.getByRole("link", { name: "Custom training" })).toBeInTheDocument();
  });

  it("hides the on-demand button without a URL even when enabled", () => {
    render(<LiveClassBanner landing={{
      ...BASE,
      live_banner_ondemand_enabled: true,
      live_banner_ondemand_label: "Custom training",
      live_banner_ondemand_url: "",
    }} />);
    expect(screen.queryByRole("link", { name: "Custom training" })).toBeNull();
    expect(screen.getByRole("link", { name: "Register now" })).toBeInTheDocument();
  });

  it("can toggle BOTH buttons off — banner text still renders", () => {
    render(<LiveClassBanner landing={{
      ...BASE,
      live_banner_link_enabled: false,
      live_banner_ondemand_enabled: false,
    }} />);
    expect(screen.getByText("Live classes are open!")).toBeInTheDocument();
    expect(screen.queryAllByRole("link")).toHaveLength(0);
  });

  it("applies custom button colors; automatic colors invert the banner palette", () => {
    render(<LiveClassBanner landing={{
      ...BASE,
      live_banner_link_enabled: true,
      live_banner_link_bg_color: "#111111",
      live_banner_link_text_color: "#eeeeee",
      live_banner_ondemand_enabled: true,
      live_banner_ondemand_label: "Custom training",
      live_banner_ondemand_url: "https://forms.gle/abc",
      live_banner_ondemand_bg_color: "",
      live_banner_ondemand_text_color: "",
    }} />);
    const register = screen.getByRole("link", { name: "Register now" });
    expect(register.style.background).toBe("rgb(17, 17, 17)");
    expect(register.style.color).toBe("rgb(238, 238, 238)");
    // Automatic on-demand: white bg + banner text color as label.
    const ondemand = screen.getByRole("link", { name: "Custom training" });
    expect(ondemand.style.background).toBe("rgb(255, 255, 255)");
    expect(ondemand.style.color).toBe("rgb(49, 46, 129)");
  });

  it("registration button keeps legacy behavior when the new fields are absent", () => {
    render(<LiveClassBanner landing={BASE} />);
    const register = screen.getByRole("link", { name: "Register now" });
    // Automatic inversion: bg = font color, label = banner bg.
    expect(register.style.background).toBe("rgb(49, 46, 129)");
    expect(register.style.color).toBe("rgb(224, 231, 255)");
  });
});
