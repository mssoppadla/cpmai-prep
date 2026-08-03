"""Admin config for the interactive labs (public /labs pages).

One lab today — the Threshold Explorer. Its dataset lives as a JSON
blob in system_settings (`labs.threshold_explorer`), so there is no
migration and no file on disk; saving here goes live on the public
page's next load."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.audit import audit_log
from app.core.deps import get_admin_user, get_db
from app.core.exceptions import ValidationError
from app.core.settings_store import settings_store
from app.models.user import User
from app.schemas.labs import DEFAULT_THRESHOLD_EXPLORER, ThresholdExplorerConfig

router = APIRouter()

KEY = "labs.threshold_explorer"


def load_threshold_config() -> ThresholdExplorerConfig:
    """Stored config, or the built-in demo when nothing was saved yet.
    A malformed stored value (direct DB edit) falls back to the demo
    rather than 500-ing the public page."""
    raw = settings_store.get(KEY)
    if not raw:
        return DEFAULT_THRESHOLD_EXPLORER
    try:
        return ThresholdExplorerConfig.model_validate(raw)
    except Exception:
        return DEFAULT_THRESHOLD_EXPLORER


def validate_semantics(cfg: ThresholdExplorerConfig) -> None:
    """Cross-field rules pydantic can't express per-field."""
    if cfg.mode == "cases":
        if len(cfg.cases) < 2:
            raise ValidationError(
                "Interactive mode needs at least 2 cases "
                "(one line per case: score, actual).")
        labels = {c.actual for c in cfg.cases}
        if labels == {1} or labels == {0}:
            raise ValidationError(
                "Interactive mode needs both classes — add at least one "
                "positive (1) and one negative (0) case, otherwise the "
                "curves are undefined.")
    else:  # counts
        if cfg.tp + cfg.fp + cfg.fn + cfg.tn == 0:
            raise ValidationError(
                "Snapshot mode needs at least one non-zero count.")


@router.get("/threshold-explorer", response_model=ThresholdExplorerConfig)
def get_threshold_config():
    return load_threshold_config()


@router.put("/threshold-explorer", response_model=ThresholdExplorerConfig)
def save_threshold_config(payload: ThresholdExplorerConfig,
                          db: Session = Depends(get_db),
                          admin: User = Depends(get_admin_user)):
    validate_semantics(payload)
    settings_store.set(KEY, payload.model_dump(mode="json"),
                       db=db, updated_by=admin.id)
    audit_log(db, admin.id, "labs.threshold_explorer_updated",
              {"mode": payload.mode, "cases": len(payload.cases)})
    return payload
