"""Admin sub-router. Every route below is gated by get_admin_user."""
from fastapi import APIRouter, Depends
from app.core.deps import get_admin_user
from app.api.v1.endpoints.admin import (
    questions, exam_sets, leads, settings as settings_ep,
    llm_providers, payment_providers, users, faqs,
    plans, offers, rag, chat_history, geoip,
    pricing as pricing_admin,
    assistant_drift,
    assistant_flow,
    anonymous_traffic,
    subscriptions,
    content_pages,
    cms_ai,
)

admin_router = APIRouter(dependencies=[Depends(get_admin_user)])
admin_router.include_router(users.router,        prefix="/users",         tags=["admin"])
admin_router.include_router(questions.router,    prefix="/questions",     tags=["admin"])
admin_router.include_router(exam_sets.router,    prefix="/exam-sets",     tags=["admin"])
admin_router.include_router(leads.router,        prefix="/leads",         tags=["admin"])
admin_router.include_router(faqs.router,         prefix="/faqs",          tags=["admin"])
admin_router.include_router(content_pages.router, prefix="/content-pages", tags=["admin"])
admin_router.include_router(cms_ai.router,        prefix="/cms-ai",        tags=["admin"])
admin_router.include_router(settings_ep.router,  prefix="/settings",      tags=["admin"])
admin_router.include_router(llm_providers.router,    prefix="/llm-providers",     tags=["admin"])
admin_router.include_router(payment_providers.router,prefix="/payment-providers", tags=["admin"])
admin_router.include_router(plans.router,        prefix="/plans",         tags=["admin"])
admin_router.include_router(offers.router,       prefix="/offer-codes",   tags=["admin"])
admin_router.include_router(rag.router,          prefix="/rag",           tags=["admin"])
admin_router.include_router(chat_history.router, prefix="/chat-history",  tags=["admin"])
admin_router.include_router(geoip.router,        prefix="/geoip",         tags=["admin"])
admin_router.include_router(pricing_admin.router, prefix="/pricing",      tags=["admin"])
admin_router.include_router(assistant_drift.router, prefix="/assistant-drift", tags=["admin"])
admin_router.include_router(assistant_flow.router,  prefix="/assistant-flow",  tags=["admin"])
admin_router.include_router(anonymous_traffic.router, prefix="/anonymous-traffic", tags=["admin"])
# Subscriptions admin: routes registered WITHOUT a prefix here because
# they live at two different paths — /admin/users/{id}/subscriptions
# (list + grant) and /admin/subscriptions/{id}/{extend,revoke}. The
# router file declares each path absolutely so both surfaces are
# co-located in one module.
admin_router.include_router(subscriptions.router, tags=["admin"])
