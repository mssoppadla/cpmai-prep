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
        # Dedicated privacy contact — falls back to support_email if
        # not configured. Privacy Policy page links here directly.
        "privacy_email": settings_store.get_str(
            "site.privacy_email",
            settings_store.get_str("site.support_email", ""),
        ),
        "contact_phone": settings_store.get_str("site.contact_phone", ""),
        # Social handles — empty string = platform hidden in UI.
        # When a value is set, it MUST be the full profile URL
        # (https://...) — both the footer link and the JSON-LD
        # `sameAs` SEO array consume it as-is.
        "linkedin_url":  settings_store.get_str("site.linkedin_url",  ""),
        "youtube_url":   settings_store.get_str("site.youtube_url",   ""),
        "twitter_url":   settings_store.get_str("site.twitter_url",   ""),
        "instagram_url": settings_store.get_str("site.instagram_url", ""),
        "facebook_url":  settings_store.get_str("site.facebook_url",  ""),
        "threads_url":   settings_store.get_str("site.threads_url",   ""),
        "tiktok_url":    settings_store.get_str("site.tiktok_url",    ""),
        "github_url":    settings_store.get_str("site.github_url",    ""),
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
        # Suggested starter prompts shown in the empty-state of the
        # assistant widget. Admin-editable as a list so they can
        # rotate the suggestions seasonally / based on what learners
        # actually ask. List of strings — frontend renders each as a
        # clickable chip that pre-fills the input.
        "assistant_try_asking_suggestions": _try_asking_suggestions(),
        # Anonymous-state copy shown to NOT-signed-in visitors when they
        # open the chat widget. Same setting the backend guardrail
        # raises (so the value stays in one place), but exposed here too
        # so the frontend can render it before the user even tries to
        # send — avoiding an extra round-trip + a frustrating "type, then
        # learn you need to sign in" flow. Admins edit this once and
        # both the inline copy AND the backend-side error message
        # update in lockstep.
        "assistant_anonymous_no_identity_message": settings_store.get_str(
            "assistant.anonymous_no_identity_message",
            "Please sign in to continue chatting. Anonymous chat needs "
            "a browser identifier — refresh the page or sign in.",
        ),
    }


def _try_asking_suggestions() -> list[str]:
    """Read the configured suggestion list; sanitise so a misconfigured
    setting can't break the widget render.

    Defaults match the previously-hardcoded EmptyState entries so the
    widget looks identical before any admin edits.
    """
    raw = settings_store.get("assistant.try_asking_suggestions", None)
    if isinstance(raw, list):
        clean = [str(x).strip() for x in raw
                 if isinstance(x, str) and str(x).strip()]
        if clean:
            return clean
    # Fallback — same wording the hardcoded EmptyState used.
    return [
        "What's the difference between Phase 2 and Phase 3?",
        "How much is the exam bundle?",
        "Where do I register for the actual exam?",
    ]


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
        # Hero block on the public landing page (/). Both headline +
        # subtitle moved here so non-engineering admins can A/B copy
        # without a redeploy. Defaults match the previously-shipped
        # marketing copy.
        "hero_headline": settings_store.get_str(
            "landing.hero_headline",
            "Pass the CPMAI certification on your first attempt",
        ),
        "hero_subtitle": settings_store.get_str(
            "landing.hero_subtitle",
            "Realistic mock exams · AI-powered coaching · Detailed answer "
            "reasoning for every question across all 6 CPMAI phases.",
        ),
        # Banner shown on /exams when the visitor is NOT signed in.
        # Plain-text (not HTML) — frontend renders with the same styling
        # as before; admins can change the wording but not the markup.
        "exams_anonymous_banner": settings_store.get_str(
            "exams.anonymous_banner",
            "You're not signed in. Free sets are open — start one "
            "anonymously and you'll see your result immediately (just "
            "not saved to a dashboard). Sign in to save attempts; "
            "subscribe to unlock premium sets.",
        ),
    }
