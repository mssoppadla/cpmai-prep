"""Public content endpoints — CPMAI phases, FAQs, and admin-edited landing copy."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.deps import get_db
from app.core.settings_store import settings_store
from app.models.faq import FaqItem
from app.models.topic import Topic
from app.schemas.faq import FaqOut

router = APIRouter()


@router.get("/topics")
def list_topics(db: Session = Depends(get_db)):
    return [
        {"id": t.id, "code": t.code, "name": t.name, "order": t.order}
        for t in db.query(Topic).order_by(Topic.order).all()
    ]


@router.get("/faqs", response_model=list[FaqOut])
def list_faqs(db: Session = Depends(get_db)):
    """Public FAQs ordered by display_order. Inactive items are hidden."""
    rows = (db.query(FaqItem)
            .filter(FaqItem.is_active.is_(True))
            .order_by(FaqItem.display_order, FaqItem.id)
            .all())
    return rows


@router.get("/landing")
def landing_copy():
    """Admin-editable landing-page text bits.

    Keys backed by system_settings so admins can tweak them in
    /admin/settings without redeploying.
    """
    return {
        "lead_section_heading": settings_store.get_str(
            "landing.lead_section_heading",
            "Start with our free CPMAI study guide",
        ),
        "lead_cta_text": settings_store.get_str(
            "landing.lead_cta_text",
            "Get the free guide",
        ),
        "lead_post_submit_route": settings_store.get_str(
            "landing.lead_post_submit_route",
            "/exams",
        ),
    }
