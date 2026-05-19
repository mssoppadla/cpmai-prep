/**
 * Admin content-pages list view tests.
 *
 * Pins:
 *   - Renders rows from the API
 *   - "+ New page" → form → POST → redirect
 *   - Delete confirmation flow
 *   - Validation of slug + title at the client edge (matches backend regex)
 *
 * BlockNote itself is NOT exercised here — that's the [id] editor route's
 * concern, and rendering BlockNote in jsdom is heavy + flaky. We only
 * test the list page, which has no editor dependencies.
 */
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import ContentPagesAdminPage from "@/app/admin/content-pages/page";
import { admin } from "@/lib/api";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    admin: {
      ...actual.admin,
      contentPages: {
        list: vi.fn(),
        get: vi.fn(),
        create: vi.fn(),
        update: vi.fn(),
        delete: vi.fn(),
      },
    },
  };
});

const mockedAdmin = vi.mocked(admin.contentPages);

const samplePage = {
  id: 1,
  tenant_id: 1,
  slug: "study-guide",
  title: "CPMAI Study Guide",
  blocks: [],
  nav_visibility: "always" as const,
  nav_label: null,
  nav_order: 10,
  is_published: true,
  is_landing: false,
  is_deleted: false,
  deleted_at: null,
  deleted_by: null,
  created_by: 1,
  created_at: "2026-05-19T00:00:00Z",
  updated_at: "2026-05-19T00:00:00Z",
};

describe("ContentPagesAdminPage", () => {
  beforeEach(() => {
    mockedAdmin.list.mockReset();
    mockedAdmin.create.mockReset();
    mockedAdmin.delete.mockReset();
  });

  it("renders pages returned by the API", async () => {
    mockedAdmin.list.mockResolvedValueOnce([samplePage]);
    render(<ContentPagesAdminPage />);
    await waitFor(() => {
      expect(screen.getByText("CPMAI Study Guide")).toBeInTheDocument();
    });
    // Slug shown inside a <code> element, prefixed with "/"
    expect(
      screen.getByText((_, el) => el?.tagName === "CODE" && el.textContent === "/study-guide")
    ).toBeInTheDocument();
    // Status badge — bullet + text, distinct from the help blurb.
    expect(screen.getByText(/● Published/)).toBeInTheDocument();
    expect(screen.getByText("always")).toBeInTheDocument();
  });

  it("shows empty state when no pages exist", async () => {
    mockedAdmin.list.mockResolvedValueOnce([]);
    render(<ContentPagesAdminPage />);
    await waitFor(() => {
      expect(screen.getByText(/No content pages yet/i)).toBeInTheDocument();
    });
  });

  it("opens create form when '+ New page' is clicked", async () => {
    mockedAdmin.list.mockResolvedValueOnce([]);
    render(<ContentPagesAdminPage />);
    await waitFor(() => screen.getByText(/No content pages yet/i));
    fireEvent.click(screen.getByRole("button", { name: /\+ New page/ }));
    expect(screen.getByText(/Create a new page/i)).toBeInTheDocument();
    expect(screen.getByPlaceholderText("study-guide")).toBeInTheDocument();
  });

  it("rejects invalid slug before hitting the API", async () => {
    mockedAdmin.list.mockResolvedValueOnce([]);
    render(<ContentPagesAdminPage />);
    await waitFor(() => screen.getByText(/No content pages yet/i));
    fireEvent.click(screen.getByRole("button", { name: /\+ New page/ }));
    fireEvent.change(screen.getByPlaceholderText("study-guide"),
      { target: { value: "Has Spaces" } });
    fireEvent.change(screen.getByPlaceholderText("CPMAI Study Guide"),
      { target: { value: "Title" } });
    fireEvent.click(screen.getByRole("button", { name: /Create and open editor/i }));
    await waitFor(() => {
      expect(screen.getByText(/Slug must be lowercase/i)).toBeInTheDocument();
    });
    expect(mockedAdmin.create).not.toHaveBeenCalled();
  });

  it("rejects empty title before hitting the API", async () => {
    mockedAdmin.list.mockResolvedValueOnce([]);
    render(<ContentPagesAdminPage />);
    await waitFor(() => screen.getByText(/No content pages yet/i));
    fireEvent.click(screen.getByRole("button", { name: /\+ New page/ }));
    fireEvent.change(screen.getByPlaceholderText("study-guide"),
      { target: { value: "about" } });
    // Title left empty
    fireEvent.click(screen.getByRole("button", { name: /Create and open editor/i }));
    await waitFor(() => {
      expect(screen.getByText(/Title is required/i)).toBeInTheDocument();
    });
    expect(mockedAdmin.create).not.toHaveBeenCalled();
  });

  it("creates a page and the API receives the trimmed payload", async () => {
    mockedAdmin.list.mockResolvedValueOnce([]);
    mockedAdmin.create.mockResolvedValueOnce(samplePage);
    render(<ContentPagesAdminPage />);
    await waitFor(() => screen.getByText(/No content pages yet/i));
    fireEvent.click(screen.getByRole("button", { name: /\+ New page/ }));
    fireEvent.change(screen.getByPlaceholderText("study-guide"),
      { target: { value: "  study-guide  " } });
    fireEvent.change(screen.getByPlaceholderText("CPMAI Study Guide"),
      { target: { value: "  Title  " } });
    fireEvent.click(screen.getByRole("button", { name: /Create and open editor/i }));
    await waitFor(() => {
      expect(mockedAdmin.create).toHaveBeenCalledWith({
        slug: "study-guide", title: "Title",
      });
    });
  });

  it("confirms before delete and only calls API on confirm", async () => {
    mockedAdmin.list.mockResolvedValueOnce([samplePage]);
    mockedAdmin.delete.mockResolvedValueOnce(undefined);
    render(<ContentPagesAdminPage />);
    await waitFor(() => screen.getByText("CPMAI Study Guide"));
    // Decline first
    vi.spyOn(window, "confirm").mockReturnValueOnce(false);
    fireEvent.click(screen.getByText("Delete"));
    expect(mockedAdmin.delete).not.toHaveBeenCalled();
    // Then confirm
    vi.spyOn(window, "confirm").mockReturnValueOnce(true);
    mockedAdmin.list.mockResolvedValueOnce([]);  // reload after delete
    fireEvent.click(screen.getByText("Delete"));
    await waitFor(() => {
      expect(mockedAdmin.delete).toHaveBeenCalledWith(1);
    });
  });

  it("surfaces API errors as an alert", async () => {
    mockedAdmin.list.mockRejectedValueOnce(new Error("network down"));
    render(<ContentPagesAdminPage />);
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/network down/);
    });
  });
});
