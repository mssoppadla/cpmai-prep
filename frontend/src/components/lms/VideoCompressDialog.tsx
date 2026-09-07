"use client";
/**
 * VideoCompressDialog — pre-upload compression for admin lesson videos.
 *
 * Why client-side and not server-side:
 *   - 1 GB cap means uploads are slow over residential ISPs (10–30 min
 *     for a multi-Gbps raw lesson). Compressing BEFORE upload saves
 *     bandwidth + storage.
 *   - Server-side compression needs a worker queue + Redis job + a
 *     long-running ffmpeg process. That's a separate PR.
 *   - Browser MediaRecorder gives Good Enough output for screen-record
 *     lectures (which is most of what this LMS hosts) without any new
 *     dependency.
 *
 * Approach:
 *   - Load source video into a hidden <video> element to probe metadata
 *     (duration, intrinsic resolution).
 *   - Compute source bitrate (file.size * 8 / duration). Every preset's
 *     EFFECTIVE bitrate is clamped to ~90% of the source — re-encoding
 *     above the source bitrate only inflates the file, it can never add
 *     quality (2026-09-07: a 0.7 Mbps source showed "predicted 6.16 GB"
 *     for a 910 MB file because predictions used the raw preset rate).
 *   - Offer resolution × bitrate presets, marking ONE as recommended.
 *     When the clamp dominates (low-bitrate source), the sizes converge,
 *     so the recommendation prefers the HIGHEST resolution that fits the
 *     source — same bytes, more pixels.
 *   - "Preview quality" sidebar: encodes a 10-second sample from the
 *     middle of the video at the selected preset, so the admin can judge
 *     quality and get a MEASURED size estimate before committing to a
 *     full re-encode (which runs at ~1× playback speed).
 *   - On "Start compression": draw frames from the <video> to a <canvas>
 *     at target resolution; capture the canvas stream + the video's
 *     audio track; pipe both into a MediaRecorder at the effective
 *     bitrate. Real-time progress; side-by-side preview when done.
 *
 * Known limitations (documented intentionally so future-me doesn't
 * waste time chasing them):
 *
 *   - Output is WebM (VP8/VP9 codec). Chrome/Edge/Firefox play it
 *     natively; iOS Safari plays only via <video> tag with .webm
 *     source — which is what our lesson player uses. So end-users
 *     are unaffected.
 *   - canvas.captureStream() does not work on iOS Safari < 16. The
 *     dialog detects this and falls back to "upload original" mode
 *     with a banner explaining why compression is disabled.
 *   - Audio re-encoding via MediaRecorder uses Opus at a fixed
 *     bitrate (~128 kbps). For lecture audio this is fine; for
 *     music-heavy content it's noticeably worse than the source.
 *   - Compression runs at ~1× playback speed (MediaRecorder draws
 *     in real time). A 1-hour video takes ~1 hour to compress.
 *     User can cancel mid-way and just upload the original.
 *   - Output file size is APPROXIMATE — MediaRecorder's
 *     videoBitsPerSecond is a target, not a cap. Real output varies
 *     ±15%. The 10s sample preview measures the ACTUAL rate and
 *     refines the estimate.
 */
import { useCallback, useEffect, useRef, useState } from "react";


export interface CompressionPreset {
  id: string;
  label: string;
  width: number;
  height: number;
  /** Total bitrate (video + audio) target in bits/sec. We split:
   *  audio fixed at 128_000; video gets the remainder. The EFFECTIVE
   *  rate used for encoding + prediction is clamped to the source. */
  totalBitsPerSecond: number;
  description: string;
}


