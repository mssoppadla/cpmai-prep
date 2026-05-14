"""Tool implementations for the agentic orchestrator.

Each tool lives in its own module and **registers itself at import
time** via ``registry.register(...)``. This module just imports each
tool module so the registry gets populated as a side-effect of
importing ``app.services.assistant.agentic.tools``.

Adding a new tool:

  1. Drop a new file in this directory.
  2. Define the tool class + a ``register(MyTool())`` call.
  3. Add an import line below.

The order of imports below is the order tools appear in the router's
tools[] array — usually doesn't matter, but keeping it stable makes
log output deterministic, which helps when debugging "why did the
router pick X over Y".
"""
# noqa: F401 — these imports are side-effecting (they call register())
from app.services.assistant.agentic.tools import (
    faq_search,
    content_search,
    pricing_lookup,
    account_state,
    user_insights,
    pmi_reference,
    human_escalation,
)
