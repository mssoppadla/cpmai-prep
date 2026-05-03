"""Aggregate API router. Endpoint modules to be added per the spec."""
from fastapi import APIRouter

api_router = APIRouter()

# TODO: include routers as endpoints are implemented:
# from app.api.v1.endpoints import auth, users, payments, quizzes, exams, \
#     analytics, content, assistant, data_export, audit
# from app.api.v1.endpoints.admin.router import admin_router
# api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
# ... etc.
# api_router.include_router(admin_router, prefix="/admin", tags=["admin"])

@api_router.get("/")
def root():
    return {"message": "CPMAI Prep API v1"}
