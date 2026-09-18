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


# ================================================================ labs
# Registry-driven lab shapes (see app/core/labs_registry.py).

class LabSectionOut(BaseModel):
    id: str
    title: str


class LabPlanRef(BaseModel):
    slug: str
    name: str


class LabIndexOut(BaseModel):
    """One lab as the /labs index, the admin Labs screen and the plan
    checkboxes see it. Anonymous view — no per-user entitlement."""
    slug: str
    key: str
    title: str
    default_title: str
    group: str
    domain: str
    blurb: str
    minutes: int
    enabled: bool
    gated: bool
    cuttable: bool
    frame: str                     # "content" | "viewport" — how the page sizes the iframe
    mode: str
    free_upto: str
    free_upto_index: int
    sections: list[LabSectionOut]
    plans: list[LabPlanRef]
    teaches: list[str]

    @classmethod
    def from_access(cls, acc) -> "LabIndexOut":
        lab = acc.lab
        return cls(
            slug=lab.slug, key=lab.key, title=acc.settings.title,
            default_title=lab.title, group=lab.group, domain=lab.domain,
            blurb=lab.blurb, minutes=lab.minutes,
            enabled=acc.settings.enabled, gated=lab.gated,
            cuttable=lab.cuttable, frame=lab.frame, mode=acc.settings.mode,
            free_upto=acc.settings.free_upto,
            free_upto_index=lab.section_index(acc.settings.free_upto),
            sections=[LabSectionOut(id=s.id, title=s.title) for s in lab.sections],
            plans=[LabPlanRef(**p) for p in acc.plans],
            teaches=list(lab.teaches),
        )


class LabAccessOut(BaseModel):
    """The decision for one visitor: what to render and how to embed."""
    slug: str
    title: str
    enabled: bool
    mode: str
    full: bool
    reason: str                    # ok | signin | plan | disabled
    free_upto_index: int           # last free section (index), -1 = none
    sections: list[LabSectionOut]
    locked_sections: list[LabSectionOut]
    plans: list[LabPlanRef]
    embed_token: str

    @classmethod
    def from_access(cls, acc, embed_token: str) -> "LabAccessOut":
        lab = acc.lab
        return cls(
            slug=lab.slug, title=acc.settings.title,
            enabled=acc.settings.enabled, mode=acc.settings.mode,
            full=acc.full, reason=acc.reason,
            free_upto_index=acc.free_upto_index,
            sections=[LabSectionOut(id=s.id, title=s.title) for s in lab.sections],
            locked_sections=[LabSectionOut(id=s.id, title=s.title)
                             for s in acc.locked_sections],
            plans=[LabPlanRef(**p) for p in acc.plans],
            embed_token=embed_token,
        )
