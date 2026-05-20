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
 *   - Compute source bitrate (file.size * 8 / duration) so we can
 *     recommend a sensible target.
 *   - Offer resolution × bitrate presets, marking ONE as recommended
 *     based on duration heuristics.
 *   - On user pick: draw frames from the <video> to a <canvas> at
 *     target resolution; capture the canvas stream + the video's audio
 *     track; pipe both into a MediaRecorder at the chosen bitrate.
 *   - Show real-time progress (video.currentTime / video.duration).
 *   - When done, blob URL goes into a preview <video>; admin chooses
 *     "Upload compressed" or "Upload original".
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
 *     ±15%.
 */
import { useCallback, useEffect, useRef, useState } from "react";


export interface CompressionPreset {
  id: string;
  label: string;
  width: number;
  height: number;
  /** Total bitrate (video + audio) target in bits/sec. We split:
   *  audio fixed at 128_000; video gets the remainder. */
  totalBitsPerSecond: number;
  description: string;
}


/** Preset library. Order matters — these render top-to-bottom. */
const PRESETS: CompressionPreset[] = [
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


/** Pick the preset most appropriate for a given duration. Heuristic:
 *  short → high quality acceptable; very long → throttle harder. */
function recommendedPresetId(durationSec: number): string {
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


/** Predicted output bytes from preset + duration. Real-world is ±15%. */
function predictedBytes(preset: CompressionPreset, durationSec: number): number {
  return Math.round((preset.totalBitsPerSecond * durationSec) / 8);
}


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
  | "compressing"       // MediaRecorder running
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

  // Refs for the offscreen probing + compressing video element.
  const probeRef = useRef<HTMLVideoElement | null>(null);
  const cancelCompressionRef = useRef<(() => void) | null>(null);

  // Stable object URL for the source so probing + preview share it.
  useEffect(() => {
    const url = URL.createObjectURL(file);
    setOriginalUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

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
      setPresetId(recommendedPresetId(dur));
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
  }, [originalUrl]);

  // Phase 2: run MediaRecorder compression with the selected preset.
  const runCompression = useCallback(async () => {
    const preset = PRESETS.find((p) => p.id === presetId);
    if (!preset || !originalUrl) return;
    setErr(null);
    setProgress(0);
    setCompressedBlob(null);
    setCompressedUrl((cur) => { if (cur) URL.revokeObjectURL(cur); return null; });
    setPhase("compressing");

    // Aspect-preserving resize: scale so the source fits inside
    // preset.width × preset.height. Maintains the source's original
    // ratio (otherwise wide source gets squashed into 16:9 preset).
    const srcAspect = intrinsicW / intrinsicH;
    let outW = preset.width;
    let outH = preset.height;
    if (srcAspect > outW / outH) {
      outH = Math.round(outW / srcAspect);
      // Even dims required by some codecs
      if (outH % 2) outH -= 1;
    } else {
      outW = Math.round(outH * srcAspect);
      if (outW % 2) outW -= 1;
    }

    // Create the live <video> we'll drive playback through.
    const v = document.createElement("video");
    v.src = originalUrl;
    v.muted = false;            // we WANT the audio track to capture
    v.crossOrigin = "anonymous";
    v.playsInline = true;
    await new Promise<void>((res, rej) => {
      v.onloadeddata = () => res();
      v.onerror = () => rej(new Error("source video failed to load for compression"));
    });

    const canvas = document.createElement("canvas");
    canvas.width = outW;
    canvas.height = outH;
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      setErr("Could not get a 2D canvas context — browser may be in a degraded state.");
      setPhase("failed");
      return;
    }

    // Build a composite stream: video from canvas + audio from <video>.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const videoStream: MediaStream = (canvas as any).captureStream(30);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const audioOnly: MediaStream = (v as any).captureStream?.();
    if (audioOnly) {
      audioOnly.getAudioTracks().forEach((t) => videoStream.addTrack(t));
    }

    // Pick a mimeType the browser supports.
    const candidates = [
      "video/webm;codecs=vp9,opus",
      "video/webm;codecs=vp8,opus",
      "video/webm",
    ];
    const mimeType = candidates.find((c) => MediaRecorder.isTypeSupported(c)) ?? "video/webm";

    // Split bitrate: audio gets 128k, video gets the rest.
    const audioBps = 128_000;
    const videoBps = Math.max(200_000, preset.totalBitsPerSecond - audioBps);

    const recorder = new MediaRecorder(videoStream, {
      mimeType,
      videoBitsPerSecond: videoBps,
      audioBitsPerSecond: audioBps,
    });
    const chunks: BlobPart[] = [];
    recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };

    let frameLoop: number | null = null;
    let cancelled = false;
    cancelCompressionRef.current = () => {
      cancelled = true;
      try { recorder.state === "recording" && recorder.stop(); } catch {}
      try { v.pause(); } catch {}
      if (frameLoop != null) cancelAnimationFrame(frameLoop);
      videoStream.getTracks().forEach((t) => t.stop());
    };

    function drawFrame() {
      if (cancelled || v.ended || v.paused) {
        if (recorder.state === "recording") recorder.stop();
        return;
      }
      ctx!.drawImage(v, 0, 0, outW, outH);
      setProgress(durationSec > 0 ? Math.min(1, v.currentTime / durationSec) : 0);
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

    try {
      recorder.start();
      // Audio capture requires play(). Start drawing on the next tick.
      await v.play();
      frameLoop = requestAnimationFrame(drawFrame);
      const blob = await done;
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
  }, [presetId, originalUrl, intrinsicW, intrinsicH, durationSec]);

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
    onCancel();
  }

  // ───────────────────────── render ─────────────────────────

  const currentPreset = PRESETS.find((p) => p.id === presetId);
  const predictedSize = currentPreset && durationSec
    ? predictedBytes(currentPreset, durationSec)
    : 0;
  const sourceBitrate = durationSec > 0 ? (file.size * 8) / durationSec : 0;
  const reductionPct = file.size > 0 && predictedSize > 0
    ? Math.round((1 - predictedSize / file.size) * 100)
    : 0;
  const recId = durationSec ? recommendedPresetId(durationSec) : "";

  return (
    <div className="fixed inset-0 z-50 bg-slate-900/50 flex items-start justify-center p-4 overflow-y-auto">
      <div className="bg-white rounded-xl border border-slate-200 max-w-3xl w-full my-8 max-h-[90vh] overflow-y-auto">
        <header className="p-5 border-b border-slate-200">
          <h2 className="font-semibold text-slate-900">Compress before upload?</h2>
          <p className="text-xs text-slate-500 mt-1">
            Smaller files upload faster and use less of your storage budget.
            Compression runs entirely in your browser; nothing leaves until you confirm.
          </p>
        </header>

        <div className="p-5 space-y-4">
          {/* Source info */}
          <div className="grid grid-cols-3 gap-3 text-sm">
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
          </div>

          {sourceBitrate > 0 && (
            <div className="text-xs text-slate-600">
              Source bitrate: <strong>{(sourceBitrate / 1_000_000).toFixed(1)} Mbps</strong>
              {sourceBitrate > 5_500_000 && (
                <span className="ml-2 text-amber-700">
                  (higher than necessary for most lesson content — strongly recommend compressing)
                </span>
              )}
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

          {/* Preset picker — shown once we know duration */}
          {(phase === "ready" || phase === "failed") && (
            <fieldset className="space-y-2">
              <legend className="text-sm font-medium text-slate-700 mb-1">
                Compression preset
              </legend>
              {PRESETS.map((p) => (
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
                      <div className="font-medium text-slate-900 text-sm flex items-center gap-2">
                        {p.label}
                        {p.id === recId && (
                          <span className="text-xs px-2 py-0.5 bg-emerald-100 text-emerald-700 border border-emerald-200 rounded">
                            Recommended for {fmtDuration(durationSec)} lessons
                          </span>
                        )}
                      </div>
                      <div className="text-xs text-slate-500 mt-0.5">{p.description}</div>
                      {durationSec > 0 && (
                        <div className="text-xs text-slate-600 mt-1">
                          Predicted output: <strong>{fmtBytes(predictedBytes(p, durationSec))}</strong>
                          {p.id === presetId && file.size > 0 && (
                            <span className="ml-2 text-emerald-700">
                              ({reductionPct > 0 ? `≈${reductionPct}% smaller` : "no reduction"})
                            </span>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                </label>
              ))}
            </fieldset>
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
                      <span className="ml-2 text-emerald-700">
                        ({Math.round((1 - compressedBlob.size / file.size) * 100)}% smaller)
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
