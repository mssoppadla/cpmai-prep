/**
 * Idempotent loader for Google Identity Services (GIS) script.
 *
 * Multiple components on a page can call loadGoogleIdentityServices() —
 * the script is fetched only once and all callers share the same Promise.
 */
const GIS_SRC = "https://accounts.google.com/gsi/client";

let _loadPromise: Promise<void> | null = null;

export function isGoogleLoaded(): boolean {
  return typeof window !== "undefined" && !!window.google?.accounts?.id;
}

/**
 * Load the GIS script. Resolves once `window.google.accounts.id` is
 * available. Safe to call repeatedly — only inserts the script tag once.
 *
 * Returns a rejected Promise on SSR or if the script fails to load.
 */
export function loadGoogleIdentityServices(): Promise<void> {
  if (typeof window === "undefined") {
    return Promise.reject(new Error("GIS cannot load on the server"));
  }
  if (isGoogleLoaded()) return Promise.resolve();
  if (_loadPromise) return _loadPromise;

  _loadPromise = new Promise<void>((resolve, reject) => {
    // If the tag was added previously but the script is still loading,
    // hook into its lifecycle.
    const existing = document.querySelector<HTMLScriptElement>(
      `script[src="${GIS_SRC}"]`,
    );
    const target = existing ?? document.createElement("script");
    if (!existing) {
      target.src = GIS_SRC;
      target.async = true;
      target.defer = true;
      document.head.appendChild(target);
    }
    const onLoad = () => {
      // Double-check the global appeared (rare race on slow nets)
      if (isGoogleLoaded()) resolve();
      else reject(new Error("GIS loaded but window.google.accounts is missing"));
    };
    const onError = () => reject(new Error("Failed to load Google Identity Services"));
    target.addEventListener("load", onLoad, { once: true });
    target.addEventListener("error", onError, { once: true });
  });

  return _loadPromise;
}
