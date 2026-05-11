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


@router.get("/site")
def site_chrome():
    """Site-wide header/footer config — admin-editable via /admin/settings.

    Empty-string values are intentionally allowed; the frontend hides UI
    elements (social links, support email) when they're empty so admins can
    progressively reveal channels.
    """
    return {
        "brand_name": settings_store.get_str(
            "site.brand_name", "CPMAI Prep",
        ),
        "tagline": settings_store.get_str(
            "site.tagline",
            "Pass the CPMAI certification on your first attempt.",
        ),
        "support_email": settings_store.get_str("site.support_email", ""),
        "linkedin_url": settings_store.get_str("site.linkedin_url", ""),
        "youtube_url": settings_store.get_str("site.youtube_url", ""),
        "twitter_url": settings_store.get_str("site.twitter_url", ""),
        "copyright_text": settings_store.get_str(
            "site.copyright_text",
            "© 2026 CPMAI Prep. All rights reserved.",
        ),
        "show_pricing_link": bool(
            settings_store.get("site.show_pricing_link", True),
        ),
        # End-user chat widget subtitle. Lives here (rather than under
        # /assistant/*) so the widget can render it without an extra
        # round-trip — site chrome is already fetched on every page.
        "assistant_widget_subtitle": settings_store.get_str(
            "assistant.widget_subtitle",
            "Grounded in our FAQ, pricing & question explanations",
        ),
    }


@router.get("/landing")
def landing_copy():
    """Admin-editable landing-page text bits.

    Keys backed by system_settings so admins can tweak them in
    /admin/settings without redeploying. Includes the upsell banner
    shown on the learner dashboard.
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
        "premium_upsell_title": settings_store.get_str(
            "landing.premium_upsell_title",
            "Get the full bank",
        ),
        "premium_upsell_body": settings_store.get_str(
            "landing.premium_upsell_body",
            "Premium unlocks all advanced sets, AI tutor with extended quota, "
            "and detailed performance analytics.",
        ),
    }
