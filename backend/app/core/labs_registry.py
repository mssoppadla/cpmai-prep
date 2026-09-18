"""The single registry of interactive labs / visual walkthroughs.

Everything about a lab that the product needs to know — its public
slug, the settings keys it is configured under, the sections an admin
can cut a free preview at, the embed asset it renders from — lives
HERE and nowhere else. Adding a lab is one entry in ``LABS`` plus its
HTML asset under ``frontend/labs-assets/``; the admin Labs screen, the
plan checkboxes, the /labs index, the access endpoint and the settings
validators all derive from this list.

Access modes (Settings → ``labs.<key>_access``)
------------------------------------------------
  free     everyone, full page (launch default for every lab)
  signin   any logged-in account, full page; plans ignored
  preview  page served up to and including ``labs.<key>_free_upto``;
           the rest is served only to plan members
  plan     header only; body served only to plan members

"Plan member" = active, non-revoked, non-expired subscription whose
plan lists the lab slug in ``Plan.perks["labs"]`` (legacy subscriptions
with no plan_id unlock everything, mirroring the exam-set paywall).

Labs without an embed asset (``asset=None``) are bespoke React pages
that cannot be truncated server-side; they are always free and the
admin screen shows no access controls for them.
"""
from __future__ import annotations

from dataclasses import dataclass, field


ACCESS_MODES = ("free", "signin", "preview", "plan")
PERK_LABS_KEY = "labs"          # Plan.perks[PERK_LABS_KEY] = ["slug", ...]


@dataclass(frozen=True)
class LabSection:
    id: str
    title: str


@dataclass(frozen=True)
class LabDef:
    slug: str            # public URL: /labs/<slug>
    key: str             # settings prefix: labs.<key>_enabled / _title / _access / _free_upto
    title: str           # default display name (admin-editable)
    group: str           # "interactive" | "walkthrough" — grouping on /labs
    domain: str          # CPMAI domain chip
    blurb: str           # card + meta description
    minutes: int
    sections: tuple[LabSection, ...] = ()
    asset: str | None = None      # frontend/labs-assets/<slug>.html, embedded via /labs/embed/<slug>
    teaches: tuple[str, ...] = ()  # JSON-LD "teaches"
    order: int = 100

    @property
    def gated(self) -> bool:
        return self.asset is not None

    @property
    def cuttable(self) -> bool:
        """Preview mode needs sections to cut at."""
        return self.gated and len(self.sections) > 1

    def setting(self, suffix: str) -> str:
        return f"labs.{self.key}_{suffix}"

    def section_index(self, section_id: str | None) -> int:
        """Index of the last FREE section for preview mode; -1 = none."""
        if not section_id:
            return -1
        for i, s in enumerate(self.sections):
            if s.id == section_id:
                return i
        return -1


def _secs(*pairs: tuple[str, str]) -> tuple[LabSection, ...]:
    return tuple(LabSection(i, t) for i, t in pairs)


