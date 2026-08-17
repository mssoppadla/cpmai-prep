"""Invoice engine — PDF generation + buyer email with owner CC.

Flow (docs: payments multi-gateway spec, invoice addendum):
  * organic capture — activate_subscription_for_payment marks the row
    ``queued`` synchronously (so the verify-vs-webhook race can't send
    twice) and spawns ``queue_invoice_email``; the thread renders the
    PDF and sends via the existing SMTP mailer.
  * manual grant — admin ticks "payment received" (+ optionally "send
    invoice") on the grant form; the endpoint records a
    provider_name="manual" captured Payment and queues the same email.
  * admin resend / download — /admin/payments/{id}/invoice endpoints
    call ensure_invoice_pdf / send_invoice_email directly.

The PDF lives at UPLOAD_ROOT/invoices/<invoice_number>.pdf — OUTSIDE
the public /uploads static mount's document classes (PDFs there are
token-gated anyway); admin download goes through the authed endpoint.

Everything here is fail-soft: an invoice problem must never break a
payment capture.
"""
from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from pathlib import Path

import structlog
from sqlalchemy.orm import Session

from app.core.settings_store import settings_store
from app.models.payment import Payment
from app.models.plan import Plan
from app.models.user import User

log = structlog.get_logger("invoice")


def invoice_dir() -> Path:
    root = Path(os.environ.get("UPLOAD_ROOT", "/app/uploads")).resolve()
    d = root / "invoices"
    d.mkdir(parents=True, exist_ok=True)
    return d


def invoice_path(payment: Payment) -> Path | None:
    if not payment.invoice_number:
        return None
    return invoice_dir() / f"{payment.invoice_number}.pdf"


def _amount_str(minor: int | None, currency: str | None) -> str:
    return f"{(minor or 0) / 100:.2f} {currency or 'INR'}"


def _pdf_safe(s: str) -> str:
    """fpdf's built-in Helvetica is latin-1 only. Map the common
    typographic characters admins paste (em-dash, curly quotes, ₹) to
    ASCII look-alikes and strip anything else non-encodable, so a
    settings edit can never crash invoice generation."""
    table = {"—": "-", "–": "-", "‘": "'", "’": "'",
             "“": '"', "”": '"', "₹": "Rs.",
             " ": " ", "…": "..."}
    for src, dst in table.items():
        s = s.replace(src, dst)
    return s.encode("latin-1", "replace").decode("latin-1")


def _product_desc(plan) -> str:
    """'CPMAI Full Prep — Exam Bundle' — name plus the humanized
    bundle_type the pricing page shows, so the invoice says WHAT was
    bought (exam bundle vs live class vs course), not just a name."""
    if plan is None:
        return "Plan access"
    kind = (plan.bundle_type or "").replace("_", " ").strip().title()
    return f"{plan.name} — {kind}" if kind else plan.name


def _account_label(db: Session, payment: Payment) -> str:
    """Human name of the gateway ACCOUNT that took the money — Personal
    vs Company Razorpay matters for reconciliation, so the invoice and
    the admin table both show it."""
    if payment.provider_config_id:
        from app.models.payment_provider import PaymentProviderConfig
        row = db.get(PaymentProviderConfig, payment.provider_config_id)
        if row is not None:
            base = row.display_name or row.name or payment.provider_name
            return f"{base} ({payment.provider_name})"
    return payment.provider_name or "manual"


def ensure_invoice_pdf(db: Session, payment: Payment) -> Path:
    """Assign an invoice number (first call only) and render the PDF if
    the file doesn't exist yet. Idempotent; commits the number."""
    if not payment.invoice_number:
        year = (payment.created_at or datetime.now(timezone.utc)).year
        payment.invoice_number = f"INV-{year}-{payment.id:06d}"
        db.commit()

    path = invoice_dir() / f"{payment.invoice_number}.pdf"
    if path.exists():
        return path

    user = db.get(User, payment.user_id)
    plan = db.get(Plan, payment.plan_id) if payment.plan_id else None

    desc = _product_desc(plan)
    breakdown_consistent = (
        payment.base_amount_paise and payment.discount_paise
        and (payment.base_amount_paise - payment.discount_paise
             == payment.amount_paise))
    rows = []
    if breakdown_consistent:
        rows.append((desc, _amount_str(payment.base_amount_paise,
                                       payment.currency)))
        rows.append((f"Discount ({payment.offer_code or 'offer'})",
                     "-" + _amount_str(payment.discount_paise,
                                       payment.currency)))
    else:
        if payment.discount_paise and payment.offer_code:
            desc = f"{desc} (offer {payment.offer_code} applied)"
        rows.append((desc, _amount_str(payment.amount_paise,
                                       payment.currency)))

    _render_invoice_pdf(
        path,
        invoice_number=payment.invoice_number,
        issued=(payment.created_at or datetime.now(timezone.utc)),
        bill_name=(user.name if user is not None else None),
        bill_email=(user.email if user is not None else None),
        rows=rows,
        total=_amount_str(payment.amount_paise, payment.currency),
        paid_via=_account_label(db, payment),
        order_ref=payment.provider_order_id,
        payment_ref=payment.provider_payment_id,
    )
    log.info("invoice.pdf_generated", payment_id=payment.id,
             invoice_number=payment.invoice_number)
    return path


