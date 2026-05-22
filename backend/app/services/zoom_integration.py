"""Zoom integration service — REST API client + Web SDK signing.

Two distinct auth surfaces Zoom requires, both read from settings_store
so the operator configures them via /admin/settings (no env vars):

  1. **Web SDK signing** (zoom.sdk_key + zoom.sdk_secret).
     The Meeting SDK that we embed in the browser (/sessions/{id}/live)
     needs a signed JWT in its constructor. We mint that JWT here using
     HMAC-SHA256 with the SDK Secret. The browser NEVER sees the secret
     — only the resulting signature.

  2. **REST API** for managing meetings (OAuth Server-to-Server).
     Three creds: zoom.account_id, zoom.oauth_client_id,
     zoom.oauth_client_secret. We hit /oauth/token, get a short-lived
     bearer, then call /users/me/meetings and friends.

These two SETS of credentials are independent — an operator may have
the SDK pair configured but not the REST API pair yet (or vice versa).
Each ZoomClient method probes the credentials it needs and raises a
clear ``ZoomNotConfigured`` if they're missing.

# Settings keys (configured via /admin/settings)

  zoom.sdk_key                   public-ish; used in the browser
  zoom.sdk_secret                secret — never sent to frontend
  zoom.account_id                Zoom OAuth account ID
  zoom.oauth_client_id           Zoom OAuth client ID
  zoom.oauth_client_secret       secret
  zoom.host_email                Zoom account email that hosts meetings

  zoom.api_base_url              optional override (default zoom.us)
  zoom.sdk_jwt_ttl_seconds       optional, default 1800 (30 min)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
import structlog

from app.core.settings_store import settings_store


log = structlog.get_logger("zoom_integration")


# ──────────────────────────────────────────────────────────────────────
# Errors
# ──────────────────────────────────────────────────────────────────────
class ZoomError(Exception):
    """Base class for Zoom integration errors. Don't raise this
    directly — use one of the subclasses below."""


class ZoomNotConfigured(ZoomError):
    """Settings_store is missing the credentials this operation needs.
    Surfaces to the admin UI as a 422 with a clear "Configure Zoom in
    /admin/settings first" message."""


class ZoomApiError(ZoomError):
    """The Zoom REST API returned a non-success response. Wraps the
    upstream status code + error body for operator triage."""

    def __init__(self, status: int, body: Any):
        super().__init__(f"Zoom API returned {status}: {body!r}")
        self.status = status
        self.body = body


# ──────────────────────────────────────────────────────────────────────
# Public dataclass returned to the endpoint layer.
# ──────────────────────────────────────────────────────────────────────
@dataclass
class CreatedMeeting:
    meeting_id: str          # numeric Zoom meeting ID (as string)
    join_url: str            # learners use the SDK token, NOT this URL
    start_url: str           # host link with embedded auth token


@dataclass
class SignedSDKToken:
    signature: str
    sdk_key: str
    meeting_number: str
    user_name: str
    role: int                # 0 = participant; 1 = host
    expires_at: datetime