LABS: tuple[LabDef, ...] = (
    LabDef(
        slug="metrics-lab", key="metrics_lab", order=10,
        title="Classification Metrics Lab", group="interactive",
        domain="D-IV · Model Evaluation", minutes=10,
        blurb=("Underfitting, overfitting, the imbalance trap — trigger each "
               "failure mode, watch train vs test data, the bias–variance "
               "target and both AUC curves react, and learn the remedy."),
        teaches=("Precision and recall", "Confusion matrix",
                 "Overfitting and underfitting", "Bias-variance tradeoff",
                 "ROC and precision-recall curves", "Class imbalance"),
    ),
    LabDef(
        slug="data-pipeline-navigator", key="pipeline_lab", order=20,
        title="Data Pipeline Simulator", group="interactive",
        domain="D-III · Data Understanding & Preparation", minutes=25,
        blurb=("Run one fraud-detection project through the whole CPMAI data "
               "lifecycle — profile the 4 V's, validate at the source, govern "
               "lineage, label, size, explore, cleanse, encode, balance and "
               "split. Twelve live simulations; every decision carries "
               "forward into a generated readiness report."),
        asset="data-pipeline-navigator.html",
        teaches=("The 4 V's of big data", "Data quality dimensions",
                 "Data integration frameworks", "Reconciliation and checksums",
                 "Data lineage", "Data labelling", "Curse of dimensionality",
                 "Exploratory Data Analysis", "Target encoding",
                 "SMOTE and class imbalance", "Data splitting and leakage"),
    ),
    LabDef(
        slug="phase-2-3-walkthrough", key="walkthrough", order=30,
        title="Data Understanding and Data Preparation", group="walkthrough",
        domain="D-III · Data Understanding & Preparation", minutes=45,
        blurb=("Every Phase II & III activity with its owner, one continuous "
               "clinic-chatbot example, two go/no-go gates, the Phase III "
               "master sequence and 360+ tap-to-explain terms."),
        asset="phase-2-3-walkthrough.html",
        sections=_secs(
            ("s1", "Identify data SMEs"),
            ("s2", "Define required data"),
            ("s3", "Identify data sources & locations"),
            ("cx", "Privacy, compliance & access"),
            ("s10", "Govern & design the pipelines"),
            ("s4", "Coordinate AI workspace & infrastructure"),
            ("s5", "Choose the data integration framework"),
            ("s6", "Gather, land & reconcile the data"),
            ("s7", "Oversee data evaluation + EDA"),
            ("s8", "Gate 2 · Does the data meet solution needs"),
            ("s9", "Convey data understanding to leadership"),
            ("s9r", "Phase III — practical implementation steps"),
            ("s13", "Transform (a) — Cleanse"),
            ("s14", "Transform (b) — Filter"),
            ("s15", "Transform (c) — Label"),
            ("s16", "Split first — evaluation isolation"),
            ("s18", "Transform (d) — Feature engineering"),
            ("s17", "Transform (e) — Balance & enlarge"),
            ("s19", "Same word, different thing — five name clashes"),
            ("s20", "Gate 3 · Validate & gate"),
            ("s21", "Looking ahead · Operate"),
            ("abbr", "Abbreviations"),
        ),
        teaches=("CPMAI Phase II Data Understanding",
                 "CPMAI Phase III Data Preparation",
                 "Data governance and lineage", "Data pipelines (ELT)",
                 "Data cleansing, filtering and labelling",
                 "Train/validation/test splitting", "Class balancing",
                 "Feature engineering", "Go/no-go decision gates"),
    ),
    LabDef(
        slug="ml-training-pipeline", key="ml_pipeline", order=40,
        title="ML Training Pipeline, Illustrated", group="walkthrough",
        domain="D-IV · Model Development", minutes=20,
        blurb=("From a ready dataset through the seven-step training cycle, "
               "nested cross-validation, aggregation and the final retrain — "
               "every number on the page consistent with the next."),
        asset="ml-training-pipeline.html",
        sections=_secs(
            ("sec1", "1 · Data ready"),
            ("sec2", "2 · Training & hyperparameter tuning"),
            ("sec2b", "2b · Aggregate, choose, retrain"),
            ("sec3", "3 · Outputs & logs"),
            ("sec4", "4 · Reading the scores"),
            ("legend", "Legend & notation"),
            ("abbr", "Abbreviations"),
        ),
        teaches=("Training, validation and test sets", "K-fold cross-validation",
                 "Nested cross-validation", "Hyperparameter tuning",
                 "Epochs and batches", "Gradient descent and backpropagation",
                 "Early stopping and checkpoints", "Overfitting and underfitting"),
    ),
    LabDef(
        slug="nested-cross-validation", key="nested_cv", order=50,
        title="Nested Cross-Validation, Every Loop", group="walkthrough",
        domain="D-IV · Model Development", minutes=15,
        blurb=("K = 5 outer folds, I = 10 inner folds, 3 hyperparameter sets — "
               "all 156 training runs written out, one score per run, one "
               "honest estimate, one shipped model."),
        asset="nested-cross-validation.html",
        sections=_secs(
            ("step1", "Step 1 · Outer loop"),
            ("step2", "Step 2 · Inner loop"),
            ("step2b", "Step 2b · Inside one run"),
            ("step3", "Step 3 · Round K1 scores"),
            ("step4", "Step 4 · Round K1 verdict"),
            ("step5", "Step 5 · All five rounds"),
            ("step6", "Step 6 · The shipped model"),
            ("step6b", "6b · When teams do less"),
            ("step7", "Step 7 · Reading the scores"),
            ("abbr", "Abbreviations"),
        ),
        teaches=("Nested cross-validation", "Outer and inner folds",
                 "Hyperparameter selection", "Data leakage between folds",
                 "Honest performance estimates", "Final model retraining"),
    ),
)

LAB_BY_SLUG: dict[str, LabDef] = {lab.slug: lab for lab in LABS}
LAB_BY_KEY: dict[str, LabDef] = {lab.key: lab for lab in LABS}
LAB_SLUGS: frozenset[str] = frozenset(LAB_BY_SLUG)


def get_lab(slug: str) -> LabDef | None:
    return LAB_BY_SLUG.get(slug)


def normalise_perk_labs(perks: dict | None) -> list[str]:
    """The lab slugs a plan unlocks, deduplicated and registry-checked.
    Unknown slugs are dropped silently on read (a lab removed from the
    registry must not break an existing plan)."""
    raw = (perks or {}).get(PERK_LABS_KEY) or []
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for s in raw:
        if isinstance(s, str) and s in LAB_BY_SLUG and s not in out:
            out.append(s)
    return out