def _render_invoice_pdf(path: Path, *, invoice_number: str, issued,
                        bill_name: "str | None", bill_email: "str | None",
                        rows: list, total: str,
                        paid_via: "str | None" = None,
                        order_ref: "str | None" = None,
                        payment_ref: "str | None" = None) -> None:
    """Shared layout for payment AND ad-hoc invoices — one format
    everywhere (business header from settings, INVOICE/RECEIPT block,
    wrapped line items, footer)."""
    business = settings_store.get_str("invoice.business_name",
                                      "CPMAI Exam Prep")
    address = settings_store.get_str("invoice.business_address", "")
    footer = settings_store.get_str("invoice.footer_note",
                                    "Thank you for your purchase.")

    from fpdf import FPDF
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, _pdf_safe(business), new_x="LMARGIN", new_y="NEXT")
    if address:
        pdf.set_font("Helvetica", "", 9)
        for line in address.splitlines():
            pdf.cell(0, 5, _pdf_safe(line), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, "INVOICE / RECEIPT", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Invoice no: {invoice_number}",
             new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Date: {issued.strftime('%d %b %Y')}",
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, "Billed to", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    if bill_name:
        pdf.cell(0, 6, _pdf_safe(bill_name), new_x="LMARGIN", new_y="NEXT")
    if bill_email:
        pdf.cell(0, 6, _pdf_safe(bill_email), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # Line items — one plan per payment today. Long plan names (live
    # class titles etc.) must WRAP inside the description cell, never
    # overlap the amount column — so every row is drawn with a measured
    # multi_cell + an amount cell of matching height.
    def _item_row(desc_text: str, amount_text: str, bold: bool = False):
        pdf.set_font("Helvetica", "B" if bold else "", 10)
        safe = _pdf_safe(desc_text)
        lines = pdf.multi_cell(120, 7, safe, dry_run=True, output="LINES")
        h = 7 * max(1, len(lines))
        x, y = pdf.get_x(), pdf.get_y()
        pdf.multi_cell(120, 7, safe, border=1, new_x="RIGHT", new_y="TOP")
        pdf.set_xy(x + 120, y)
        pdf.cell(60, h, amount_text, border=1,
                 new_x="LMARGIN", new_y="NEXT")

    _item_row("Description", "Amount", bold=True)
    for row_desc, row_amount in rows:
        _item_row(row_desc, row_amount)
    _item_row("Total paid", total, bold=True)
    pdf.ln(4)

    pdf.set_font("Helvetica", "", 9)
    if paid_via:
        pdf.cell(0, 5, _pdf_safe(f"Paid via: {paid_via}"),
                 new_x="LMARGIN", new_y="NEXT")
    if order_ref:
        pdf.cell(0, 5, _pdf_safe(f"Order ref: {order_ref}"),
                 new_x="LMARGIN", new_y="NEXT")
    if payment_ref:
        pdf.cell(0, 5, _pdf_safe(f"Payment ref: {payment_ref}"),
                 new_x="LMARGIN", new_y="NEXT")
    if footer:
        pdf.ln(6)
        pdf.set_font("Helvetica", "I", 9)
        pdf.multi_cell(0, 5, _pdf_safe(footer))

    pdf.output(str(path))


def send_invoice_email(db: Session, payment: Payment,
                       force: bool = False) -> bool:
    """Render (if needed) and email the invoice to the buyer, CC'ing the
    owner address. Updates invoice_email_status. Synchronous — callers
    on a request path should go through queue_invoice_email instead."""
    if payment.invoice_email_status == "sent" and not force:
        return True
    user = db.get(User, payment.user_id)
    if user is None or not user.email:
        payment.invoice_email_status = "skipped"
        db.commit()
        return False
    try:
        pdf_path = ensure_invoice_pdf(db, payment)
    except Exception as e:
        log.error("invoice.pdf_failed", payment_id=payment.id, error=str(e))
        payment.invoice_email_status = "failed"
        db.commit()
        return False

    business = settings_store.get_str("invoice.business_name",
                                      "CPMAI Exam Prep")
    cc = settings_store.get_str("email.invoice_cc_address", "") or None
    plan = db.get(Plan, payment.plan_id) if payment.plan_id else None
    plan_name = _product_desc(plan) if plan is not None else "your plan"
    # Subject + body are admin-editable (Settings → invoice.email_subject
    # / invoice.email_body) with {{placeholder}} substitution via the
    # same template engine the email automations use.
    subject, html = _invoice_email_content({
        "user_name": user.name or "there",
        "user_email": user.email,
        "plan_name": plan_name,
        "amount": _amount_str(payment.amount_paise, payment.currency),
        "currency": payment.currency,
        "invoice_number": payment.invoice_number,
        "business_name": business,
        "order_ref": payment.provider_order_id or "",
    })
    from app.services.email.mailer import send_email
    ok = send_email(
        user.email, subject, html,
        attachments=[{"path": str(pdf_path),
                      "filename": f"{payment.invoice_number}.pdf",
                      "mime_type": "application/pdf"}],
        cc=cc,
    )
    payment.invoice_email_status = "sent" if ok else "failed"
    payment.invoice_email_sent_at = (datetime.now(timezone.utc)
                                     if ok else payment.invoice_email_sent_at)
    db.commit()
    log.info("invoice.email_result", payment_id=payment.id, ok=ok, cc=cc)
    return ok


def _invoice_email_content(ctx: dict) -> tuple:
    """(subject, html) from the admin-editable templates — shared by
    payment and ad-hoc invoice mails so the copy stays in ONE place."""
    from app.services.email.mailer import render_template
    subject = render_template(
        settings_store.get_str(
            "invoice.email_subject",
            "{{business_name}} — Invoice {{invoice_number}}"), ctx)
    html = render_template(
        settings_store.get_str(
            "invoice.email_body",
            "<p>Hi {{user_name}},</p>"
            "<p>Thank you for your payment of <b>{{amount}}</b> "
            "for <b>{{plan_name}}</b>.</p>"
            "<p>Your invoice <b>{{invoice_number}}</b> is attached.</p>"
            "<p>— {{business_name}}</p>"), ctx)
    return subject, html


# ── Ad-hoc invoices (fully off-platform sales) ───────────────────────

def ensure_adhoc_invoice_pdf(db: Session, inv) -> Path:
    """Same layout as payment invoices; separate M-numbered series so
    payment-derived numbers can never collide. Idempotent."""
    if not inv.invoice_number:
        year = (inv.created_at or datetime.now(timezone.utc)).year
        inv.invoice_number = f"INV-{year}-M{inv.id:05d}"
        db.commit()
    path = invoice_dir() / f"{inv.invoice_number}.pdf"
    if path.exists():
        return path
    _render_invoice_pdf(
        path,
        invoice_number=inv.invoice_number,
        issued=(inv.created_at or datetime.now(timezone.utc)),
        bill_name=inv.buyer_name,
        bill_email=inv.buyer_email,
        rows=[(inv.description, _amount_str(inv.amount_minor,
                                            inv.currency))],
        total=_amount_str(inv.amount_minor, inv.currency),
        payment_ref=inv.gateway_reference,
    )
    log.info("invoice.adhoc_pdf_generated", adhoc_id=inv.id,
             invoice_number=inv.invoice_number)
    return path


def send_adhoc_invoice_email(db: Session, inv, force: bool = False) -> bool:
    """Email an ad-hoc invoice with the same templates + CC list as
    payment invoices. Synchronous (admin-triggered, result shown)."""
    if inv.email_status == "sent" and not force:
        return True
    if not inv.buyer_email:
        inv.email_status = "skipped"
        db.commit()
        return False
    try:
        pdf_path = ensure_adhoc_invoice_pdf(db, inv)
    except Exception as e:
        log.error("invoice.adhoc_pdf_failed", adhoc_id=inv.id, error=str(e))
        inv.email_status = "failed"
        db.commit()
        return False
    business = settings_store.get_str("invoice.business_name",
                                      "CPMAI Exam Prep")
    subject, html = _invoice_email_content({
        "user_name": inv.buyer_name or "there",
        "user_email": inv.buyer_email,
        "plan_name": inv.description,
        "amount": _amount_str(inv.amount_minor, inv.currency),
        "currency": inv.currency,
        "invoice_number": inv.invoice_number,
        "business_name": business,
        "order_ref": inv.gateway_reference or "",
    })
    from app.services.email.mailer import send_email
    cc = settings_store.get_str("email.invoice_cc_address", "") or None
    ok = send_email(
        inv.buyer_email, subject, html,
        attachments=[{"path": str(pdf_path),
                      "filename": f"{inv.invoice_number}.pdf",
                      "mime_type": "application/pdf"}],
        cc=cc,
    )
    inv.email_status = "sent" if ok else "failed"
    inv.email_sent_at = (datetime.now(timezone.utc)
                         if ok else inv.email_sent_at)
    db.commit()
    log.info("invoice.adhoc_email_result", adhoc_id=inv.id, ok=ok)
    return ok


def queue_invoice_email(payment_id: int) -> None:
    """Fire-and-forget send on a daemon thread with its own session —
    keeps SMTP latency off the webhook/verify request path. Callers must
    have already stamped invoice_email_status='queued' and committed
    (that stamp is the double-send guard under the verify/webhook race)."""
    def _run() -> None:
        from app.core.database import SessionLocal
        db = SessionLocal()
        try:
            p = db.get(Payment, payment_id)
            if p is not None:
                send_invoice_email(db, p, force=True)
        except Exception as e:
            log.error("invoice.queue_failed", payment_id=payment_id,
                      error=str(e))
        finally:
            db.close()
    threading.Thread(target=_run, name=f"invoice-{payment_id}",
                     daemon=True).start()
