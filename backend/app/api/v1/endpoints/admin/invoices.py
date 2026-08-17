"""Ad-hoc invoices — operator-entered invoices for off-platform sales.

Same PDF layout, numbering style (separate M-series), email templates,
and CC list as automatic payment invoices; the operator just types the
buyer + line item. Mounted under the admin router (get_admin_user gated
at the router level).
"""
from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.audit import audit_log
from app.core.deps import get_admin_user, get_db
from app.core.exceptions import NotFoundError
from app.models.adhoc_invoice import AdhocInvoice
from app.models.user import User

router = APIRouter()


class AdhocInvoiceIn(BaseModel):
    buyer_name: str = Field(..., min_length=1, max_length=160)
    buyer_email: str = Field(..., min_length=3, max_length=240,
                             pattern=r".+@.+\..+")
    description: str = Field(..., min_length=3, max_length=500)
    amount_minor: int = Field(..., ge=1, le=100_000_000,
                              description="Minor units (paise/cents).")
    currency: str = Field("INR", min_length=3, max_length=8)
    gateway_reference: str | None = Field(None, max_length=120)
    send_email: bool = Field(
        False, description="Email the PDF to the buyer now (CC list "
                           "from email.invoice_cc_address).")


def _out(inv: AdhocInvoice) -> dict:
    return {
        "id": inv.id,
        "invoice_number": inv.invoice_number,
        "buyer_name": inv.buyer_name,
        "buyer_email": inv.buyer_email,
        "description": inv.description,
        "amount_minor": inv.amount_minor,
        "currency": inv.currency,
        "gateway_reference": inv.gateway_reference,
        "email_status": inv.email_status,
        "email_sent_at": inv.email_sent_at,
        "created_at": inv.created_at,
    }


@router.get("")
def list_adhoc_invoices(db: Session = Depends(get_db),
                        limit: int = 50, offset: int = 0):
    q = db.query(AdhocInvoice).order_by(AdhocInvoice.id.desc())
    return {"total": q.count(),
            "items": [_out(i) for i in
                      q.offset(max(0, offset)).limit(min(200, limit)).all()]}


@router.post("", status_code=201)
def create_adhoc_invoice(payload: AdhocInvoiceIn,
                         db: Session = Depends(get_db),
                         admin: User = Depends(get_admin_user)):
    from app.services.invoice import (
        ensure_adhoc_invoice_pdf, send_adhoc_invoice_email,
    )
    inv = AdhocInvoice(
        invoice_number=f"PENDING-{admin.id}",   # replaced after flush
        buyer_name=payload.buyer_name.strip(),
        buyer_email=payload.buyer_email.strip().lower(),
        description=payload.description.strip(),
        amount_minor=payload.amount_minor,
        currency=payload.currency.upper(),
        gateway_reference=(payload.gateway_reference or "").strip() or None,
        created_by=admin.id,
    )
    db.add(inv)
    db.flush()                      # assigns id for the number
    inv.invoice_number = None       # let the service mint INV-YYYY-M#####
    ensure_adhoc_invoice_pdf(db, inv)
    sent = None
    if payload.send_email:
        sent = send_adhoc_invoice_email(db, inv)
    audit_log(db, admin.id, "admin.invoice.adhoc_created", {
        "adhoc_invoice_id": inv.id,
        "invoice_number": inv.invoice_number,
        "buyer_email": inv.buyer_email,
        "amount_minor": inv.amount_minor,
        "currency": inv.currency,
        "emailed": bool(sent),
    })
    return {**_out(inv), "email_sent": sent}


@router.get("/{invoice_id}/pdf")
def adhoc_invoice_pdf(invoice_id: int, db: Session = Depends(get_db)):
    inv = db.get(AdhocInvoice, invoice_id)
    if inv is None:
        raise NotFoundError()
    from app.services.invoice import ensure_adhoc_invoice_pdf
    path = ensure_adhoc_invoice_pdf(db, inv)
    return FileResponse(str(path), media_type="application/pdf",
                        filename=f"{inv.invoice_number}.pdf")


@router.post("/{invoice_id}/send")
def adhoc_invoice_send(invoice_id: int, db: Session = Depends(get_db)):
    inv = db.get(AdhocInvoice, invoice_id)
    if inv is None:
        raise NotFoundError()
    from app.services.invoice import send_adhoc_invoice_email
    ok = send_adhoc_invoice_email(db, inv, force=True)
    return {"sent": ok, "invoice_number": inv.invoice_number,
            "email_status": inv.email_status}
