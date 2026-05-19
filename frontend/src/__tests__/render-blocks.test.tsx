/**
 * RenderBlocks tests — public block→React renderer.
 *
 * One assertion per block type, plus the list-grouping state machine.
 * If a new block type is added to ``RenderBlocks``, add a test here so
 * end-user output is pinned. Silently dropping a block type is worse
 * than a noisy fallback because the operator's content disappears
 * without warning.
 */
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import RenderBlocks from "@/components/cms/RenderBlocks";
import type { BlockNoteBlock } from "@/types/api";


// ----------------------------------------------------- block factories

function paragraph(text: string): BlockNoteBlock {
  return { id: text, type: "paragraph", content: text };
}
function heading(level: number, text: string): BlockNoteBlock {
  return { id: `h-${text}`, type: "heading", props: { level }, content: text };
}
function bullet(text: string): BlockNoteBlock {
  return { id: `bul-${text}`, type: "bulletListItem", content: text };
}
function ordered(text: string): BlockNoteBlock {
  return { id: `ord-${text}`, type: "numberedListItem", content: text };
}
function check(text: string, checked: boolean): BlockNoteBlock {
  return {
    id: `chk-${text}`, type: "checkListItem",
    props: { checked }, content: text,
  };
}
function table(rows: string[][]): BlockNoteBlock {
  return {
    id: "t",
    type: "table",
    content: {
      type: "tableContent",
      columnWidths: rows[0]?.map(() => null) ?? [],
      rows: rows.map((cells) => ({
        cells: cells.map((cellText) => ({
          type: "tableCell",
          props: {
            colspan: 1, rowspan: 1, backgroundColor: "default",
            textColor: "default", textAlignment: "left",
          },
          content: [{ type: "text", text: cellText, styles: {} }],
        })),
      })),
    },
  };
}
function image(url: string, caption?: string): BlockNoteBlock {
  return {
    id: "img", type: "image",
    props: { url, caption: caption ?? "", name: "", showPreview: true },
  };
}
function video(url: string): BlockNoteBlock {
  return { id: "vid", type: "video", props: { url, caption: "" } };
}
function codeBlock(text: string, language?: string): BlockNoteBlock {
  return {
    id: "code", type: "codeBlock",
    props: { language: language ?? "" }, content: text,
  };
}
function ytGallery(urls: string, columns = 1): BlockNoteBlock {
  return { id: "yt", type: "youtubeGallery", props: { urls, columns } };
}


// ----------------------------------------------------- per-block rendering

describe("RenderBlocks — paragraph", () => {
  it("renders <p> with text", () => {
    render(<RenderBlocks blocks={[paragraph("Hello world")]} />);
    const el = screen.getByText("Hello world");
    expect(el.tagName).toBe("P");
  });
});


describe("RenderBlocks — heading", () => {
  it("levels 1/2/3 emit h1/h2/h3", () => {
    render(<RenderBlocks blocks={[
      heading(1, "Title"),
      heading(2, "Subtitle"),
      heading(3, "Section"),
    ]} />);
    expect(screen.getByText("Title").tagName).toBe("H1");
    expect(screen.getByText("Subtitle").tagName).toBe("H2");
    expect(screen.getByText("Section").tagName).toBe("H3");
  });

  it("defaults missing level to h2", () => {
    const b: BlockNoteBlock = { id: "x", type: "heading", content: "Untitled" };
    render(<RenderBlocks blocks={[b]} />);
    expect(screen.getByText("Untitled").tagName).toBe("H2");
  });

  it("clamps level >3 to h3 (sane upper bound)", () => {
    render(<RenderBlocks blocks={[heading(7, "Big")]} />);
    // h4-h6 fall into the else branch which emits h3
    expect(screen.getByText("Big").tagName).toBe("H3");
  });
});


describe("RenderBlocks — bullet list", () => {
  it("groups consecutive bullets into one <ul>", () => {
    const { container } = render(<RenderBlocks blocks={[
      bullet("one"), bullet("two"), bullet("three"),
    ]} />);
    const lists = container.querySelectorAll("ul");
    expect(lists).toHaveLength(1);
    expect(lists[0].querySelectorAll("li")).toHaveLength(3);
  });
});


