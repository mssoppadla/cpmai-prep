"""Interactive-lab configs. Currently one lab: the Threshold Explorer
(public page /labs/threshold-explorer). Stored as a single JSON blob in
system_settings under `labs.threshold_explorer` — admin-editable via
/admin/labs/threshold-explorer, no schema migration needed."""
from typing import Literal

from pydantic import BaseModel, Field


class ThresholdCase(BaseModel):
    """One data point: the model's score and the ground-truth label."""
    score: float = Field(ge=0.0, le=1.0)
    actual: Literal[0, 1]


class ThresholdExplorerConfig(BaseModel):
    """The lab's dataset.

    mode = "cases":  each case is re-thresholded live — slider, matrix,
                     ROC and PR curves all active.
    mode = "counts": only the four confusion-matrix totals; the public
                     page hides the slider and curves (four totals carry
                     no per-case scores to re-threshold).
    """
    mode: Literal["cases", "counts"] = "cases"
    threshold: float = Field(0.5, ge=0.01, le=0.99,
                             description="Where the slider starts.")
    cases: list[ThresholdCase] = Field(default_factory=list, max_length=500)
    tp: int = Field(0, ge=0)
    fp: int = Field(0, ge=0)
    fn: int = Field(0, ge=0)
    tn: int = Field(0, ge=0)


# The dataset served until an admin saves their own — a small, readable
# demo with both classes spread across the score range so every widget
# (slider, matrix, ROC, PR) has something meaningful to show.
DEFAULT_THRESHOLD_EXPLORER = ThresholdExplorerConfig(
    mode="cases",
    threshold=0.52,
    cases=[
        ThresholdCase(score=s, actual=a) for s, a in [
            (0.04, 0), (0.09, 0), (0.13, 0), (0.18, 0), (0.22, 1),
            (0.27, 0), (0.33, 0), (0.38, 1), (0.42, 0), (0.47, 1),
            (0.51, 0), (0.55, 1), (0.58, 0), (0.62, 1), (0.66, 1),
            (0.71, 0), (0.75, 1), (0.79, 1), (0.84, 1), (0.88, 0),
            (0.92, 1), (0.95, 1), (0.98, 1),
        ]
    ],
)
