"use client";
/**
 * GoogleSignInButton — drop-in React component for Google Sign-In.
 *
 * Renders nothing if `clientId` is empty, so a project can ship the
 * component everywhere and only enable it where configured.
 *
 * Props are intentionally minimal. The component:
 *   1. Loads GIS once (idempotent across mounts)
 *   2. Initializes with the given client_id and callback
 *   3. Renders Google's official button into a child div
 *   4. Hands the `credential` JWT to your `onCredential` prop
 *
 * Network calls and session handling are explicitly NOT this component's
 * job — the parent decides what to do with the credential.
 */
import { useEffect, useRef, useState } from "react";
import {
  isGoogleLoaded,
  loadGoogleIdentityServices,
} from "./gis-loader";
import type { GsiButtonConfig, GoogleCredentialResponse } from "./types";

export interface GoogleSignInButtonProps {
  /** Google OAuth web-application client ID. If empty, nothing renders. */
  clientId: string;
  /** Called with the verified credential JWT after the user completes sign-in. */
  onCredential: (credential: string) => void | Promise<void>;
  /** Called if GIS fails to load or initialize (script blocked, etc.) */
  onError?: (e: Error) => void;
  /** GIS button styling. See https://developers.google.com/identity/gsi/web/reference/js-reference#GsiButtonConfiguration */
  buttonConfig?: GsiButtonConfig;
  /** Optional className on the outer wrapper. */
  className?: string;
  /** UI context — affects the auto-prompt copy. */
  context?: "signin" | "signup" | "use";
}

export function GoogleSignInButton({
  clientId,
  onCredential,
  onError,
  buttonConfig,
  className,
  context = "signin",
}: GoogleSignInButtonProps) {
  const target = useRef<HTMLDivElement | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!clientId) return;
    let cancelled = false;

    const wireUp = () => {
      if (cancelled || !target.current || !isGoogleLoaded()) return;
      try {
        window.google!.accounts.id.initialize({
          client_id: clientId,
          context,
          callback: (resp: GoogleCredentialResponse) => {
            if (resp?.credential) Promise.resolve(onCredential(resp.credential));
          },
        });
        window.google!.accounts.id.renderButton(target.current, {
          theme: "outline",
          size: "large",
          shape: "rectangular",
          text: "continue_with",
          logo_alignment: "left",
          ...buttonConfig,
        });
        setReady(true);
      } catch (e) {
        onError?.(e instanceof Error ? e : new Error(String(e)));
      }
    };

    loadGoogleIdentityServices()
      .then(wireUp)
      .catch((e) => {
        if (!cancelled) onError?.(e instanceof Error ? e : new Error(String(e)));
      });

    return () => { cancelled = true; };
    // The Google config is captured at init time; reinit only if clientId changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clientId]);

  if (!clientId) return null;

  return (
    <div className={className}>
      <div ref={target} aria-label="Sign in with Google" />
      {!ready && (
        <div className="text-xs text-slate-400 py-2">Loading Google sign-in…</div>
      )}
    </div>
  );
}
