"""Admin sub-router. Every route below is gated by get_admin_user."""
from fastapi import APIRouter, Depends
from app.core.deps import get_admin_user
from app.api.v1.endpoints.admin import (
    questions, exam_sets, leads, settings as settings_ep,
    llm_providers, payment_providers, users, faqs,
)

admin_router = APIRouter(dependencies=[Depends(get_admin_user)])
admin_router.include_router(users.router,        prefix="/users",         tags=["admin"])
admin_router.include_router(questions.router,    prefix="/questions",     tags=["admin"])
admin_router.include_router(exam_sets.router,    prefix="/exam-sets",     tags=["admin"])
admin_router.include_router(leads.router,        prefix="/leads",         tags=["admin"])
admin_router.include_router(faqs.router,         prefix="/faqs",          tags=["admin"])
admin_router.include_router(settings_ep.router,  prefix="/settings",      tags=["admin"])
admin_router.include_router(llm_providers.router,    prefix="/llm-providers",     tags=["admin"])
admin_router.include_router(payment_providers.router,prefix="/payment-providers", tags=["admin"])
