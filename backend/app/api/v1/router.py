"""Aggregate API router."""
from fastapi import APIRouter
from app.api.v1.endpoints import (
    auth, users, payments, exam_sets, exams, leads, assistant, content,
    cms_public, lms_public, pricing,
    webhooks_zoom, tracking,
)
from app.api.v1.endpoints.admin.router import admin_router

api_router = APIRouter()
api_router.include_router(auth.router,       prefix="/auth",      tags=["auth"])
api_router.include_router(users.router,      prefix="/users",     tags=["users"])
api_router.include_router(payments.router,   prefix="/payments",  tags=["payments"])
api_router.include_router(exam_sets.router,  prefix="/exam-sets", tags=["exam-sets"])
api_router.include_router(exams.router,      prefix="/exams",     tags=["exams"])
api_router.include_router(leads.router,      prefix="/leads",     tags=["leads"])
# Adblocker-safe alias: /leads is on EasyList's tracking filters and gets
# blocked client-side by uBlock Origin / Brave / Firefox-with-strict-mode
# BEFORE the request even leaves the browser, surfacing as a generic
# "TypeError: Failed to fetch" with no server-side trace. The "Talk to
# a human → Request callback" widget submits real prospects, so we MUST
# bypass that filter. Same router mounted at a neutral path; frontend
# uses contact-request, /leads stays around for any external integrations
# that may already point at it.
api_router.include_router(leads.router,      prefix="/contact-request", tags=["leads"])
api_router.include_router(assistant.router,  prefix="/assistant", tags=["assistant"])
api_router.include_router(content.router,    prefix="/content",   tags=["content"])
api_router.include_router(cms_public.router, prefix="/cms",       tags=["cms"])
api_router.include_router(lms_public.router, prefix="/lms",       tags=["lms"])
api_router.include_router(pricing.router,    prefix="/pricing",   tags=["pricing"])
api_router.include_router(webhooks_zoom.router, prefix="/webhooks", tags=["webhooks", "zoom"])
# Visitor-insights ingest — batched POST from the SPA tracker.
# No prefix; the endpoint itself is "/track".
api_router.include_router(tracking.router,   tags=["tracking"])
api_router.include_router(admin_router,      prefix="/admin")
