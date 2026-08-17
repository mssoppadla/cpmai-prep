/**
 * Ad-hoc Invoices page — list rendering, the create form, and the
 * email-status column.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

const mockList = vi.fn();
const mockCreate = vi.fn();
vi.mock("@/lib/api", async (importOriginal) => {
  const orig = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...orig,
    admin: {
      ...orig.admin,
      adhocInvoices: {
        list: (...a: unknown[]) => mockList(...a),
        create: (...a: unknown[]) => mockCreate(...a),
        downloadPdf: vi.fn(),
        send: vi.fn(),
      },
    },
  };
});

import AdminInvoicesPage from "@/app/admin/invoices/page";

const ROW = {
  id: 1, invoice_number: "INV-2026-M00001",
  buyer_name: "Geethu Rs", buyer_email: "rsgeethu1986@gmail.com",
  description: "Live CPMAI Classes — Aug batch",
  amount_minor: 9912, currency: "INR",
  gateway_reference: "UPI-RRN-913413077065",
  email_status: "sent" as const, email_sent_at: "2026-08-17T10:00:00Z",
  created_at: "2026-08-17T09:00:00Z",
};

beforeEach(() => {
  mockList.mockReset(); mockCreate.mockReset();
});

describe("AdminInvoicesPage", () => {
  it("renders invoice rows with number, buyer, amount, email status", async () => {
    mockList.mockResolvedValue({ total: 1, items: [ROW] });
    render(<AdminInvoicesPage />);
    await waitFor(() =>
      expect(screen.getByText("INV-2026-M00001")).toBeInTheDocument());
    expect(screen.getByText("Geethu Rs")).toBeInTheDocument();
    expect(screen.getByText("INR 99.12")).toBeInTheDocument();
    expect(screen.getByText(/✓ sent/)).toBeInTheDocument();
    expect(screen.getByText(/UPI-RRN-913413077065/)).toBeInTheDocument();
  });

  it("shows the empty state", async () => {
    mockList.mockResolvedValue({ total: 0, items: [] });
    render(<AdminInvoicesPage />);
    await waitFor(() =>
      expect(screen.getByText(/No ad-hoc invoices yet/)).toBeInTheDocument());
  });

  it("create form validates and submits minor units", async () => {
    mockList.mockResolvedValue({ total: 0, items: [] });
    mockCreate.mockResolvedValue({
      ...ROW, id: 2, invoice_number: "INV-2026-M00002", email_sent: true,
    });
    render(<AdminInvoicesPage />);
    await waitFor(() =>
      expect(screen.getByText(/No ad-hoc invoices yet/)).toBeInTheDocument());
    fireEvent.click(screen.getByText("+ Create invoice"));

    // Empty form → validation error, no API call
    fireEvent.click(screen.getByText(/^Create/));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Fill buyer/);
    expect(mockCreate).not.toHaveBeenCalled();

    fireEvent.change(screen.getByPlaceholderText(/CPMAI Exam Bundle/), {
      target: { value: "CPMAI Exam Bundle — Exam Bundle" } });
    const [nameInput] = screen.getAllByRole("textbox");
    fireEvent.change(nameInput, { target: { value: "Mike Lam" } });
    fireEvent.change(document.querySelector("input[type=email]")!, {
      target: { value: "mike.coco@gmail.com" } });
    fireEvent.change(document.querySelector("input[type=number]")!, {
      target: { value: "170.00" } });
    fireEvent.click(screen.getByText(/^Create/));

    await waitFor(() => expect(mockCreate).toHaveBeenCalledWith(
      expect.objectContaining({
        buyer_name: "Mike Lam",
        buyer_email: "mike.coco@gmail.com",
        amount_minor: 17000,
        currency: "INR",
        send_email: true,
      })));
    await waitFor(() =>
      expect(screen.getByText(/INV-2026-M00002 created and emailed/))
        .toBeInTheDocument());
  });
});
