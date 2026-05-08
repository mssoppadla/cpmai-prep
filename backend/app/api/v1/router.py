"""Aggregate API router."""
from fastapi import APIRouter
from app.api.v1.endpoints import (
    auth, users, payments, exam_sets, exams, leads, assistant, content,
    pricing,
)
from app.api.v1.endpoints.admin.router import admin_router

api_router = APIRouter()
api_router.include_router(auth.router,      prefix="/auth",      tags=["auth"])
api_router.include_router(users.router,     prefix="/users",     tags=["users"])
api_router.include_router(payments.router,  prefix="/payments",  tags=["payments"])
api_router.include_router(exam_sets.router, prefix="/exam-sets", tags=["exam-sets"])
api_router.include_router(exams.router,     prefix="/exams",     tags=["exams"])
api_router.include_router(leads.router,     prefix="/leads",     tags=["leads"])
api_router.include_router(assistant.router, prefix="/assistant", tags=["assistant"])
api_router.include_router(content.router,   prefix="/content",   tags=["content"])
api_router.include_router(pricing.router,   prefix="/pricing",   tags=["pricing"])
api_router.include_router(admin_router,     prefix="/admin")
