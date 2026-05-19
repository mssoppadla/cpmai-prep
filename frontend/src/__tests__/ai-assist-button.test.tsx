/**
 * AIAssistButton tests — the dropdown that calls into /admin/cms-ai/*.
 *
 * We don't mount a real BlockNote editor; we pass a fake editor with
 * the small set of methods the component actually uses
 * (replaceBlocks, getSelection, updateBlock, document).
 */
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import AIAssistButton from "@/components/cms/AIAssistButton";
import { admin } from "@/lib/api";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    admin: {
      ...actual.admin,
      cmsAi: {
        generatePage: vi.fn(),
        fillBlock: vi.fn(),
        improveBlock: vi.fn(),
      },
    },
  };
});

const mockedAi = vi.mocked(admin.cmsAi);

function makeFakeEditor(opts?: {
  selection?: { blocks: unknown[] };
  document?: unknown[];
}) {
  return {
    replaceBlocks: vi.fn(),
    getSelection: vi.fn(() => opts?.selection ?? { blocks: [] }),
    updateBlock: vi.fn(),
    document: opts?.document ?? [],
  };
}

describe("AIAssistButton", () => {
  beforeEach(() => {
    mockedAi.generatePage.mockReset();
    mockedAi.improveBlock.mockReset();
  });

  it("renders the trigger button and toggles the menu", () => {
    const ref = { current: null as ReturnType<typeof makeFakeEditor> | null };
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    render(<AIAssistButton editorRef={ref as any} />);
    const trigger = screen.getByText(/AI assist/);
    fireEvent.click(trigger);
    expect(screen.getByText(/Generate page from prompt/)).toBeInTheDocument();
    expect(screen.getByText(/Improve selection/)).toBeInTheDocument();
  });

  it("Generate mode → empty prompt blocked, error shown", async () => {
    const ref = { current: makeFakeEditor() };
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    render(<AIAssistButton editorRef={ref as any} />);
    fireEvent.click(screen.getByText(/AI assist/));
    fireEvent.click(screen.getByText(/Generate page from prompt/));
    fireEvent.click(screen.getByText("Generate"));
    expect(await screen.findByText(/Enter a prompt first/)).toBeInTheDocument();
    expect(mockedAi.generatePage).not.toHaveBeenCalled();
  });

  it("Generate mode → POSTs prompt and calls editor.replaceBlocks", async () => {
    const fake = makeFakeEditor({ document: [{ id: "a" }] });
    const ref = { current: fake };
    mockedAi.generatePage.mockResolvedValueOnce({
      blocks: [{ id: "new", type: "heading", content: "Hi" }] as never,
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    render(<AIAssistButton editorRef={ref as any} />);
    fireEvent.click(screen.getByText(/AI assist/));
    fireEvent.click(screen.getByText(/Generate page from prompt/));
    fireEvent.change(screen.getByPlaceholderText(/study guide/i),
      { target: { value: "Write me a page" } });
    fireEvent.click(screen.getByText("Generate"));
    await waitFor(() => {
      expect(mockedAi.generatePage).toHaveBeenCalledWith({
        prompt: "Write me a page",
      });
    });
    await waitFor(() => {
      expect(fake.replaceBlocks).toHaveBeenCalledWith(
        [{ id: "a" }],
        [{ id: "new", type: "heading", content: "Hi" }],
      );
    });
  });

  it("Improve mode → no selection → error, no API call", async () => {
    const fake = makeFakeEditor({ selection: { blocks: [] } });
    const ref = { current: fake };
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    render(<AIAssistButton editorRef={ref as any} />);
    fireEvent.click(screen.getByText(/AI assist/));
    fireEvent.click(screen.getByText(/Improve selection/));
    fireEvent.click(screen.getByText("Shorter"));
    expect(await screen.findByText(/Select one or more blocks/)).toBeInTheDocument();
    expect(mockedAi.improveBlock).not.toHaveBeenCalled();
  });

  it("Improve mode → with selection → calls improveBlock per block", async () => {
    const sel = {
      blocks: [
        { id: "b1", type: "paragraph", content: "Original A" },
        { id: "b2", type: "paragraph", content: "Original B" },
      ],
    };
    const fake = makeFakeEditor({ selection: sel });
    const ref = { current: fake };
    mockedAi.improveBlock.mockResolvedValue({ text: "improved" });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    render(<AIAssistButton editorRef={ref as any} />);
    fireEvent.click(screen.getByText(/AI assist/));
    fireEvent.click(screen.getByText(/Improve selection/));
    fireEvent.click(screen.getByText("Friendlier"));
    await waitFor(() => {
      expect(mockedAi.improveBlock).toHaveBeenCalledTimes(2);
    });
    expect(mockedAi.improveBlock).toHaveBeenNthCalledWith(1, {
      text: "Original A", tone: "friendlier",
    });
    expect(mockedAi.improveBlock).toHaveBeenNthCalledWith(2, {
      text: "Original B", tone: "friendlier",
    });
    expect(fake.updateBlock).toHaveBeenCalledTimes(2);
  });

  it("Improve mode → empty selection block is skipped", async () => {
    const sel = {
      blocks: [
        { id: "b1", type: "paragraph", content: "" },
        { id: "b2", type: "paragraph", content: "Has text" },
      ],
    };
    const fake = makeFakeEditor({ selection: sel });
    const ref = { current: fake };
    mockedAi.improveBlock.mockResolvedValue({ text: "improved" });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    render(<AIAssistButton editorRef={ref as any} />);
    fireEvent.click(screen.getByText(/AI assist/));
    fireEvent.click(screen.getByText(/Improve selection/));
    fireEvent.click(screen.getByText("More formal"));
    await waitFor(() => {
      expect(mockedAi.improveBlock).toHaveBeenCalledTimes(1);
    });
    expect(mockedAi.improveBlock).toHaveBeenCalledWith({
      text: "Has text", tone: "formal",
    });
  });
});
