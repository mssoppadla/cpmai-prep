"""Visitor-insights tracking sub-services.

Owns the parsers + helpers used by /api/v1/track to turn a raw SPA
event payload into a normalised journey_events row. The actual write
goes through tracking_service.emit_event() in the parent module.
"""