/** Preset library. Order matters — these render top-to-bottom. */
export const PRESETS: CompressionPreset[] = [
  {
    id: "1080p-high",
    label: "1080p — High (5 Mbps)",
    width: 1920, height: 1080, totalBitsPerSecond: 5_000_000,
    description: "Demos, code walkthroughs, slides with embedded video. Best detail.",
  },
  {
    id: "1080p-med",
    label: "1080p — Medium (3 Mbps)",
    width: 1920, height: 1080, totalBitsPerSecond: 3_000_000,
    description: "Standard lecture quality at full resolution. Good balance.",
  },
  {
    id: "720p-med",
    label: "720p — Medium (2.5 Mbps)",
    width: 1280, height: 720, totalBitsPerSecond: 2_500_000,
    description: "Recommended for most lessons — sharp on laptops, friendly on bandwidth.",
  },
  {
    id: "720p-low",
    label: "720p — Low (1.5 Mbps)",
    width: 1280, height: 720, totalBitsPerSecond: 1_500_000,
    description: "Long lectures where slides + voice are primary. Half the storage.",
  },
  {
    id: "480p-med",
    label: "480p — Medium (800 kbps)",
    width: 854, height: 480, totalBitsPerSecond: 800_000,
    description: "Mobile-first or low-bandwidth markets. Smallest file.",
  },
];

/** Never encode above ~90% of the source bitrate: it inflates the file
 *  without adding quality (you can't restore detail the source lacks). */
const SOURCE_CLAMP = 0.9;
/** Floor so the clamp can't produce unwatchable output. */
const MIN_TOTAL_BPS = 350_000;

export function effectiveBps(preset: CompressionPreset, sourceBps: number): number {
  if (sourceBps <= 0) return preset.totalBitsPerSecond;
  return Math.max(MIN_TOTAL_BPS,
                  Math.min(preset.totalBitsPerSecond, sourceBps * SOURCE_CLAMP));
}

export function isClamped(preset: CompressionPreset, sourceBps: number): boolean {
  return sourceBps > 0 && preset.totalBitsPerSecond > sourceBps * SOURCE_CLAMP;
}


/** Pick the preset most appropriate for duration + source. When the
 *  source bitrate is below several presets' targets, their output sizes
 *  converge (all clamped) — so prefer the highest resolution that
 *  doesn't exceed the source's own: same bytes, more pixels. */
export function recommendedPresetId(durationSec: number, sourceBps: number,
                             intrinsicH: number): string {
  if (sourceBps > 0) {
    const clampedFit = PRESETS.filter(
      (p) => isClamped(p, sourceBps) && (!intrinsicH || p.height <= intrinsicH));
    if (clampedFit.length) {
      // All cost ~the same; take the highest resolution among them.
      return clampedFit.reduce((a, b) => (b.height > a.height ? b : a)).id;
    }
  }
  if (durationSec < 5 * 60) return "1080p-med";       // < 5 min
  if (durationSec < 30 * 60) return "720p-med";       // 5–30 min
  if (durationSec < 90 * 60) return "720p-low";       // 30–90 min
  return "480p-med";                                  // 90+ min
}


function fmtBytes(n: number): string {
  if (n >= 1024 ** 3) return `${(n / 1024 ** 3).toFixed(2)} GB`;
  if (n >= 1024 ** 2) return `${(n / 1024 ** 2).toFixed(0)} MB`;
  return `${(n / 1024).toFixed(0)} KB`;
}


function fmtDuration(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}


/** Predicted output bytes from the EFFECTIVE (source-clamped) bitrate.
 *  Real-world is ±15%; the 10s sample preview refines this. */
export function predictedBytes(preset: CompressionPreset, durationSec: number,
                        sourceBps: number): number {
  return Math.round((effectiveBps(preset, sourceBps) * durationSec) / 8);
}

const SAMPLE_SECONDS = 10;


export interface VideoCompressDialogProps {
  /** The file the admin selected from the file picker. */
  file: File;
  /** Called when admin clicks "Upload compressed" — file is the
   *  re-encoded WebM blob wrapped as a File so the existing upload
   *  endpoint accepts it identically. */
  onUseCompressed: (blob: File) => void;
  /** Called when admin clicks "Upload original" — passes the original
   *  un-touched. */
  onUseOriginal: (orig: File) => void;
  /** Close without uploading (e.g. user picks "Cancel"). */
  onCancel: () => void;
}


