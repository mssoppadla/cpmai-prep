/**
 * YouTubeGalleryView tests — pure visual component.
 *
 * Click-to-load facade behaviour is the security/perf-critical part:
 * the YouTube iframe must NOT be in the DOM until the user clicks.
 */
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import YouTubeGalleryView from "@/components/cms/blocks/YouTubeGalleryView";


describe("YouTubeGalleryView", () => {
  it("shows an empty-state message when no URLs", () => {
    render(<YouTubeGalleryView urls="" />);
    expect(screen.getByText(/No YouTube videos/i)).toBeInTheDocument();
  });

  it("renders one thumbnail per valid URL", () => {
    const urls = `
      https://youtu.be/aaaaaaaaaaa
      https://youtu.be/bbbbbbbbbbb
      https://youtu.be/ccccccccccc
    `;
    const { container } = render(<YouTubeGalleryView urls={urls} />);
    const imgs = container.querySelectorAll("img");
    expect(imgs).toHaveLength(3);
    expect(imgs[0].getAttribute("src")).toContain("aaaaaaaaaaa");
    expect(imgs[1].getAttribute("src")).toContain("bbbbbbbbbbb");
    expect(imgs[2].getAttribute("src")).toContain("ccccccccccc");
  });

  it("clamps columns prop to 1..3", () => {
    const urls = "https://youtu.be/aaaaaaaaaaa";
    const { container, rerender } = render(<YouTubeGalleryView urls={urls} columns={10} />);
    let grid = container.querySelector(".yt-gallery-grid") as HTMLElement;
    expect(grid.style.gridTemplateColumns).toContain("3,");
    rerender(<YouTubeGalleryView urls={urls} columns={0} />);
    grid = container.querySelector(".yt-gallery-grid") as HTMLElement;
    expect(grid.style.gridTemplateColumns).toContain("1,");
  });

  it("does NOT render any iframe until clicked (privacy facade)", () => {
    const urls = "https://youtu.be/aaaaaaaaaaa\nhttps://youtu.be/bbbbbbbbbbb";
    const { container } = render(<YouTubeGalleryView urls={urls} />);
    expect(container.querySelector("iframe")).toBeNull();
  });

  it("renders an iframe only for the tile that was clicked", () => {
    const urls = "https://youtu.be/aaaaaaaaaaa\nhttps://youtu.be/bbbbbbbbbbb";
    const { container } = render(<YouTubeGalleryView urls={urls} />);
    const playButtons = screen.getAllByRole("button", { name: /Play YouTube video/ });
    expect(playButtons).toHaveLength(2);
    fireEvent.click(playButtons[0]);
    // One iframe now exists, pointing to the first video, with autoplay.
    const iframes = container.querySelectorAll("iframe");
    expect(iframes).toHaveLength(1);
    expect(iframes[0].getAttribute("src")).toContain("aaaaaaaaaaa");
    expect(iframes[0].getAttribute("src")).toContain("autoplay=1");
    // The second tile is still a thumbnail.
    expect(screen.getAllByRole("button", { name: /Play YouTube video bbbbbbbbbbb/ })).toHaveLength(1);
  });

  it("uses youtube-nocookie.com for the embed URL", () => {
    const urls = "https://youtu.be/aaaaaaaaaaa";
    const { container } = render(<YouTubeGalleryView urls={urls} />);
    fireEvent.click(screen.getByRole("button", { name: /Play YouTube video/ }));
    const iframe = container.querySelector("iframe");
    expect(iframe?.getAttribute("src")).toContain("youtube-nocookie.com");
  });

  it("silently drops invalid URLs (single bad URL doesn't break row)", () => {
    const urls = "https://youtu.be/aaaaaaaaaaa\nnot a url\nhttps://youtu.be/bbbbbbbbbbb";
    const { container } = render(<YouTubeGalleryView urls={urls} />);
    expect(container.querySelectorAll("img")).toHaveLength(2);
  });
});
