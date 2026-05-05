import re

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"\+?\d[\d\s\-]{8,}\d")
CARD_RE  = re.compile(r"\b(?:\d[ -]*?){13,19}\b")


def redact(text: str | None) -> str:
    if not text:
        return text or ""
    text = EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    text = PHONE_RE.sub("[REDACTED_PHONE]", text)
    text = CARD_RE.sub("[REDACTED_CARD]", text)
    return text
