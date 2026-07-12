"""Public content endpoints — CPMAI phases, ECO domains, FAQs, landing copy."""
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.core.deps import get_db
from app.core import domains as domain_registry
from app.core.settings_store import settings_store
from app.models.faq import FaqItem
from app.models.question import Question
from app.models.testimonial import Testimonial
from app.models.topic import Topic
from app.schemas.faq import FaqOut
from app.schemas.testimonial import TestimonialOut

router = APIRouter()


@router.get("/topics")
def list_topics(db: Session = Depends(get_db)):
    return [
        {"id": t.id, "code": t.code, "name": t.name, "order": t.order}
        for t in db.query(Topic).order_by(Topic.order).all()
    ]


@router.get("/domains")
def list_domains(db: Session = Depends(get_db)):
    """The five CPMAI ECO domains, with a live count of active questions
    tagged into each. The frontend uses this for the admin domain dropdown
    and the results-screen domain breakdown labels."""
    counts = dict(
        db.query(Question.domain, func.count(Question.id))
          .filter(Question.is_active.is_(True))
          .group_by(Question.domain)
          .all()
    )

    def active_count(d) -> int:
        # Count rows stored under any accepted spelling of this domain
        # (code is canonical, but legacy rows may hold the name/slug).
        total = 0
        for stored, n in counts.items():
            if domain_registry.get(stored) and domain_registry.get(stored).code == d.code:
                total += n
        return total

    return [
        {
            "code": d.code, "name": d.name, "slug": d.slug,
            "order": d.order, "weight": d.weight,
            "phase_codes": list(d.phase_codes),
            "active_question_count": active_count(d),
        }
        for d in domain_registry.all_domains()
    ]


@router.get("/faqs", response_model=list[FaqOut])
def list_faqs(db: Session = Depends(get_db)):
    """Public FAQs ordered by display_order. Inactive items are hidden."""
    rows = (db.query(FaqItem)
            .filter(FaqItem.is_active.is_(True))
            .order_by(FaqItem.display_order, FaqItem.id)
            .all())
    return rows


@router.get("/errors")
def error_pages_copy():
    """Admin-editable copy for the 404 / unexpected-error pages, plus
    the master toggle for the help-links block. The frontend embeds the
    same defaults as fallbacks so the error pages still render when the
    API itself is the thing that's down."""
    return {
        "not_found_title": settings_store.get_str(
            "errors.not_found_title",
            "Uh oh! You seem to have lost your way.",
        ),
        "not_found_body": settings_store.get_str(
            "errors.not_found_body",
            "Let us help you find what you were looking for:",
        ),
        "server_error_title": settings_store.get_str(
            "errors.server_error_title",
            "Something went wrong on our end",
        ),
        "server_error_body": settings_store.get_str(
            "errors.server_error_body",
            "Please try again — or jump back to one of these pages:",
        ),
        "show_help_links": bool(
            settings_store.get("errors.show_help_links", True),
        ),
    }


