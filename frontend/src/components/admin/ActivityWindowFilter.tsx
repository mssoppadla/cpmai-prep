"use client";

/**
 * A "who was active in this window" datetime-range filter, shared by the admin
 * Users, Contacts, and User Insights screens. Values are `datetime-local`
 * strings (browser-local); convert with `toIsoUtc` before sending to the API,
 * which expects ISO-8601 (UTC).
 */
export function ActivityWindowFilter({
  from, to, onChange, label = "Active",
}: {
  from: string;
  to: string;
  onChange: (from: string, to: string) => void;
  label?: string;
}) {
  const cls =
    "block mt-0.5 px-2 py-1.5 text-sm border border-slate-300 rounded-lg " +
    "focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none";
  return (
    <div className="flex flex-wrap items-end gap-2">
      <label className="text-xs text-slate-500">
        {label} from
        <input type="datetime-local" value={from} aria-label={`${label} from`}
               onChange={(e) => onChange(e.target.value, to)} className={cls} />
      </label>
      <label className="text-xs text-slate-500">
        to
        <input type="datetime-local" value={to} aria-label={`${label} to`}
               onChange={(e) => onChange(from, e.target.value)} className={cls} />
      </label>
      {(from || to) && (
        <button type="button" onClick={() => onChange("", "")}
                className="pb-1.5 text-xs text-slate-500 hover:text-slate-700 underline">
          clear
        </button>
      )}
    </div>
  );
}

/** A `datetime-local` value → ISO-8601 UTC for the API, or undefined if empty/invalid. */
export function toIsoUtc(local: string): string | undefined {
  if (!local) return undefined;
  const d = new Date(local);
  return isNaN(+d) ? undefined : d.toISOString();
}
