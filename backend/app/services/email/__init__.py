"""Transactional email (lead → auto-offer reply via Hostinger SMTP)."""
from app.services.email.mailer import (  # noqa: F401
    send_email,
    render_template,
    build_ctx,
    select_template,
    send_lead_offer_email,
)