@router.get("/testimonials", response_model=list[TestimonialOut])
def list_testimonials(db: Session = Depends(get_db)):
    """Public testimonials for the landing carousel, ordered by
    display_order. Inactive rows are hidden."""
    rows = (db.query(Testimonial)
            .filter(Testimonial.is_active.is_(True))
            .order_by(Testimonial.display_order, Testimonial.id)
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
        "reddit_url":    settings_store.get_str("site.reddit_url",    ""),
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
        # Helper copy under the landing LinkedIn field (admin-configurable).
        "lead_linkedin_reason": settings_store.get_str(
            "landing.lead_linkedin_reason",
            "So we can serve you better and share relevant prep documents",
        ),
        # Heading for the "connect with me" social block under the
        # landing CTA. The social URLs themselves come from /content/site
        # (site.*_url). Empty heading hides just the label, not the icons.
        "connect_heading": settings_store.get_str(
            "landing.connect_heading",
            "Connect with me",
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
        # "Two steps to ace the exam" section under the hero — surfaces
        # both product lines (courses + mock exams). All copy is admin-
        # editable so the framing (e.g. "two ways" vs "two steps"), the
        # card titles/descriptions, and the CTA labels can change without
        # a redeploy. The card LINKS (/courses, /exams) stay in code.
        "paths_heading": settings_store.get_str(
            "landing.paths_heading",
            "Two steps to ace the exam",
        ),
        "paths_subtitle": settings_store.get_str(
            "landing.paths_subtitle",
            "First build deep understanding with structured courses, then "
            "prove you're exam-ready with realistic mock exams. Work through "
            "both to maximise your score.",
        ),
        "paths_course_title": settings_store.get_str(
            "landing.paths_course_title",
            "Step 1 · Structured courses",
        ),
        "paths_course_body": settings_store.get_str(
            "landing.paths_course_body",
            "Step-by-step lessons across all 6 CPMAI phases — video, "
            "downloadable resources, and a listen-anywhere podcast.",
        ),
        "paths_course_cta": settings_store.get_str(
            "landing.paths_course_cta",
            "Browse courses",
        ),
        "paths_exam_title": settings_store.get_str(
            "landing.paths_exam_title",
            "Step 2 · Mock exams",
        ),
        "paths_exam_body": settings_store.get_str(
            "landing.paths_exam_body",
            "Realistic, PMI-standard practice exams with per-question "
            "explanations and domain-level score breakdowns.",
        ),
        "paths_exam_cta": settings_store.get_str(
            "landing.paths_exam_cta",
            "Try a mock exam",
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
        # Live-class registration banner, rendered directly under the
        # hero subtitle. Fully admin-styleable (font size/style/colors +
        # optional pulse/blink attention animation) via /admin/landing-
        # banner. Disabled by default so nothing shows until the admin
        # configures a link.
        "live_banner_enabled": bool(
            settings_store.get("landing.live_banner_enabled", False),
        ),
        "live_banner_text": settings_store.get_str(
            "landing.live_banner_text",
            "Live CPMAI exam-prep classes are open — reserve your seat!",
        ),
        "live_banner_link_url": settings_store.get_str(
            "landing.live_banner_link_url", "",
        ),
        "live_banner_link_label": settings_store.get_str(
            "landing.live_banner_link_label", "Register now",
        ),
        "live_banner_font_size": _int_setting(
            "landing.live_banner_font_size", 16, lo=10, hi=48,
        ),
        "live_banner_font_style": settings_store.get_str(
            "landing.live_banner_font_style", "normal",
        ),
        "live_banner_font_color": settings_store.get_str(
            "landing.live_banner_font_color", "#312e81",
        ),
        "live_banner_bg_color": settings_store.get_str(
            "landing.live_banner_bg_color", "#e0e7ff",
        ),
        "live_banner_animation": settings_store.get_str(
            "landing.live_banner_animation", "none",
        ),
        # Banner buttons — registration (calendar/Zoom) + on-demand
        # training request (Google Form). Each independently toggled;
        # empty colors mean "automatic pairing" in the frontend.
        "live_banner_link_enabled": bool(
            settings_store.get("landing.live_banner_link_enabled", True),
        ),
        "live_banner_link_bg_color": settings_store.get_str(
            "landing.live_banner_link_bg_color", "",
        ),
        "live_banner_link_text_color": settings_store.get_str(
            "landing.live_banner_link_text_color", "",
        ),
        "live_banner_ondemand_enabled": bool(
            settings_store.get("landing.live_banner_ondemand_enabled", False),
        ),
        "live_banner_ondemand_label": settings_store.get_str(
            "landing.live_banner_ondemand_label",
            "Request on-demand training",
        ),
        "live_banner_ondemand_url": settings_store.get_str(
            "landing.live_banner_ondemand_url", "",
        ),
        "live_banner_ondemand_bg_color": settings_store.get_str(
            "landing.live_banner_ondemand_bg_color", "",
        ),
        "live_banner_ondemand_text_color": settings_store.get_str(
            "landing.live_banner_ondemand_text_color", "",
        ),
        # Testimonial carousel under the banner. Cards come from
        # /content/testimonials; these knobs control the section shell.
        "testimonials_enabled": bool(
            settings_store.get("landing.testimonials_enabled", True),
        ),
        "testimonials_heading": settings_store.get_str(
            "landing.testimonials_heading", "What our aspirants say",
        ),
        "testimonials_interval_ms": _int_setting(
            "landing.testimonials_interval_ms", 6000, lo=2000, hi=60000,
        ),
    }


def _int_setting(key: str, default: int, *, lo: int, hi: int) -> int:
    """Read an int setting defensively — a malformed value (or a string
    that slipped in) falls back to the default instead of crashing the
    public landing render."""
    raw = settings_store.get(key, default)
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return default
    return n if lo <= n <= hi else default