type Phase =
  | "probing"           // initial — measuring duration/size
  | "ready"             // metadata loaded; user picks preset
  | "compressing"       // MediaRecorder running (full encode)
  | "done"              // compressed blob available, preview ready
  | "failed"            // compression errored out
  | "unsupported";      // browser can't compress (no captureStream)


export default function VideoCompressDialog(props: VideoCompressDialogProps) {
  const { file, onUseCompressed, onUseOriginal, onCancel } = props;
  const [phase, setPhase] = useState<Phase>("probing");
  const [err, setErr] = useState<string | null>(null);
  const [durationSec, setDurationSec] = useState<number>(0);
  const [intrinsicW, setIntrinsicW] = useState<number>(0);
  const [intrinsicH, setIntrinsicH] = useState<number>(0);
  const [presetId, setPresetId] = useState<string>("");
  const [progress, setProgress] = useState<number>(0);
  const [compressedBlob, setCompressedBlob] = useState<Blob | null>(null);
  const [compressedUrl, setCompressedUrl] = useState<string | null>(null);
  const [originalUrl, setOriginalUrl] = useState<string | null>(null);

  // 10-second quality sample (sidebar), keyed by the preset it encoded.
  const [sampleBusy, setSampleBusy] = useState(false);
  const [sampleUrl, setSampleUrl] = useState<string | null>(null);
  const [sampleBytes, setSampleBytes] = useState<number>(0);
  const [samplePresetId, setSamplePresetId] = useState<string>("");

  // Refs for the offscreen probing + compressing video element.
  const probeRef = useRef<HTMLVideoElement | null>(null);
  const cancelCompressionRef = useRef<(() => void) | null>(null);
  const cancelSampleRef = useRef<(() => void) | null>(null);

  // Stable object URL for the source so probing + preview share it.
  useEffect(() => {
    const url = URL.createObjectURL(file);
    setOriginalUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  const sourceBitrate = durationSec > 0 ? (file.size * 8) / durationSec : 0;

  // Phase 1: probe duration + intrinsic resolution.
  useEffect(() => {
    if (!originalUrl) return;
    const v = document.createElement("video");
    v.preload = "metadata";
    v.muted = true;
    v.src = originalUrl;
    v.onloadedmetadata = () => {
      const dur = isFinite(v.duration) ? v.duration : 0;
      const w = v.videoWidth || 0;
      const h = v.videoHeight || 0;
      setDurationSec(dur);
      setIntrinsicW(w);
      setIntrinsicH(h);
      const srcBps = dur > 0 ? (file.size * 8) / dur : 0;
      setPresetId(recommendedPresetId(dur, srcBps, h));
      // Capability check: canvas.captureStream + MediaRecorder.
      const canvas = document.createElement("canvas");
      const hasCapture =
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        typeof (canvas as any).captureStream === "function" &&
        typeof MediaRecorder !== "undefined";
      setPhase(hasCapture ? "ready" : "unsupported");
    };
    v.onerror = () => {
      setErr("Could not read the video — file may be corrupt or in a format the browser doesn't support.");
      setPhase("failed");
    };
    probeRef.current = v;
    return () => { v.src = ""; probeRef.current = null; };
  }, [originalUrl, file.size]);

  /** Shared encoder for both the full run and the 10s sample.
   *  Resolves with the encoded blob; rejects on error/cancel. */
  const encode = useCallback(async (
    preset: CompressionPreset,
    opts: { startAt?: number; maxSeconds?: number;
            onProgress?: (p: number) => void;
            registerCancel?: (fn: () => void) => void },
  ): Promise<Blob> => {
    if (!originalUrl) throw new Error("source not ready");

    // Aspect-preserving resize: scale so the source fits inside
    // preset.width × preset.height. Maintains the source's original
    // ratio (otherwise wide source gets squashed into 16:9 preset).
    const srcAspect = intrinsicW / intrinsicH;
    let outW = preset.width;
    let outH = preset.height;
    if (srcAspect > outW / outH) {
      outH = Math.round(outW / srcAspect);
      if (outH % 2) outH -= 1;         // even dims required by some codecs
    } else {
      outW = Math.round(outH * srcAspect);
      if (outW % 2) outW -= 1;
    }

    const v = document.createElement("video");
    v.src = originalUrl;
    v.muted = false;            // we WANT the audio track to capture
    v.crossOrigin = "anonymous";
    v.playsInline = true;
    await new Promise<void>((res, rej) => {
      v.onloadeddata = () => res();
      v.onerror = () => rej(new Error("source video failed to load for compression"));
    });
    const startAt = Math.max(0, Math.min(opts.startAt ?? 0,
                                         Math.max(0, durationSec - (opts.maxSeconds ?? 0) - 1)));
    if (startAt > 0) {
      v.currentTime = startAt;
      await new Promise<void>((res) => { v.onseeked = () => res(); });
    }
    const stopAt = opts.maxSeconds != null
      ? Math.min(durationSec, startAt + opts.maxSeconds)
      : durationSec;

    const canvas = document.createElement("canvas");
    canvas.width = outW;
    canvas.height = outH;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("Could not get a 2D canvas context — browser may be in a degraded state.");

    // Composite stream: video from canvas + audio from <video>.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const videoStream: MediaStream = (canvas as any).captureStream(30);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const audioOnly: MediaStream = (v as any).captureStream?.();
    if (audioOnly) {
      audioOnly.getAudioTracks().forEach((t) => videoStream.addTrack(t));
    }

    const candidates = [
      "video/webm;codecs=vp9,opus",
      "video/webm;codecs=vp8,opus",
      "video/webm",
    ];
    const mimeType = candidates.find((c) => MediaRecorder.isTypeSupported(c)) ?? "video/webm";

    // Split the source-clamped EFFECTIVE bitrate: audio 128k, video rest.
    const totalBps = effectiveBps(preset, sourceBitrate);
    const audioBps = Math.min(128_000, Math.round(totalBps * 0.3));
    const videoBps = Math.max(200_000, totalBps - audioBps);

    const recorder = new MediaRecorder(videoStream, {
      mimeType,
      videoBitsPerSecond: videoBps,
      audioBitsPerSecond: audioBps,
    });
    const chunks: BlobPart[] = [];
    recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };

    let frameLoop: number | null = null;
    let cancelled = false;
    opts.registerCancel?.(() => {
      cancelled = true;
      try { recorder.state === "recording" && recorder.stop(); } catch {}
      try { v.pause(); } catch {}
      if (frameLoop != null) cancelAnimationFrame(frameLoop);
      videoStream.getTracks().forEach((t) => t.stop());
    });

    function drawFrame() {
      if (cancelled || v.ended || v.paused || v.currentTime >= stopAt) {
        try { v.pause(); } catch {}
        if (recorder.state === "recording") recorder.stop();
        return;
      }
      ctx!.drawImage(v, 0, 0, outW, outH);
      const span = stopAt - startAt;
      opts.onProgress?.(span > 0
        ? Math.min(1, (v.currentTime - startAt) / span) : 0);
      frameLoop = requestAnimationFrame(drawFrame);
    }

    const done = new Promise<Blob>((res, rej) => {
      recorder.onstop = () => {
        videoStream.getTracks().forEach((t) => t.stop());
        if (cancelled) rej(new Error("cancelled"));
        else res(new Blob(chunks, { type: mimeType }));
      };
      recorder.onerror = (e) => rej(e as unknown as Error);
    });

    recorder.start();
    await v.play();               // audio capture requires play()
    frameLoop = requestAnimationFrame(drawFrame);
    return done;
  }, [originalUrl, intrinsicW, intrinsicH, durationSec, sourceBitrate]);

  // Sidebar: 10-second quality sample from the middle of the video.
  const runSample = useCallback(async () => {
    const preset = PRESETS.find((p) => p.id === presetId);
    if (!preset || sampleBusy) return;
    setSampleBusy(true);
    setSampleUrl((cur) => { if (cur) URL.revokeObjectURL(cur); return null; });
    setSampleBytes(0);
    try {
      const blob = await encode(preset, {
        startAt: durationSec / 2,
        maxSeconds: SAMPLE_SECONDS,
        registerCancel: (fn) => { cancelSampleRef.current = fn; },
      });
      setSampleUrl(URL.createObjectURL(blob));
      setSampleBytes(blob.size);
      setSamplePresetId(preset.id);
    } catch {
      /* sample cancelled/failed — sidebar simply stays empty */
    } finally {
      cancelSampleRef.current = null;
      setSampleBusy(false);
    }
  }, [presetId, sampleBusy, encode, durationSec]);

  // Phase 2: full-length compression with the selected preset.
  const runCompression = useCallback(async () => {
    const preset = PRESETS.find((p) => p.id === presetId);
    if (!preset || !originalUrl) return;
    cancelSampleRef.current?.();          // a running sample would fight for decode
    setErr(null);
    setProgress(0);
    setCompressedBlob(null);
    setCompressedUrl((cur) => { if (cur) URL.revokeObjectURL(cur); return null; });
    setPhase("compressing");
    let cancelled = false;
    try {
      const blob = await encode(preset, {
        onProgress: setProgress,
        registerCancel: (fn) => {
          cancelCompressionRef.current = () => { cancelled = true; fn(); };
        },
      });
      const url = URL.createObjectURL(blob);
      setCompressedBlob(blob);
      setCompressedUrl(url);
      setProgress(1);
      setPhase("done");
    } catch (e) {
      if (!cancelled) {
        setErr((e as Error)?.message ?? "compression failed");
        setPhase("failed");
      } else {
        setPhase("ready");
      }
    } finally {
      cancelCompressionRef.current = null;
    }
  }, [presetId, originalUrl, encode]);

  function handleUseCompressed() {
    if (!compressedBlob) return;
    // Re-name with .webm extension since the codec is WebM.
    const base = file.name.replace(/\.[^.]+$/, "");
    const f = new File([compressedBlob], `${base}-compressed.webm`,
                       { type: compressedBlob.type, lastModified: Date.now() });
    onUseCompressed(f);
  }

  function handleCancel() {
    cancelCompressionRef.current?.();
    cancelSampleRef.current?.();
    onCancel();
  }

  // ───────────────────────── render ─────────────────────────

  const currentPreset = PRESETS.find((p) => p.id === presetId);
  const predictedSize = currentPreset && durationSec
    ? predictedBytes(currentPreset, durationSec, sourceBitrate)
    : 0;
  const recId = durationSec
    ? recommendedPresetId(durationSec, sourceBitrate, intrinsicH) : "";
  // Sample-measured refinement of the estimate, when a sample exists for
  // the CURRENT preset.
  const sampleValid = sampleUrl && samplePresetId === presetId;
  const measuredEstimate = sampleValid && sampleBytes > 0 && durationSec > 0
    ? Math.round((sampleBytes / SAMPLE_SECONDS) * durationSec)
    : 0;

  return (
    <div className="fixed inset-0 z-50 bg-slate-900/50 flex items-start justify-center p-4 overflow-y-auto">
      <div className="bg-white rounded-xl border border-slate-200 max-w-5xl w-full my-8 max-h-[90vh] overflow-y-auto">
        <header className="p-5 border-b border-slate-200">
          <h2 className="font-semibold text-slate-900">Compress before upload?</h2>
          <p className="text-xs text-slate-500 mt-1">
            Smaller files upload faster and use less of your storage budget.
            Compression runs entirely in your browser; nothing leaves until you confirm.
          </p>
        </header>

        <div className="p-5 space-y-4">
          {/* Source info */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
            <div className="border border-slate-200 rounded-lg p-3">
              <div className="text-xs text-slate-500">Source size</div>
              <div className="font-semibold text-slate-900">{fmtBytes(file.size)}</div>
            </div>
            <div className="border border-slate-200 rounded-lg p-3">
              <div className="text-xs text-slate-500">Duration</div>
              <div className="font-semibold text-slate-900">
                {durationSec ? fmtDuration(durationSec) : "—"}
              </div>
            </div>
            <div className="border border-slate-200 rounded-lg p-3">
              <div className="text-xs text-slate-500">Source resolution</div>
              <div className="font-semibold text-slate-900">
                {intrinsicW > 0 ? `${intrinsicW}×${intrinsicH}` : "—"}
              </div>
            </div>
            <div className="border border-slate-200 rounded-lg p-3">
              <div className="text-xs text-slate-500">Source bitrate</div>
              <div className="font-semibold text-slate-900">
                {sourceBitrate > 0
                  ? `${(sourceBitrate / 1_000_000).toFixed(1)} Mbps` : "—"}
              </div>
            </div>
          </div>

          {sourceBitrate > 0 && sourceBitrate > 5_500_000 && (
            <div className="text-xs text-amber-700">
              Source bitrate is higher than necessary for most lesson content —
              strongly recommend compressing.
            </div>
          )}
          {sourceBitrate > 0 && sourceBitrate < 1_200_000 && (
            <div className="text-xs text-slate-600 bg-slate-50 border border-slate-200 rounded-lg p-3">
              This source is already low-bitrate
              ({(sourceBitrate / 1_000_000).toFixed(1)} Mbps), so bitrates are
              capped at the source — re-encoding above it would only grow the
              file without adding quality. Expect modest savings; if the
              predicted reduction is small, uploading the original is a fine
              choice.
            </div>
          )}

          {phase === "unsupported" && (
            <div role="alert" className="bg-amber-50 border border-amber-200 text-amber-900 p-3 rounded-lg text-sm">
              Your browser doesn&apos;t support in-browser video re-encoding (no
              <code> canvas.captureStream</code>). Compress with a desktop tool
              (HandBrake, QuickTime → Export) and re-upload, or upload the
              original as-is.
            </div>
          )}

          {err && (
            <div role="alert" className="bg-rose-50 border border-rose-200 text-rose-700 p-3 rounded-lg text-sm">
              {err}
            </div>
          )}

          {/* Preset picker + quality-preview sidebar */}
          {(phase === "ready" || phase === "failed") && (
            <div className="grid lg:grid-cols-[1fr,320px] gap-4 items-start">
              <fieldset className="space-y-2">
                <legend className="text-sm font-medium text-slate-700 mb-1">
                  Compression preset
                </legend>
                {PRESETS.map((p) => {
                  const pred = durationSec
                    ? predictedBytes(p, durationSec, sourceBitrate) : 0;
                  const red = file.size > 0 && pred > 0
                    ? Math.round((1 - pred / file.size) * 100) : 0;
                  const clamped = isClamped(p, sourceBitrate);
                  return (
                    <label key={p.id}
                           className={`block border rounded-lg p-3 cursor-pointer transition ${
                             presetId === p.id
                               ? "border-indigo-400 bg-indigo-50"
                               : "border-slate-200 hover:border-slate-300"
                           }`}>
                      <div className="flex items-start gap-3">
                        <input
                          type="radio"
                          name="preset"
                          checked={presetId === p.id}
                          onChange={() => setPresetId(p.id)}
                          className="mt-1"
                        />
                        <div className="flex-1">
                          <div className="font-medium text-slate-900 text-sm flex items-center gap-2 flex-wrap">
                            {p.label}
                            {p.id === recId && (
                              <span className="text-xs px-2 py-0.5 bg-emerald-100 text-emerald-700 border border-emerald-200 rounded">
                                Recommended
                              </span>
                            )}
                            {clamped && (
                              <span className="text-xs px-2 py-0.5 bg-slate-100 text-slate-600 border border-slate-200 rounded"
                                    title="The preset's bitrate exceeds the source's, so encoding is capped at the source — going higher would grow the file without adding quality.">
                                capped at source ({(effectiveBps(p, sourceBitrate) / 1_000_000).toFixed(1)} Mbps)
                              </span>
                            )}
                          </div>
                          <div className="text-xs text-slate-500 mt-0.5">{p.description}</div>
                          {durationSec > 0 && (
                            <div className="text-xs text-slate-600 mt-1">
                              Predicted output: <strong>{fmtBytes(pred)}</strong>
                              <span className={`ml-2 ${red > 0 ? "text-emerald-700" : "text-slate-500"}`}>
                                ({red > 0 ? `≈${red}% smaller` : "≈ same size"})
                              </span>
                            </div>
                          )}
                        </div>
                      </div>
                    </label>
                  );
                })}
              </fieldset>

              {/* Quality-preview sidebar */}
              <aside className="border border-slate-200 rounded-lg p-4 lg:sticky lg:top-2 bg-slate-50">
                <h3 className="text-sm font-medium text-slate-700">
                  Check quality first
                </h3>
                <p className="text-xs text-slate-500 mt-1 mb-3">
                  Encodes a {SAMPLE_SECONDS}s clip from the middle of the video
                  at the selected preset — judge sharpness and get a measured
                  size estimate before the full run.
                </p>
                <button
                  onClick={runSample}
                  disabled={sampleBusy || !presetId}
                  className="w-full px-3 py-2 text-sm font-medium text-indigo-700 bg-white border border-indigo-300 rounded-lg hover:bg-indigo-50 disabled:opacity-50"
                >
                  {sampleBusy
                    ? `Sampling ~${SAMPLE_SECONDS}s…`
                    : sampleValid ? "Re-run sample" : `Preview ${SAMPLE_SECONDS}s sample`}
                </button>
                {sampleValid && (
                  <div className="mt-3 space-y-2">
                    <video controls src={sampleUrl!} autoPlay loop muted
                           className="w-full rounded border border-slate-200 bg-slate-900" />
                    <div className="text-xs text-slate-600">
                      Sample: <strong>{fmtBytes(sampleBytes)}</strong> for {SAMPLE_SECONDS}s
                      <br />
                      Measured full-video estimate:{" "}
                      <strong>{fmtBytes(measuredEstimate)}</strong>
                      {file.size > 0 && measuredEstimate > 0 && (
                        <span className={measuredEstimate < file.size ? "text-emerald-700 ml-1" : "text-rose-600 ml-1"}>
                          ({measuredEstimate < file.size
                            ? `≈${Math.round((1 - measuredEstimate / file.size) * 100)}% smaller`
                            : "larger than original — pick a lower preset or upload original"})
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-slate-500">
                      Too soft? Pick a higher preset and re-sample. Looks
                      fine? Start the full compression.
                    </p>
                  </div>
                )}
                {predictedSize > 0 && !sampleValid && (
                  <div className="mt-3 text-xs text-slate-500">
                    Current selection predicts{" "}
                    <strong>{fmtBytes(predictedSize)}</strong> (±15%).
                  </div>
                )}
              </aside>
            </div>
          )}

          {/* Compression progress */}
          {phase === "compressing" && (
            <div className="bg-slate-50 border border-slate-200 rounded-lg p-4">
              <div className="text-sm text-slate-700 mb-2 flex items-center justify-between">
                <span>Compressing…</span>
                <span className="font-mono">{(progress * 100).toFixed(0)}%</span>
              </div>
              <div className="h-2 bg-slate-200 rounded-full overflow-hidden">
                <div className="h-full bg-indigo-500 transition-all"
                     style={{ width: `${progress * 100}%` }} />
              </div>
              <p className="text-xs text-slate-500 mt-2">
                Re-encoding runs at ~1× playback speed. You can leave this tab
                in the background — just don&apos;t close it.
              </p>
            </div>
          )}

          {/* Side-by-side preview when done */}
          {phase === "done" && compressedBlob && compressedUrl && originalUrl && (
            <div>
              <h3 className="text-sm font-medium text-slate-700 mb-2">
                Preview — compare before/after
              </h3>
              <div className="grid grid-cols-2 gap-3 text-xs">
                <div>
                  <div className="mb-1 text-slate-600">
                    Original — <strong>{fmtBytes(file.size)}</strong>
                  </div>
                  <video controls src={originalUrl}
                         className="w-full rounded border border-slate-200 bg-slate-900" />
                </div>
                <div>
                  <div className="mb-1 text-slate-600">
                    Compressed — <strong>{fmtBytes(compressedBlob.size)}</strong>
                    {file.size > 0 && (
                      <span className={`ml-2 ${compressedBlob.size < file.size ? "text-emerald-700" : "text-rose-600"}`}>
                        ({compressedBlob.size < file.size
                          ? `${Math.round((1 - compressedBlob.size / file.size) * 100)}% smaller`
                          : "larger than original — upload the original instead"})
                      </span>
                    )}
                  </div>
                  <video controls src={compressedUrl}
                         className="w-full rounded border border-slate-200 bg-slate-900" />
                </div>
              </div>
              <p className="text-xs text-slate-500 mt-2">
                Play both for ~10s on the most detailed section to verify the
                compressed version still reads clearly. If it&apos;s too soft,
                pick a higher-bitrate preset above and re-compress.
              </p>
            </div>
          )}
        </div>

        {/* Footer actions */}
        <footer className="p-5 border-t border-slate-200 flex flex-wrap justify-end gap-2 bg-slate-50 sticky bottom-0">
          <button onClick={handleCancel}
                  className="px-4 py-2 text-sm font-medium text-slate-700 bg-white border border-slate-300 rounded-lg hover:bg-slate-50">
            Cancel
          </button>
          <button onClick={() => onUseOriginal(file)}
                  className="px-4 py-2 text-sm font-medium text-slate-700 bg-white border border-slate-300 rounded-lg hover:bg-slate-50">
            Upload original ({fmtBytes(file.size)})
          </button>
          {phase === "ready" && (
            <button onClick={runCompression}
                    disabled={!presetId}
                    className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:bg-slate-300">
              Start compression
            </button>
          )}
          {phase === "compressing" && (
            <button onClick={() => cancelCompressionRef.current?.()}
                    className="px-4 py-2 text-sm font-medium text-rose-700 bg-white border border-rose-300 rounded-lg hover:bg-rose-50">
              Stop
            </button>
          )}
          {phase === "done" && compressedBlob && (
            <>
              <button onClick={runCompression}
                      className="px-4 py-2 text-sm font-medium text-slate-700 bg-white border border-slate-300 rounded-lg hover:bg-slate-50">
                Try a different preset
              </button>
              <button onClick={handleUseCompressed}
                      className="px-4 py-2 text-sm font-medium text-white bg-emerald-600 rounded-lg hover:bg-emerald-700">
                Upload compressed ({fmtBytes(compressedBlob.size)})
              </button>
            </>
          )}
          {phase === "failed" && (
            <button onClick={runCompression}
                    className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700">
              Retry
            </button>
          )}
        </footer>
      </div>
    </div>
  );
}