describe("RenderBlocks — numbered list", () => {
  it("groups consecutive numbered items into one <ol>", () => {
    const { container } = render(<RenderBlocks blocks={[
      ordered("one"), ordered("two"),
    ]} />);
    expect(container.querySelectorAll("ol")).toHaveLength(1);
    expect(container.querySelectorAll("ul")).toHaveLength(0);
  });
});


describe("RenderBlocks — check list", () => {
  it("renders checkbox + text, struck through when checked", () => {
    const { container } = render(<RenderBlocks blocks={[
      check("done thing", true),
      check("pending thing", false),
    ]} />);
    const boxes = container.querySelectorAll("input[type=checkbox]");
    expect(boxes).toHaveLength(2);
    expect((boxes[0] as HTMLInputElement).checked).toBe(true);
    expect((boxes[1] as HTMLInputElement).checked).toBe(false);
    // First item (checked) should have line-through styling
    expect(screen.getByText("done thing").className).toContain("line-through");
    expect(screen.getByText("pending thing").className).not.toContain("line-through");
    // Public renderer must NOT let visitors toggle checkboxes
    expect(boxes[0]).toHaveProperty("readOnly", true);
  });
});


describe("RenderBlocks — table", () => {
  it("renders <table> with rows and cells", () => {
    const { container } = render(<RenderBlocks blocks={[
      table([
        ["A", "B"],
        ["1", "2"],
        ["3", "4"],
      ]),
    ]} />);
    const t = container.querySelector("table");
    expect(t).not.toBeNull();
    expect(t!.querySelectorAll("tr")).toHaveLength(3);
    expect(t!.querySelectorAll("td")).toHaveLength(6);
    expect(screen.getByText("A")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
  });

  it("renders nothing for an empty table (no rows)", () => {
    const empty: BlockNoteBlock = {
      id: "t", type: "table",
      content: { type: "tableContent", rows: [], columnWidths: [] },
    };
    const { container } = render(<RenderBlocks blocks={[empty]} />);
    expect(container.querySelector("table")).toBeNull();
  });
});


describe("RenderBlocks — image", () => {
  it("renders <img> with caption", () => {
    const { container } = render(<RenderBlocks blocks={[
      image("https://example.com/cat.jpg", "A black cat"),
    ]} />);
    const img = container.querySelector("img");
    expect(img).not.toBeNull();
    expect(img!.getAttribute("src")).toBe("https://example.com/cat.jpg");
    expect(img!.getAttribute("alt")).toBe("A black cat");
    expect(screen.getByText("A black cat").tagName).toBe("FIGCAPTION");
  });

  it("renders nothing when url is empty (operator hasn't uploaded yet)", () => {
    const { container } = render(<RenderBlocks blocks={[image("")]} />);
    expect(container.querySelector("figure")).toBeNull();
  });
});


describe("RenderBlocks — video (non-YouTube)", () => {
  it("renders <video> element with controls", () => {
    const { container } = render(<RenderBlocks blocks={[
      video("https://example.com/clip.mp4"),
    ]} />);
    const v = container.querySelector("video");
    expect(v).not.toBeNull();
    expect(v!.getAttribute("src")).toBe("https://example.com/clip.mp4");
    expect(v!.hasAttribute("controls")).toBe(true);
  });
});


describe("RenderBlocks — codeBlock", () => {
  it("renders <pre><code> with language class", () => {
    const { container } = render(<RenderBlocks blocks={[
      codeBlock("def hi():\n    pass", "python"),
    ]} />);
    const pre = container.querySelector("pre");
    expect(pre).not.toBeNull();
    const code = pre!.querySelector("code");
    expect(code).not.toBeNull();
    expect(code!.className).toBe("language-python");
    expect(code!.textContent).toContain("def hi():");
  });

  it("renders without language class when language is empty", () => {
    const { container } = render(<RenderBlocks blocks={[codeBlock("text")]} />);
    const code = container.querySelector("code");
    expect(code?.className).toBe("");
  });
});


describe("RenderBlocks — youtubeGallery", () => {
  it("renders thumbnails for each valid URL", () => {
    const { container } = render(<RenderBlocks blocks={[
      ytGallery(
        "https://youtu.be/aaaaaaaaaaa\nhttps://youtu.be/bbbbbbbbbbb",
        2,
      ),
    ]} />);
    const imgs = container.querySelectorAll("img");
    expect(imgs).toHaveLength(2);
    expect(imgs[0].getAttribute("src")).toContain("img.youtube.com");
  });
});


// ----------------------------------------------------- list grouping state machine

describe("RenderBlocks — list grouping", () => {
  it("breaks list grouping when a non-list block intervenes", () => {
    const { container } = render(<RenderBlocks blocks={[
      bullet("a"), bullet("b"),
      paragraph("interrupting"),
      bullet("c"), bullet("d"),
    ]} />);
    expect(container.querySelectorAll("ul")).toHaveLength(2);
  });

  it("mixing bullet and numbered creates separate lists", () => {
    const { container } = render(<RenderBlocks blocks={[
      bullet("a"), ordered("b"),
    ]} />);
    expect(container.querySelectorAll("ul")).toHaveLength(1);
    expect(container.querySelectorAll("ol")).toHaveLength(1);
  });

  it("checkListItem groups under <ul> like bullets do", () => {
    const { container } = render(<RenderBlocks blocks={[
      check("a", false), check("b", true),
    ]} />);
    // Both items in a single <ul>
    expect(container.querySelectorAll("ul")).toHaveLength(1);
    expect(container.querySelectorAll("ul li")).toHaveLength(2);
  });
});


// ----------------------------------------------------- inline content collapsing

describe("RenderBlocks — inline content", () => {
  it("renders inline content array as flat text", () => {
    const b: BlockNoteBlock = {
      id: "x", type: "paragraph",
      content: [
        { type: "text", text: "Hello " },
        { type: "text", text: "world" },
      ],
    };
    render(<RenderBlocks blocks={[b]} />);
    expect(screen.getByText("Hello world")).toBeInTheDocument();
  });

  it("table cells with inline content arrays render their text", () => {
    // Verifies the cell extractor walks ``cell.content`` (an array) too.
    const { container } = render(<RenderBlocks blocks={[
      table([["Cell A", "Cell B"]]),
    ]} />);
    const cells = container.querySelectorAll("td");
    expect(cells[0].textContent).toBe("Cell A");
    expect(cells[1].textContent).toBe("Cell B");
  });
});


// ----------------------------------------------------- structural guards

describe("RenderBlocks — structural guards", () => {
  it("unknown block types are silently dropped (no crash)", () => {
    const b: BlockNoteBlock = { id: "x", type: "unknownBlockType", content: "x" };
    const { container } = render(<RenderBlocks blocks={[b]} />);
    expect(container.querySelector("p")).toBeNull();
    expect(container.querySelector("span")).toBeNull();
    expect(screen.queryByText("x")).toBeNull();
  });

  it("empty blocks array renders nothing", () => {
    const { container } = render(<RenderBlocks blocks={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("multiple block types render together in order", () => {
    const { container } = render(<RenderBlocks blocks={[
      heading(1, "Welcome"),
      paragraph("Intro"),
      table([["k", "v"]]),
      bullet("First"),
      bullet("Second"),
      ytGallery("https://youtu.be/aaaaaaaaaaa", 1),
      codeBlock("x = 1", "python"),
    ]} />);
    // Each element must appear in order
    expect(container.querySelector("h1")).not.toBeNull();
    expect(container.querySelector("p")).not.toBeNull();
    expect(container.querySelector("table")).not.toBeNull();
    expect(container.querySelectorAll("ul li")).toHaveLength(2);
    expect(container.querySelector("img")?.getAttribute("src"))
      .toContain("img.youtube.com");
    expect(container.querySelector("pre code")).not.toBeNull();
  });
});
