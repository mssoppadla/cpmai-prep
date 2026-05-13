"use client";
/**
 * Write-only secret input for admin settings.
 *
 * Why this exists
 * ---------------
 * The /admin/settings endpoint returns secret values masked as
 * "••••<last4>". A regular <input value={…}> would render the bullets
 * as if they were the real value, and "Save" would PATCH bullets
 * back to the server — corrupting the stored secret.
 *
 * This component renders TWO states:
 *
 *   1. Idle:   shows the masked value (read-only), with a "Rotate"
 *              button next to it.
 *   2. Editing: shows an empty password-typed input ready to receive
 *              the new value. The user pastes/types, clicks Save, and
 *              the parent calls onSave(newValue). After save, we
 *              auto-return to Idle.
 *
 * The input never re-reads the existing value back — it's write-only,
 * intentionally. If the admin can't remember what was there, they
 * can rotate it (which is the safe action anyway).
 */
import { useState } from "react";


interface SecretInputProps {
  /** The masked representation of the current value (e.g. "••••6e4f"),
   *  or empty string if no value has been set yet. Displayed in idle
   *  state. */
  masked: string;
  /** Called when the admin clicks Save with a new value. Should return
   *  a Promise that resolves on success or rejects on failure. */
  onSave: (newValue: string) => Promise<void>;
  /** Optional placeholder shown when entering a new value. Defaults to
   *  "Paste new value". */
  placeholder?: string;
  /** Disable the whole control (e.g. while another save is in flight). */
  disabled?: boolean;
}


export function SecretInput({
  masked,
  onSave,
  placeholder = "Paste new value",
  disabled = false,
}: SecretInputProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Idle state — show masked value + "Rotate" button. The masked value
  // is rendered as plain text (not an input) so dev tools can't snoop
  // it as a defaulted form field.
  if (!editing) {
    return (
      <div className="flex items-center gap-2">
        <code className="px-2 py-1 text-sm font-mono bg-slate-100 rounded
                         text-slate-700 select-none">
          {masked || <span className="text-slate-400 italic">unset</span>}
        </code>
        <button
          type="button"
          disabled={disabled}
          onClick={() => { setEditing(true); setDraft(""); setError(null); }}
          className="px-2 py-1 text-xs border border-slate-300 rounded
                     hover:bg-slate-50 disabled:opacity-50"
        >
          {masked ? "Rotate" : "Set value"}
        </button>
      </div>
    );
  }

  // Editing state — password-typed input + Save / Cancel.
  // type="password" prevents the value from showing in shoulder-surfing
  // distance AND prevents browsers from autofilling old values.
  async function save() {
    if (!draft.trim()) {
      setError("Value cannot be empty.");
      return;
    }
    setBusy(true); setError(null);
    try {
      await onSave(draft.trim());
      setEditing(false);
      setDraft("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2">
        <input
          type="password"
          autoComplete="new-password"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={placeholder}
          disabled={busy}
          className="flex-1 px-3 py-1.5 text-sm font-mono border
                     border-slate-300 rounded focus:ring-1
                     focus:ring-indigo-500 outline-none"
        />
        <button
          type="button"
          onClick={save}
          disabled={busy || !draft.trim()}
          className="px-3 py-1.5 bg-indigo-600 text-white text-xs rounded
                     hover:bg-indigo-700 disabled:opacity-50"
        >
          {busy ? "Saving…" : "Save"}
        </button>
        <button
          type="button"
          onClick={() => { setEditing(false); setDraft(""); setError(null); }}
          disabled={busy}
          className="px-3 py-1.5 text-xs text-slate-600 hover:text-slate-900
                     disabled:opacity-50"
        >
          Cancel
        </button>
      </div>
      {error && (
        <div className="text-xs text-rose-600">{error}</div>
      )}
    </div>
  );
}
