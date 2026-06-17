"""Admin CRUD for the lead → auto-offer email templates.

Each template is selected by lead ``source`` (intent), with the
``source IS NULL`` row as the default fallback. The body is raw HTML
(inline styles) authored here; ``{{placeholders}}`` are filled at send
time by ``app.services.email.mailer``.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.deps import get_db, get_admin_user
from app.core.exceptions import NotFoundError
from app.core.audit import audit_log
from app.models.user import User
from app.models.email_template import EmailTemplate
from app.schemas.email_template import (
    EmailTemplateCreate, EmailTemplateUpdate, EmailTemplateOut,
    EmailTemplateTestIn,
)
from app.services.email import mailer

router = APIRouter()


@router.get("", response_model=list[EmailTemplateOut])
def list_templates(db: Session = Depends(get_db)):
    return (db.query(EmailTemplate)
            .order_by(EmailTemplate.source.is_(None), EmailTemplate.source,
                      EmailTemplate.id.desc())
            .all())


@router.post("", response_model=EmailTemplateOut, status_code=201)
def create_template(payload: EmailTemplateCreate,
                    db: Session = Depends(get_db),
                    admin: User = Depends(get_admin_user)):
    row = EmailTemplate(
        source=payload.source,
        subject=payload.subject,
        html_body=payload.html_body,
        is_active=payload.is_active,
    )
    db.add(row); db.commit(); db.refresh(row)
    audit_log(db, admin.id, "email_template.created",
              {"id": row.id, "source": row.source})
    return row


@router.patch("/{template_id}", response_model=EmailTemplateOut)
def update_template(template_id: int, payload: EmailTemplateUpdate,
                    db: Session = Depends(get_db),
                    admin: User = Depends(get_admin_user)):
    row = db.get(EmailTemplate, template_id)
    if not row:
        raise NotFoundError()
    data = payload.model_dump(exclude_unset=True)
    # Normalise an empty/whitespace source to NULL (the default template).
    if "source" in data and data["source"] is not None:
        data["source"] = data["source"].strip() or None
    for k, v in data.items():
        setattr(row, k, v)
    db.commit(); db.refresh(row)
    audit_log(db, admin.id, "email_template.updated",
              {"id": template_id, "fields": list(data.keys())})
    return row


@router.delete("/{template_id}", status_code=204)
def delete_template(template_id: int,
                    db: Session = Depends(get_db),
                    admin: User = Depends(get_admin_user)):
    row = db.get(EmailTemplate, template_id)
    if not row:
        raise NotFoundError()
    db.delete(row); db.commit()
    audit_log(db, admin.id, "email_template.deleted", {"id": template_id})


@router.post("/{template_id}/test")
def send_test(template_id: int, payload: EmailTemplateTestIn,
              db: Session = Depends(get_db),
              admin: User = Depends(get_admin_user)):
    """Render this template with a sample context + the live offer
    settings, and send it to the admin (or an override recipient) so
    they can eyeball the result in a real inbox."""
    row = db.get(EmailTemplate, template_id)
    if not row:
        raise NotFoundError()
    to = (payload.to or "").strip() or admin.email
    ctx = mailer.build_ctx(
        db, name=f"{admin.name or 'there'} (preview)", email=to)
    subject = mailer.render_template(row.subject, ctx)
    html = mailer.render_template(row.html_body, ctx)
    ok = mailer.send_email(to, subject, html)
    audit_log(db, admin.id, "email_template.test_sent",
              {"id": template_id, "to": to, "ok": ok})
    return {"sent": ok, "to": to}
