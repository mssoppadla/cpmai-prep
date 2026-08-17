"""Ad-hoc invoices — for sales that happened fully off-platform.

The operator types buyer name/email, what was sold, and the amount;
the PDF uses the exact same layout/settings as payment invoices but a
separate M-numbered series (INV-<year>-M<id>) so numbers derived from
payment ids can never collide. Email goes out with the same
invoice.email_subject/body templates + CC list.
"""
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class AdhocInvoice(Base):
    __tablename__ = "adhoc_invoices"

    id             = Column(Integer, primary_key=True)
    invoice_number = Column(String(40), unique=True, nullable=False)
    buyer_name     = Column(String(160), nullable=False)
    buyer_email    = Column(String(240), nullable=False)
    description    = Column(String(500), nullable=False)
    amount_minor   = Column(Integer, nullable=False)   # paise/cents
    currency       = Column(String(8), nullable=False, default="INR")
    # Real gateway/bank reference if any (pay_..., PayPal txn, UPI RRN).
    gateway_reference = Column(String(120), nullable=True)
    email_status   = Column(String(16), nullable=True)  # sent|failed|skipped
    email_sent_at  = Column(DateTime(timezone=True), nullable=True)
    created_by     = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())
