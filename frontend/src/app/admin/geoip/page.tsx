"use client";
/**
 * /admin/geoip — operational dashboard for the GeoIP enrichment feature.
 *
 * Three cards on one page:
 *
 *   1. Credentials — account ID + masked license key (write-only).
 *      Has a "Test connection" button that pings MaxMind without
 *      downloading the full DB.
 *   2. Database — last refresh date/size/age, "Refresh now" button,
 *      stale-warning if age > 35 days.
 *   3. Debug lookup — paste any IP, see the resolved country/city.
 *      Useful for "is the DB really working?" checks from this UI
 *      without SSHing into the VPS.
 *
 * Credentials are stored in the system_settings table via
 * /admin/settings — so rotating the license key here is identical to
 * editing it in the generic Runtime Settings page. We surface the
 * subset on this dedicated page because:
 *   - Co-locating cred + status + manual-refresh makes incident
 *     response faster (one page instead of three).
 *   - The SecretInput component is the right UX for license keys
 *     (write-only, never echo).
 */
import { useEffect, useState, useCallback } from "react";
import { admin, errMsg } from "@/lib/api";
import { SecretInput } from "@/components/admin/SecretInput";
import { countryAndCity } from "@/lib/country-flag";
import type {
  GeoIPStatusOut, GeoIPTestKeyOut, GeoIPRefreshOut,
  GeoIPLookupOut, GeoIPSchedulePreviewOut, SettingOut,
} from "@/types/api";


/**
 * Common cron presets surfaced as one-click buttons on the Schedule
 * card. The labels are intentionally human-language; the cron expression
 * lives in the second tuple element. Operators who want something
 * custom can type into the text field directly.
 *
 * Cadence rationale:
 *   MaxMind GeoLite2-City releases TWICE A WEEK (Tuesdays + Fridays,
 *   ~14:00-22:00 UTC). So:
 *     - "Twice weekly" (default) catches both releases within 6-14 hours
 *     - "Weekly" catches Tuesday's, misses Friday's for up to 4 days
 *     - "Monthly" gets at most 4 of 8 monthly releases — data can be
 *       up to 30 days stale, but bandwidth + DB-churn savings can matter
 *     - "Daily" / "Hourly" exist mostly for testing or paranoid setups —
 *       most ticks return 304 Not Modified (free).
 */
const SCHEDULE_PRESETS: ReadonlyArray<[string, string]> = [
  ["Twice weekly — Wed + Sat 04:17 UTC (recommended, matches MaxMind release cadence)", "17 4 * * 3,6"],
  ["Weekly — Wednesday 04:17 UTC", "17 4 * * 3"],
  ["Monthly — 5th of month 04:17 UTC (less fresh data; saves bandwidth)", "17 4 5 * *"],
  ["Daily — 04:00 UTC", "0 4 * * *"],
  ["Hourly — on the hour (for testing only)", "0 * * * *"],
];


