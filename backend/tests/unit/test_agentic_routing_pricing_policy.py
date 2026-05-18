"""Routing-policy contract tests for pricing/cost questions.

Background: in production we observed the agentic router consistently
picking ``pmi_reference`` for questions like "How much does the official
CPMAI exam cost?" — and that tool returns a URL hedge ("visit pmi.org
for fees") instead of the actual number, even though we have a curated
FAQ entry with the live fee. The misrouting traced back to two signals
the router LLM was reading:

  1. ``pmi_reference.description`` listed "exam fee" as a trigger
  2. ``faq_search.description`` didn't mention pricing at all
  3. ``DEFAULT_ROUTER_SYSTEM`` had a generic rule ("for pricing use
     pricing_lookup") that didn't disambiguate OUR-product cost vs
     EXAM cost

This file pins the three signals so a future refactor of any tool
description or the router system prompt can't silently regress
pricing routing. Behavioural validation (actual LLM routing on real
queries) is done out-of-band by manual local LLM testing — these
tests are the regression net.
"""
from __future__ import annotations

from app.services.assistant.agentic.orchestrator import DEFAULT_ROUTER_SYSTEM
from app.services.assistant.agentic.tools.faq_search import FaqSearchTool
from app.services.assistant.agentic.tools.pmi_reference import PmiReferenceTool


# ----------------------------------------------------------- tool descriptions

def test_faq_search_description_steers_pricing_questions():
    """faq_search must advertise itself as the destination for
    PRICING / FEE / COST questions so the router LLM can pick it
    over pmi_reference. Without these keywords the router falls
    back to pmi_reference (which returns a URL hedge)."""
    desc = FaqSearchTool().description.lower()
    # Pricing keywords — at least these three must be present
    assert "pricing" in desc, "faq_search must mention 'pricing'"
    assert "exam fee" in desc, "faq_search must mention 'exam fee'"
    assert "cost" in desc, "faq_search must mention 'cost'"
    # FIRST-CHOICE wording — explicit preference signal to the router
    assert "first choice" in desc or "prefer this" in desc, (
        "faq_search description should explicitly nudge the router "
        "to prefer it over pmi_reference for ambiguous cases")


def test_pmi_reference_description_warns_off_pricing_questions():
    """pmi_reference must EXPLICITLY tell the router not to use it
    for cost questions. Without this guard the router sees 'PMI
    official' + 'CPMAI' in the description and reads 'cost' from
    the user query, then picks pmi_reference — yielding a hedge."""
    desc = PmiReferenceTool().description.lower()
    assert "do not use" in desc and (
        "pricing" in desc or "cost" in desc
    ), ("pmi_reference description must explicitly warn the router "
         "against using it for pricing/cost questions")
    assert "faq_search" in desc, (
        "pmi_reference description should point the router at "
        "faq_search as the correct destination for cost questions")


def test_pmi_reference_intent_param_warns_against_cost():
    """Belt-and-braces — even if the router gets past the top-level
    description and starts inspecting the intent enum, the parameter
    description itself should steer away from 'how much does it cost'."""
    intent_param = (PmiReferenceTool()
                    .parameters_schema["properties"]["intent"]
                    ["description"].lower())
    assert "how much" in intent_param or "cost" in intent_param, (
        "The intent param description should explicitly call out "
        "cost questions as off-policy for pmi_reference")


# ----------------------------------------------------------- router system prompt

def test_default_router_system_has_explicit_pricing_routing_rule():
    """DEFAULT_ROUTER_SYSTEM must contain an unambiguous PRICING
    ROUTING rule that disambiguates:
      - OUR subscription cost → pricing_lookup
      - PMI exam fee          → faq_search
      - PMI registration URL  → pmi_reference
    The combination of these three is what eliminates the hedge."""
    prompt = DEFAULT_ROUTER_SYSTEM.lower()
    # Rule heading marker
    assert "pricing routing" in prompt, (
        "DEFAULT_ROUTER_SYSTEM must have a discrete 'pricing routing' "
        "section so the rule is visually scannable and not buried")
    # Three explicit routes
    assert "pricing_lookup" in prompt, "pricing_lookup must be named"
    assert "faq_search" in prompt, "faq_search must be named"
    assert "pmi_reference" in prompt, "pmi_reference must be named"
    # The negative rule — pmi_reference is NOT for cost
    assert "never use pmi_reference" in prompt or (
        "do not use" in prompt and "pmi_reference" in prompt
        and ("cost" in prompt or "fee" in prompt)
    ), ("DEFAULT_ROUTER_SYSTEM must contain a hard 'never use "
         "pmi_reference for cost/fee questions' instruction")


def test_default_router_system_distinguishes_our_product_from_pmi_exam():
    """The pricing-routing rule must distinguish 'OUR subscription
    cost' from 'PMI exam fee' — without that distinction the router
    can't reliably pick between pricing_lookup and faq_search."""
    prompt = DEFAULT_ROUTER_SYSTEM.lower()
    # OUR product signal
    assert any(s in prompt for s in (
        "our subscription", "our product", "platform cost",
        "subscription / how much", "exam bundle",
    )), ("DEFAULT_ROUTER_SYSTEM must call out OUR-product cost "
          "questions distinctly from PMI exam fee questions")
    # PMI exam signal
    assert any(s in prompt for s in (
        "pmi exam fee", "official cpmai exam",
        "certification cost", "member vs non-member",
    )), ("DEFAULT_ROUTER_SYSTEM must call out PMI exam fee "
          "questions distinctly from OUR-product cost questions")