# ──────────────────────────────────────────────────────────────────────
# The client.
# ──────────────────────────────────────────────────────────────────────
class ZoomClient:
    """Thin wrapper around the Zoom REST API + SDK signing.

    Stateless apart from the OAuth bearer cache. Safe to instantiate
    per-request; long-running processes can keep a singleton if needed.
    """

    def __init__(self):
        self._oauth_token: Optional[str] = None
        self._oauth_expires_at: float = 0  # monotonic seconds

    # ──────────────────── credential probes ────────────────────
    def _sdk_pair(self) -> tuple[str, str]:
        """Returns (sdk_key, sdk_secret). Raises ZoomNotConfigured if
        either is missing or empty."""
        key = settings_store.get_str("zoom.sdk_key", "")
        secret = settings_store.get_str("zoom.sdk_secret", "")
        if not key or not secret:
            raise ZoomNotConfigured(
                "Zoom SDK credentials missing. Configure zoom.sdk_key "
                "and zoom.sdk_secret in /admin/settings."
            )
        return key, secret

    def _oauth_creds(self) -> tuple[str, str, str]:
        """Returns (account_id, client_id, client_secret). Raises
        ZoomNotConfigured if any are missing."""
        account_id = settings_store.get_str("zoom.account_id", "")
        client_id = settings_store.get_str("zoom.oauth_client_id", "")
        client_secret = settings_store.get_str("zoom.oauth_client_secret", "")
        if not (account_id and client_id and client_secret):
            raise ZoomNotConfigured(
                "Zoom REST API credentials missing. Configure "
                "zoom.account_id + zoom.oauth_client_id + "
                "zoom.oauth_client_secret in /admin/settings."
            )
        return account_id, client_id, client_secret

    # ──────────────────── SDK JWT signing ────────────────────
    def sign_sdk_token(
        self,
        meeting_number: str,
        *,
        user_name: str,
        role: int = 0,
        ttl_seconds: Optional[int] = None,
    ) -> SignedSDKToken:
        """Mint the signature the Zoom Web SDK consumes in its
        ``client.join({ signature, sdkKey, meetingNumber, userName,
        role, ... })`` call. The signature is a JWT signed with HMAC-
        SHA256 using the SDK Secret.

        The payload structure is dictated by Zoom — see
        https://developers.zoom.us/docs/meeting-sdk/auth/. Notably the
        `tokenExp` claim is what enforces the join window: even if the
        user somehow shares the JWT, joining after `tokenExp` fails.

        Default TTL: 30 minutes (matches zoom.sdk_jwt_ttl_seconds).
        """
        key, secret = self._sdk_pair()
        ttl = ttl_seconds or settings_store.get_int(
            "zoom.sdk_jwt_ttl_seconds", 1800
        )
        iat = int(time.time())
        exp = iat + ttl

        # Zoom Meeting SDK JWT v2 header + payload.
        header = {"alg": "HS256", "typ": "JWT"}
        payload = {
            "sdkKey": key,
            "appKey": key,
            "mn": meeting_number,
            "role": role,
            "iat": iat,
            "exp": exp,
            "tokenExp": exp,
        }
        signature = _make_jwt(header, payload, secret)
        return SignedSDKToken(
            signature=signature,
            sdk_key=key,
            meeting_number=meeting_number,
            user_name=user_name,
            role=role,
            expires_at=datetime.fromtimestamp(exp, tz=timezone.utc),
        )

    # ──────────────────── OAuth bearer (REST API) ────────────────────
    def _get_bearer(self) -> str:
        """Get a fresh access token from Zoom's OAuth server, cached
        in memory until ~60s before expiry."""
        if self._oauth_token and time.monotonic() < self._oauth_expires_at - 60:
            return self._oauth_token

        account_id, client_id, client_secret = self._oauth_creds()
        basic = base64.b64encode(
            f"{client_id}:{client_secret}".encode()
        ).decode()
        with httpx.Client(timeout=15.0) as client:
            r = client.post(
                "https://zoom.us/oauth/token",
                headers={"Authorization": f"Basic {basic}"},
                params={
                    "grant_type": "account_credentials",
                    "account_id": account_id,
                },
            )
        if r.status_code >= 400:
            raise ZoomApiError(r.status_code, r.text)
        body = r.json()
        self._oauth_token = body["access_token"]
        # `expires_in` is seconds from now — Zoom typically returns 3600.
        self._oauth_expires_at = time.monotonic() + int(body.get("expires_in", 3600))
        return self._oauth_token

    def _api_base(self) -> str:
        return settings_store.get_str("zoom.api_base_url", "https://api.zoom.us/v2")

    # ──────────────────── REST API methods ────────────────────
    def create_meeting(
        self,
        *,
        topic: str,
        start_time: datetime,
        duration_minutes: int,
        host_config: dict[str, Any],
        agenda: Optional[str] = None,
    ) -> CreatedMeeting:
        """Schedule a Zoom Meeting under the configured host account.

        host_config keys map onto Zoom's settings dict:
          mute_on_entry         → settings.mute_upon_entry
          allow_self_unmute     → settings.audio (when False, audio
                                  set to "none" preventing self-unmute
                                  via Zoom; the Web SDK enforces this
                                  separately too)
          allow_video_toggle    → settings.host_video / participant_video
          chat_mode             → settings.chat (enabled/disabled is what
                                  Zoom natively supports; "admin_only"
                                  is enforced client-side by us)
          screen_share_mode     → settings.share_screen (host_only / all)
          waiting_room          → settings.waiting_room
          lock_after_start      → can't be pre-set; host locks live
          auto_record           → settings.auto_recording = "cloud"
        """
        host_email = settings_store.get_str("zoom.host_email", "")
        if not host_email:
            raise ZoomNotConfigured(
                "Zoom host_email not configured. Set zoom.host_email "
                "in /admin/settings to the email of the Zoom account "
                "that owns scheduled meetings."
            )

        bearer = self._get_bearer()
        payload = {
            "topic": topic,
            "type": 2,  # scheduled meeting
            "start_time": start_time.astimezone(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "duration": duration_minutes,
            "timezone": "UTC",
            "agenda": agenda or "",
            "settings": _host_config_to_zoom_settings(host_config),
        }
        url = f"{self._api_base()}/users/{host_email}/meetings"
        with httpx.Client(timeout=30.0) as client:
            r = client.post(
                url,
                headers={"Authorization": f"Bearer {bearer}"},
                json=payload,
            )
        if r.status_code >= 400:
            raise ZoomApiError(r.status_code, r.text)
        body = r.json()
        return CreatedMeeting(
            meeting_id=str(body["id"]),
            join_url=body["join_url"],
            start_url=body["start_url"],
        )

    def update_meeting(
        self,
        meeting_id: str,
        *,
        topic: Optional[str] = None,
        start_time: Optional[datetime] = None,
        duration_minutes: Optional[int] = None,
        host_config: Optional[dict[str, Any]] = None,
    ) -> None:
        """PATCH a previously-created Zoom meeting. No-op if all args
        are None."""
        body: dict[str, Any] = {}
        if topic is not None:
            body["topic"] = topic
        if start_time is not None:
            body["start_time"] = start_time.astimezone(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        if duration_minutes is not None:
            body["duration"] = duration_minutes
        if host_config is not None:
            body["settings"] = _host_config_to_zoom_settings(host_config)
        if not body:
            return

        bearer = self._get_bearer()
        url = f"{self._api_base()}/meetings/{meeting_id}"
        with httpx.Client(timeout=30.0) as client:
            r = client.patch(
                url,
                headers={"Authorization": f"Bearer {bearer}"},
                json=body,
            )
        if r.status_code >= 400:
            raise ZoomApiError(r.status_code, r.text)

    def delete_meeting(self, meeting_id: str) -> None:
        """Delete a scheduled meeting. Idempotent: 404 on the upstream
        is treated as "already gone, ok"."""
        bearer = self._get_bearer()
        url = f"{self._api_base()}/meetings/{meeting_id}"
        with httpx.Client(timeout=30.0) as client:
            r = client.delete(
                url, headers={"Authorization": f"Bearer {bearer}"}
            )
        if r.status_code == 404:
            log.info("zoom.delete_meeting_not_found", meeting_id=meeting_id)
            return
        if r.status_code >= 400:
            raise ZoomApiError(r.status_code, r.text)

    def get_recordings(self, meeting_id: str) -> list[dict[str, Any]]:
        """Fetch the recording files for a meeting once Zoom finishes
        cloud processing. Returns the raw `recording_files` list from
        Zoom's response — keys: id, file_type, file_size, download_url,
        play_url, recording_start, recording_end. The webhook handler
        (Z-B2) uses this if the webhook itself didn't include the URL."""
        bearer = self._get_bearer()
        url = f"{self._api_base()}/meetings/{meeting_id}/recordings"
        with httpx.Client(timeout=30.0) as client:
            r = client.get(
                url, headers={"Authorization": f"Bearer {bearer}"}
            )
        if r.status_code == 404:
            return []
        if r.status_code >= 400:
            raise ZoomApiError(r.status_code, r.text)
        body = r.json()
        return body.get("recording_files", []) or []


# Module-level singleton — picks up settings updates because each call
# re-reads from settings_store.
zoom_client = ZoomClient()


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────
def _make_jwt(header: dict, payload: dict, secret: str) -> str:
    """Encode a JWT manually so we don't pull in PyJWT just for this.

    Zoom's SDK accepts the standard {header}.{payload}.{signature}
    format with HMAC-SHA256.
    """
    def b64url(b: bytes) -> str:
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")

    header_b64 = b64url(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = b64url(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    sig = hmac.new(secret.encode("ascii"), signing_input, hashlib.sha256).digest()
    sig_b64 = b64url(sig)
    return f"{header_b64}.{payload_b64}.{sig_b64}"


def _host_config_to_zoom_settings(host_config: dict[str, Any]) -> dict[str, Any]:
    """Map our internal HostConfig dict onto Zoom's REST settings shape.

    Some of our toggles don't have a 1:1 Zoom equivalent — for those
    we either set the closest Zoom field AND enforce client-side in
    the SDK embed (chat_mode "admin_only", screen_share_mode "approval"),
    or skip the Zoom mapping (lock_after_start happens live, not at
    schedule time).
    """
    zoom_settings: dict[str, Any] = {}

    if "mute_on_entry" in host_config:
        zoom_settings["mute_upon_entry"] = bool(host_config["mute_on_entry"])

    if "allow_video_toggle" in host_config:
        # Default Zoom: both host_video and participant_video on/off
        # via the same toggle here. The Web SDK enforces tighter.
        zoom_settings["host_video"] = bool(host_config["allow_video_toggle"])
        zoom_settings["participant_video"] = bool(host_config["allow_video_toggle"])

    chat_mode = host_config.get("chat_mode", "open")
    # Zoom natively supports on/off chat; "admin_only" maps to "on"
    # here and is enforced client-side by hiding the public chat panel.
    zoom_settings["chat"] = chat_mode != "off"

    screen_share_mode = host_config.get("screen_share_mode", "approval")
    # Zoom values: "host" (host only) or "all" (everyone).
    zoom_settings["share_screen"] = (
        "host" if screen_share_mode == "host_only" else "all"
    )

    if "waiting_room" in host_config:
        zoom_settings["waiting_room"] = bool(host_config["waiting_room"])

    if host_config.get("auto_record"):
        zoom_settings["auto_recording"] = "cloud"

    return zoom_settings


def verify_webhook_signature(
    raw_body: bytes,
    timestamp_header: str,
    signature_header: str,
) -> bool:
    """Verify a Zoom webhook v2 signature using the secret token from
    settings_store (zoom.webhook_secret_token).

    Zoom's signature scheme:
      message = "v0:{timestamp}:{raw body}"
      sig     = "v0=" + HMAC-SHA256(secret_token, message).hex()
    """
    secret = settings_store.get_str("zoom.webhook_secret_token", "")
    if not secret:
        # Fail closed — better to drop legitimate webhooks while
        # unconfigured than to accept arbitrary unsigned payloads.
        log.warning("zoom.webhook_secret_token not configured; rejecting webhook")
        return False
    msg = f"v0:{timestamp_header}:{raw_body.decode('utf-8', errors='replace')}".encode()
    expected = "v0=" + hmac.new(
        secret.encode("ascii"), msg, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)