export default function GeoIPPage() {
  const [status, setStatus] = useState<GeoIPStatusOut | null>(null);
  const [settings, setSettings] = useState<Record<string, SettingOut>>({});
  const [error, setError] = useState<string | null>(null);

  // -------------------------------- load
  const reload = useCallback(async () => {
    setError(null);
    try {
      const [statusRow, allSettings] = await Promise.all([
        admin.geoip.status(),
        admin.settings.list(),
      ]);
      setStatus(statusRow);
      // Filter to just the keys we care about.
      const next: Record<string, SettingOut> = {};
      for (const row of allSettings) {
        if (row.key.startsWith("geoip.")) next[row.key] = row;
      }
      setSettings(next);
    } catch (e) {
      setError(errMsg(e));
    }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  // ----------------------------- handlers
  async function saveSetting(key: string, value: unknown) {
    await admin.settings.update(key, value);
    await reload();
  }

  return (
    <div className="p-8 max-w-4xl space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-slate-900">GeoIP enrichment</h1>
        <p className="text-slate-600 mt-1 text-sm">
          IP-to-country/city lookup for incoming leads. Database is the
          free MaxMind GeoLite2-City, refreshed monthly by cron.{" "}
          <a href="/admin/settings" className="text-indigo-600 hover:underline">
            See all settings →
          </a>
        </p>
      </header>

      {error && (
        <div className="bg-rose-50 border border-rose-200 text-rose-700
                        p-3 rounded-lg text-sm">{error}</div>
      )}

      {/* ------------------------------------------- Credentials card */}
      <section className="bg-white rounded-xl border border-slate-200 p-6
                          space-y-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">MaxMind credentials</h2>
          <p className="text-xs text-slate-500 mt-1">
            Get these from <a href="https://www.maxmind.com" target="_blank"
              rel="noreferrer" className="text-indigo-600 hover:underline">
              maxmind.com
            </a> → My Account / My License Keys. Changes here take effect
            on the next refresh (monthly cron or manual "Refresh now").
          </p>
        </div>

        <CredentialRow
          label="Account ID"
          row={settings["geoip.maxmind_account_id"]}
          onSave={(v) => saveSetting("geoip.maxmind_account_id", v)}
          inputType="text"
        />

        <CredentialRow
          label="License key"
          row={settings["geoip.maxmind_license_key"]}
          onSave={(v) => saveSetting("geoip.maxmind_license_key", v)}
          inputType="secret"
        />

        <CredentialRow
          label="Monthly refresh enabled"
          row={settings["geoip.refresh_enabled"]}
          onSave={(v) => saveSetting("geoip.refresh_enabled", v === "true")}
          inputType="bool"
        />

        <TestKeyButton onResult={() => reload()} />
      </section>

      {/* --------------------------------------------- Schedule card */}
      <ScheduleCard
        status={status}
        scheduleRow={settings["geoip.refresh_schedule"]}
        enabledRow={settings["geoip.refresh_enabled"]}
        onSaved={reload}
      />

      {/* --------------------------------------------- Database card */}
      <DatabaseCard status={status} onRefreshed={reload} />

      {/* --------------------------------------------- Debug lookup */}
      <DebugLookupCard />
    </div>
  );
}


// =================================================================== rows

function CredentialRow({
  label, row, onSave, inputType,
}: {
  label: string;
  row: SettingOut | undefined;
  onSave: (newValue: string) => Promise<void>;
  inputType: "text" | "secret" | "bool";
}) {
  return (
    <div className="grid grid-cols-3 gap-4 items-start">
      <div className="text-sm font-medium text-slate-700">{label}</div>
      <div className="col-span-2">
        {inputType === "secret" ? (
          <SecretInput
            masked={typeof row?.value === "string" ? row.value : ""}
            onSave={onSave}
            placeholder="Paste license key from maxmind.com"
          />
        ) : inputType === "bool" ? (
          <BoolSelect
            value={row?.value === true || row?.value === "true"}
            onChange={(v) => onSave(v ? "true" : "false")}
          />
        ) : (
          <PlainInputRow
            value={row?.value as string | number | null}
            onSave={onSave}
          />
        )}
        {row?.description && (
          <p className="text-xs text-slate-500 mt-1">{row.description}</p>
        )}
      </div>
    </div>
  );
}


function PlainInputRow({
  value, onSave,
}: { value: string | number | null | undefined; onSave: (v: string) => Promise<void> }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);

  if (!editing) {
    return (
      <div className="flex items-center gap-2">
        <code className="text-sm font-mono text-slate-800">
          {value === null || value === undefined || value === ""
            ? <span className="text-slate-400 italic">unset</span>
            : String(value)}
        </code>
        <button
          onClick={() => { setEditing(true); setDraft(String(value ?? "")); }}
          className="px-2 py-1 text-xs border border-slate-300 rounded
                     hover:bg-slate-50"
        >Edit</button>
      </div>
    );
  }
  return (
    <div className="flex items-center gap-2">
      <input value={draft} onChange={(e) => setDraft(e.target.value)}
             className="flex-1 px-3 py-1.5 text-sm font-mono border
                        border-slate-300 rounded outline-none
                        focus:ring-1 focus:ring-indigo-500" />
      <button disabled={busy}
              onClick={async () => {
                setBusy(true);
                try { await onSave(draft); setEditing(false); }
                finally { setBusy(false); }
              }}
              className="px-3 py-1.5 bg-indigo-600 text-white text-xs rounded
                         hover:bg-indigo-700 disabled:opacity-50">
        {busy ? "Saving…" : "Save"}
      </button>
      <button onClick={() => setEditing(false)}
              className="px-3 py-1.5 text-xs text-slate-600 hover:text-slate-900">
        Cancel
      </button>
    </div>
  );
}


function BoolSelect({
  value, onChange,
}: { value: boolean; onChange: (v: boolean) => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  return (
    <select value={value ? "true" : "false"}
            disabled={busy}
            onChange={async (e) => {
              setBusy(true);
              try { await onChange(e.target.value === "true"); }
              finally { setBusy(false); }
            }}
            className="px-3 py-1.5 text-sm border border-slate-300 rounded">
      <option value="true">Enabled</option>
      <option value="false">Disabled</option>
    </select>
  );
}


function TestKeyButton({ onResult }: { onResult: () => void }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<GeoIPTestKeyOut | null>(null);

  return (
    <div className="pt-2 border-t border-slate-100">
      <button
        onClick={async () => {
          setBusy(true); setResult(null);
          try {
            const r = await admin.geoip.testKey();
            setResult(r);
            onResult();
          } catch (e) {
            setResult({
              ok: false,
              status_code: null,
              message: errMsg(e),
              latest_db_date: null,
            });
          } finally { setBusy(false); }
        }}
        disabled={busy}
        className="px-3 py-1.5 bg-slate-800 text-white text-sm rounded
                   hover:bg-slate-900 disabled:opacity-50">
        {busy ? "Testing…" : "Test connection to MaxMind"}
      </button>
      {result && (
        <div className={`mt-2 text-sm ${result.ok
            ? "text-emerald-700" : "text-rose-700"}`}>
          {result.ok ? "✓ " : "✗ "}{result.message}
        </div>
      )}
    </div>
  );
}


// ====================================================== Database card

function DatabaseCard({
  status, onRefreshed,
}: { status: GeoIPStatusOut | null; onRefreshed: () => void }) {
  const [busy, setBusy] = useState(false);
  const [refreshResult, setRefreshResult] = useState<GeoIPRefreshOut | null>(null);
  const [refreshError, setRefreshError] = useState<string | null>(null);

  async function refresh() {
    setBusy(true); setRefreshResult(null); setRefreshError(null);
    try {
      const r = await admin.geoip.refreshNow();
      setRefreshResult(r);
      onRefreshed();
    } catch (e) {
      setRefreshError(errMsg(e));
    } finally {
      setBusy(false);
    }
  }

  // Distinguish three states so the UX matches what the admin needs to
  // do next, rather than dumping a single dl regardless of state.
  //   STATE 1: not loaded yet (spinner)
  //   STATE 2: no credentials -> point them at Credentials card
  //   STATE 3: credentials but no database -> prominent "Install now"
  //   STATE 4: database installed -> normal status display
  const credsOK = !!status?.credentials_configured;
  const dbPresent = !!status?.database_present;
  const installButtonLabel = dbPresent ? "Refresh now" : "Install database now";

  return (
    <section className="bg-white rounded-xl border border-slate-200 p-6
                        space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-900">Database</h2>
        {dbPresent && (
          <span className="text-xs text-emerald-700 bg-emerald-50
                           border border-emerald-200 rounded px-2 py-0.5">
            ✓ Installed
          </span>
        )}
      </div>

      {!status ? (
        <p className="text-sm text-slate-500">Loading…</p>
      ) : !credsOK ? (
        // STATE 2 — no credentials yet. Block install path entirely and
        // point at the Credentials card above.
        <div className="bg-slate-50 border border-slate-200 text-slate-700
                        p-4 rounded text-sm space-y-2">
          <div className="font-medium">Set credentials first.</div>
          <ol className="list-decimal list-inside text-xs space-y-1 ml-1">
            <li>Paste your MaxMind license key in the Credentials card above.</li>
            <li>Click <strong>Test connection</strong> — should turn green.</li>
            <li>Come back here and click <strong>Install database now</strong>.</li>
          </ol>
          <div className="text-xs text-slate-500">
            Don't have a key? Get one at{" "}
            <a href="https://www.maxmind.com" target="_blank" rel="noreferrer"
               className="text-indigo-600 hover:underline">maxmind.com</a>
            {" "}→ My License Keys → Create new license key{" "}
            <em>(check "GeoIP Update" permission)</em>. Free.
          </div>
        </div>
      ) : !dbPresent ? (
        // STATE 3 — creds present but mmdb missing. This is the
        // first-install case AND the recovery case after a failed deploy.
        // Make the action one big, obvious button — no SSH needed.
        <div className="bg-indigo-50 border border-indigo-200 text-indigo-900
                        p-4 rounded text-sm space-y-3">
          <div>
            <div className="font-medium">
              Database not installed yet — click the button below.
            </div>
            <div className="text-xs text-indigo-900/70 mt-1">
              Downloads MaxMind GeoLite2-City (~30 MB) to the server,
              verifies sha256, and atomically installs it. Takes 5-15
              seconds. Lookups start working immediately — no app
              restart needed (the reader hot-reloads on mtime change).
            </div>
          </div>
          <button onClick={refresh} disabled={busy}
                  className="px-4 py-2 bg-indigo-600 text-white text-sm
                             font-medium rounded hover:bg-indigo-700
                             disabled:opacity-50">
            {busy ? "Installing…" : "Install database now"}
          </button>
          {refreshError && (
            <div className="text-sm text-rose-700">
              ✗ {refreshError}
            </div>
          )}
          {refreshResult && refreshResult.updated && (
            <div className="text-sm text-emerald-700 font-medium">
              ✓ {refreshResult.message}
            </div>
          )}
        </div>
      ) : (
        // STATE 4 — database installed. Show status + a smaller refresh
        // button (rare-action) instead of the big primary CTA.
        <>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
            <dt className="text-slate-500">Size</dt>
            <dd className="text-slate-800">{status.database_size_human}</dd>
            <dt className="text-slate-500">Last refresh (UTC)</dt>
            <dd className="text-slate-800">
              {status.database_mtime
                ? new Date(status.database_mtime).toLocaleString()
                : "—"}
            </dd>
            <dt className="text-slate-500">Age</dt>
            <dd className={status.database_stale
                ? "text-amber-700 font-medium" : "text-slate-800"}>
              {status.database_age_days?.toFixed(1)} days
              {status.database_stale && " — STALE (>35 days)"}
            </dd>
            <dt className="text-slate-500">Lookups this process</dt>
            <dd className="text-slate-800">{status.last_lookup_count}</dd>
          </dl>

          <div className="pt-3 border-t border-slate-100 flex items-center gap-3 flex-wrap">
            <button onClick={refresh} disabled={busy}
                    className="px-3 py-1.5 bg-indigo-600 text-white text-sm
                               rounded hover:bg-indigo-700 disabled:opacity-50">
              {busy ? "Refreshing…" : "Refresh now"}
            </button>
            <span className="text-xs text-slate-500">
              The cron handles this automatically — manual is for "I just
              rotated the key and want to verify" cases.
            </span>
            {refreshResult && (
              <span className="text-sm text-emerald-700 w-full">
                ✓ {refreshResult.message}
              </span>
            )}
            {refreshError && (
              <span className="text-sm text-rose-700 w-full">
                ✗ {refreshError}
              </span>
            )}
          </div>
        </>
      )}
    </section>
  );
}


// ===================================================== Schedule card

function ScheduleCard({
  status, scheduleRow, enabledRow, onSaved,
}: {
  status: GeoIPStatusOut | null;
  scheduleRow: SettingOut | undefined;
  enabledRow: SettingOut | undefined;
  onSaved: () => void;
}) {
  // Local draft so the operator can type freely + preview without
  // touching the persisted value. Initialized from the server's
  // current schedule on every reload.
  const currentExpr =
    typeof scheduleRow?.value === "string" ? scheduleRow.value : "";
  const [draft, setDraft] = useState(currentExpr);
  const [preview, setPreview] =
    useState<GeoIPSchedulePreviewOut | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Re-seed the draft whenever the server's value changes (e.g. after
  // a successful save → reload propagates here).
  useEffect(() => { setDraft(currentExpr); setPreview(null); }, [currentExpr]);

  const dirty = draft !== currentExpr;

  // Toggle the refresh_enabled kill switch independently.
  const enabled = enabledRow?.value === true || enabledRow?.value === "true";

  async function previewNow(expr: string) {
    setPreviewing(true); setError(null);
    try {
      setPreview(await admin.geoip.previewSchedule(expr, 5));
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setPreviewing(false);
    }
  }

  async function save() {
    if (!draft.trim()) { setError("Schedule cannot be empty."); return; }
    setSaving(true); setError(null);
    try {
      await admin.settings.update("geoip.refresh_schedule", draft.trim());
      onSaved();
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setSaving(false);
    }
  }

  async function toggleEnabled(next: boolean) {
    try {
      await admin.settings.update("geoip.refresh_enabled", next);
      onSaved();
    } catch (e) {
      setError(errMsg(e));
    }
  }

  return (
    <section className="bg-white rounded-xl border border-slate-200 p-6
                        space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-slate-900">Refresh schedule</h2>
        <p className="text-xs text-slate-500 mt-1">
          The VPS cron fires every minute; this expression decides which
          minutes actually trigger a refresh. Edit + save here to change
          the schedule without redeploying. Aligns with MaxMind's release
          cadence (Tuesdays + Fridays).
        </p>
      </div>

      {/* Kill switch — flips refresh_enabled. Independent of schedule. */}
      <div className="flex items-center gap-3 pb-3 border-b border-slate-100">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => toggleEnabled(e.target.checked)}
            className="rounded"
          />
          <span className="font-medium text-slate-700">
            Refreshes enabled
          </span>
        </label>
        <span className="text-xs text-slate-500">
          Disable during a known MaxMind outage. Schedule still ticks
          but no downloads happen until re-enabled.
        </span>
      </div>

      {/* Current schedule + next 3 from /status */}
      {status?.refresh_schedule && (
        <div className="text-sm text-slate-700">
          <div>
            <span className="text-slate-500">Active: </span>
            <code className="font-mono text-slate-800">
              {status.refresh_schedule}
            </code>
            {status.refresh_schedule_human && (
              <span className="text-slate-500 ml-2">
                — {status.refresh_schedule_human}
              </span>
            )}
          </div>
          {status.refresh_schedule_next_runs.length > 0 && (
            <div className="mt-1.5 text-xs text-slate-500">
              Next runs:&nbsp;
              {status.refresh_schedule_next_runs.map((iso, i) => (
                <span key={iso}>
                  {i > 0 && ", "}
                  <code className="font-mono">
                    {new Date(iso).toLocaleString()}
                  </code>
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Preset buttons */}
      <div>
        <div className="text-xs text-slate-500 mb-1.5">Presets:</div>
        <div className="flex flex-wrap gap-2">
          {SCHEDULE_PRESETS.map(([label, expr]) => (
            <button
              key={expr}
              onClick={() => { setDraft(expr); previewNow(expr); }}
              className={`px-2.5 py-1 text-xs rounded border ${
                draft === expr
                  ? "bg-indigo-50 border-indigo-300 text-indigo-700"
                  : "border-slate-300 hover:bg-slate-50"
              }`}
              title={expr}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Draft + Preview + Save */}
      <div className="space-y-2">
        <label className="text-xs text-slate-500" htmlFor="schedule-expr">
          Cron expression (minute hour day-of-month month day-of-week):
        </label>
        <div className="flex items-center gap-2">
          <input
            id="schedule-expr"
            value={draft}
            onChange={(e) => { setDraft(e.target.value); setPreview(null); }}
            placeholder="17 4 * * 3,6"
            className="flex-1 px-3 py-1.5 text-sm font-mono border
                       border-slate-300 rounded focus:ring-1
                       focus:ring-indigo-500 outline-none"
          />
          <button
            onClick={() => previewNow(draft)}
            disabled={previewing || !draft.trim()}
            className="px-3 py-1.5 text-xs border border-slate-300
                       rounded hover:bg-slate-50 disabled:opacity-50"
          >
            {previewing ? "Checking…" : "Preview"}
          </button>
          <button
            onClick={save}
            disabled={saving || !dirty || !draft.trim()}
            className="px-3 py-1.5 bg-indigo-600 text-white text-xs
                       rounded hover:bg-indigo-700 disabled:opacity-50"
            title={!dirty ? "No changes to save" : "Save this schedule"}
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>

        {preview && (
          preview.ok ? (
            <div className="bg-emerald-50 border border-emerald-200 rounded p-3 text-sm">
              <div className="text-emerald-800 font-medium">
                ✓ Valid — {preview.human}
              </div>
              {preview.next_runs.length > 0 && (
                <ul className="mt-1.5 text-xs text-emerald-900/70 space-y-0.5">
                  {preview.next_runs.map((iso) => (
                    <li key={iso}>
                      <code className="font-mono">
                        {new Date(iso).toLocaleString()}
                      </code>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ) : (
            <div className="bg-rose-50 border border-rose-200 rounded p-3 text-sm text-rose-700">
              ✗ {preview.reason}
            </div>
          )
        )}
        {error && (
          <div className="text-sm text-rose-700">{error}</div>
        )}
      </div>
    </section>
  );
}


// ====================================================== Debug lookup

function DebugLookupCard() {
  const [ip, setIp] = useState("");
  const [result, setResult] = useState<GeoIPLookupOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function go() {
    if (!ip.trim()) return;
    setBusy(true); setError(null); setResult(null);
    try {
      setResult(await admin.geoip.lookup(ip.trim()));
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="bg-white rounded-xl border border-slate-200 p-6
                        space-y-3">
      <h2 className="text-lg font-semibold text-slate-900">Debug lookup</h2>
      <p className="text-xs text-slate-500">
        Resolve any IP address using the currently-installed database.
        Private IPs (10.x, 192.168.x, 127.x) return "no record" — that's
        expected.
      </p>
      <div className="flex items-center gap-2">
        <input value={ip} onChange={(e) => setIp(e.target.value)}
               onKeyDown={(e) => e.key === "Enter" && go()}
               placeholder="8.8.8.8"
               className="flex-1 px-3 py-1.5 text-sm font-mono border
                          border-slate-300 rounded focus:ring-1
                          focus:ring-indigo-500 outline-none" />
        <button onClick={go} disabled={busy || !ip.trim()}
                className="px-3 py-1.5 bg-slate-800 text-white text-sm
                           rounded hover:bg-slate-900 disabled:opacity-50">
          {busy ? "Looking up…" : "Lookup"}
        </button>
      </div>
      {error && (
        <div className="text-sm text-rose-700">{error}</div>
      )}
      {result && (
        <div className="bg-slate-50 border border-slate-200 rounded p-3 text-sm">
          {result.found ? (
            <div className="space-y-1">
              <div className="text-lg">
                {countryAndCity(result.country, result.city)}
              </div>
              <div className="text-xs text-slate-600 font-mono">
                country={result.country || "—"} · city={result.city || "—"} ·
                lat={result.latitude ?? "—"} · lon={result.longitude ?? "—"}
              </div>
            </div>
          ) : (
            <span className="text-slate-500">
              No record for <code className="font-mono">{result.ip}</code>{" "}
              (private/reserved IP, or unknown to MaxMind).
            </span>
          )}
        </div>
      )}
    </section>
  );
}
