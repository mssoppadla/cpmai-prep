"""Chat endpoint with daily limits and quota headers."""
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session
from app.core.deps import get_db, get_optional_user
from app.core.exceptions import GuardrailViolation
from app.core.limiter import limiter
from app.models.user import User
from app.schemas.assistant import AssistantRequest, AssistantResponse
from app.services.assistant.orchestrator import AssistantOrchestrator
from app.services.assistant.guardrails import AssistantGuardrails

router = APIRouter()
guardrails = AssistantGuardrails()


@router.post("/chat", response_model=AssistantResponse)
@limiter.limit("20/minute")
def chat(payload: AssistantRequest, request: Request, response: Response,
         user: User | None = Depends(get_optional_user),
         db: Session = Depends(get_db)):
    user_id = user.id if user else None
    anon_id = getattr(request.state, "anon_id", None)

    quota = guardrails.check_daily_limit(user_id=user_id, anon_id=anon_id)
    payload.user_id = user_id
    payload.anon_id = anon_id

    result = AssistantOrchestrator(db).handle(payload, user)

    response.headers["X-Chat-Quota-Used"]      = str(quota["used"])
    response.headers["X-Chat-Quota-Limit"]     = str(quota["limit"])
    response.headers["X-Chat-Quota-Remaining"] = str(quota["remaining"])
    response.headers["X-Chat-Quota-Reset"]     = quota["reset_at_utc"]
    return result
