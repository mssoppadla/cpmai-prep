"""Agentic-flow building blocks.

This package houses everything specific to the AGENTIC orchestration
flow — the router/tool-calling/synthesis pipeline that runs when
``settings.assistant.flow != "legacy"``. The legacy flow stays in
``app.services.assistant.handlers`` untouched.

Public surface:

  * :mod:`.types`     — Tool, ToolContext, ToolResult, ToolStatus
  * :mod:`.registry`  — singleton registry the agentic orchestrator
                        iterates over to build the router's tool
                        schema and dispatch tool calls
  * :mod:`.tools`     — per-tool modules (one file per tool); each
                        registers itself at import time

The orchestrator itself (LangGraph wiring) lands in a follow-up PR.
Until then this package is a self-contained tool library that's
importable + testable in isolation.
"""
