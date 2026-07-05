"""Outbound transactional email via SMTP (Hostinger).

Stdlib-only (``smtplib`` + ``email.message``) — no new dependency. All
config is read at send time from the runtime settings store so the
Hostinger mailbox credentials rotate without a redeploy.

Fail-soft contract: every send is best-effort. Failures (bad creds,
network, no template) are logged and swallowed — they must NEVER break
the request that triggered them (a landing-form sign-up still succeeds
even if the offer email can't go out).
"""
import re
import ssl
import smtplib
from email.message import EmailMessage

import structlog

from app.core.settings_store import settings_store

log = structlog.get_logger("email")

_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")

# Placeholders an admin can use in a template subject/body. Surfaced in
# the admin editor as a cheat-sheet; kept here as the source of truth.
SUPPORTED_PLACEHOLDERS = (
    "name", "email", "offer_code", "offer_valid_until",
    "enroll_url", "brand_name",
)


def render_template(template: str, ctx: dict) -> str:
    """Substitute ``{{key}}`` placeholders with values from ``ctx``.

    Unknown placeholders are left verbatim (a typo stays visible rather
    than silently blanking the copy). Values are stringified; ``None``
    renders as an empty string.
    """
    def repl(m: "re.Match") -> str:
        key = m.group(1)
        if key not in ctx:
            return m.group(0)
        v = ctx[key]
        return "" if v is None else str(v)
    return _PLACEHOLDER.sub(repl, template or "")


def _html_to_text(html: str) -> str:
    """Cheap HTML → text fallback for the multipart/alternative plain
    part. Not a real parser — just enough so text-only clients (and spam
    filters that penalise HTML-only mail) get readable content."""
    text = re.sub(r"<\s*br\s*/?>", "\n", html, flags=re.I)
    text = re.sub(r"</\s*(p|div|tr|h[1-6])\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() or "Please view this email in an HTML-capable client."


def send_email(to: str, subject: str, html_body: str,
               attachments: list[dict] | None = None) -> bool:
    """Send a single HTML email. Returns True on success, False on any
    failure or when SMTP isn't configured yet.

    ``attachments``: optional list of ``{path, filename, mime_type}``
    entries whose paths have ALREADY been verified by
    app.services.email.attachments.resolve_attachment_paths — this
    function reads them as-is and never does its own path math.
    """
    host     = settings_store.get_str("email.smtp_host", "")
    port     = settings_store.get_int("email.smtp_port", 465)
    use_ssl  = settings_store.get_bool("email.smtp_use_ssl", True)
    username = settings_store.get_str("email.smtp_username", "")
    password = settings_store.get_str("email.smtp_password", "")
    from_addr = settings_store.get_str("email.from_address", username)
    from_name = settings_store.get_str("email.from_name", "")

    if not (host and from_addr and to):
        log.warning("email.send_skipped_unconfigured",
                    has_host=bool(host), has_from=bool(from_addr),
                    has_to=bool(to))
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_addr}>" if from_name else from_addr
    msg["To"] = to
    msg.set_content(_html_to_text(html_body))
    msg.add_alternative(html_body, subtype="html")

    # Attach pre-verified files (lifecycle automations). A read failure
    # aborts the send — delivering a mail without the PDF the admin
    # promised is worse than a visible failure the dispatcher retries.
    for att in (attachments or []):
        try:
            data = open(att["path"], "rb").read()
        except OSError as e:
            log.error("email.attachment_read_failed",
                      path=att.get("path"), error=str(e))
            return False
        maintype, _, subtype = (att.get("mime_type")
                                or "application/octet-stream").partition("/")
        msg.add_attachment(data, maintype=maintype or "application",
                           subtype=subtype or "octet-stream",
                           filename=att.get("filename") or "attachment")

    try:
        if use_ssl:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=20) as s:
                if username and password:
                    s.login(username, password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as s:
                s.starttls(context=ssl.create_default_context())
                if username and password:
                    s.login(username, password)
                s.send_message(msg)
        log.info("email.sent", to=to, subject=subject)
        return True
    except Exception as e:  # noqa: BLE001 — fail-soft by design
        log.error("email.send_failed", to=to, error=str(e))
        return False


def build_ctx(db, *, name: str | None, email: str) -> dict:
    """Assemble the placeholder context for a recipient.

    Resolves the admin-designated shared offer code (``email.auto_offer_code``)
    and its ``valid_until`` (the "active for 24 hours" window managed on
    the OfferCode row in /admin/offer-codes).
    """
    from app.models.offer import OfferCode

    code = settings_store.get_str("email.auto_offer_code", "").strip()
    valid_until = ""
    if code:
        row = (db.query(OfferCode)
               .filter(OfferCode.code == code.upper()).first())
        if row and row.valid_until:
            valid_until = row.valid_until.strftime("%d %b %Y, %H:%M UTC")
    enroll_url = settings_store.get_str("email.enroll_url", "") or "/"
    brand = settings_store.get_str("site.brand_name", "CPMAI Prep")
    return {
        "name": (name or "there"),
        "email": email,
        "offer_code": code,
        "offer_valid_until": valid_until,
        "enroll_url": enroll_url,
        "brand_name": brand,
    }


def select_template(db, source: str | None):
    """Pick the active template for a lead ``source`` (intent), falling
    back to the default (``source IS NULL``) template. Newest active row
    wins when duplicates exist. Returns None if nothing is active."""
    from app.models.email_template import EmailTemplate

    base = db.query(EmailTemplate).filter(EmailTemplate.is_active.is_(True))
    if source:
        tpl = (base.filter(EmailTemplate.source == source)
               .order_by(EmailTemplate.id.desc()).first())
        if tpl:
            return tpl
    return (base.filter(EmailTemplate.source.is_(None))
            .order_by(EmailTemplate.id.desc()).first())


def send_lead_offer_email(lead_id: int) -> bool:
    """Background-task entrypoint: render + send the auto-offer email for
    a captured lead.

    Opens its OWN DB session — the request session is already closed by
    the time a FastAPI BackgroundTask runs. On success, writes a
    ``lead.offer_email_sent`` audit event so the endpoint's 24h
    anti-spam guard can see prior sends.
    """
    from app.core.database import SessionLocal
    from app.models.lead import Lead
    from app.core.audit import audit_log

    with SessionLocal() as db:
        lead = db.get(Lead, lead_id)
        if not lead:
            return False
        source = (lead.source.value
                  if hasattr(lead.source, "value") else str(lead.source))
        tpl = select_template(db, source)
        if not tpl:
            log.warning("email.no_template", source=source, lead_id=lead_id)
            return False
        ctx = build_ctx(db, name=lead.name, email=lead.email)
        subject = render_template(tpl.subject, ctx)
        html = render_template(tpl.html_body, ctx)
        ok = send_email(lead.email, subject, html)
        if ok:
            audit_log(db, None, "lead.offer_email_sent",
                      {"lead_id": lead_id, "email": lead.email,
                       "offer_code": ctx.get("offer_code") or None})
        return ok
