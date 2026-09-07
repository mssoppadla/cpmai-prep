/**
 * Size-math pins for the video compression dialog (prod report
 * 2026-09-07): a 910 MB / 176-minute lecture at 0.7 Mbps source showed
 * "predicted 6.16 GB" for the 5 Mbps preset — predictions used the raw
 * preset bitrate, so every preset above the source INFLATED the file.
 * The fix clamps the effective bitrate to ~90% of the source.
 */
import { describe, expect, it } from "vitest";
import {
  PRESETS, effectiveBps, isClamped, predictedBytes, recommendedPresetId,
} from "@/components/lms/VideoCompressDialog";

// The prod file: 910 MB, 176:28 → ~0.72 Mbps source.
const DUR = 176 * 60 + 28;
const SIZE = 910 * 1024 ** 2;
const SRC_BPS = (SIZE * 8) / DUR;

describe("compression size math", () => {
  it("never predicts an output larger than the source", () => {
    for (const p of PRESETS) {
      expect(predictedBytes(p, DUR, SRC_BPS)).toBeLessThan(SIZE);
    }
  });

  it("clamps effective bitrate to ~90% of a low-bitrate source", () => {
    for (const p of PRESETS) {
      expect(effectiveBps(p, SRC_BPS)).toBeLessThanOrEqual(SRC_BPS * 0.9 + 1);
      expect(isClamped(p, SRC_BPS)).toBe(true);   // 0.72 Mbps < every preset
    }
  });

  it("keeps a quality floor even for tiny sources", () => {
    const tiny = 200_000; // 0.2 Mbps source
    for (const p of PRESETS) {
      expect(effectiveBps(p, tiny)).toBeGreaterThanOrEqual(350_000);
    }
  });

  it("uses the raw preset bitrate when the source is high-bitrate", () => {
    const high = 12_000_000; // screen recording at 12 Mbps
    for (const p of PRESETS) {
      expect(effectiveBps(p, high)).toBe(p.totalBitsPerSecond);
      expect(isClamped(p, high)).toBe(false);
    }
  });

  it("recommends the highest resolution when the clamp dominates (same bytes, more pixels)", () => {
    // 1080p source at 0.72 Mbps: all presets clamp to the same rate, so
    // recommend 1080p rather than 480p.
    expect(recommendedPresetId(DUR, SRC_BPS, 1080)).toBe("1080p-high");
    // 720p source: never recommend above the source's own resolution.
    expect(recommendedPresetId(DUR, SRC_BPS, 720)).toBe("720p-med");
  });

  it("falls back to the duration heuristic for high-bitrate sources", () => {
    const high = 12_000_000;
    expect(recommendedPresetId(3 * 60, high, 1080)).toBe("1080p-med");
    expect(recommendedPresetId(20 * 60, high, 1080)).toBe("720p-med");
    expect(recommendedPresetId(60 * 60, high, 1080)).toBe("720p-low");
    expect(recommendedPresetId(120 * 60, high, 1080)).toBe("480p-med");
  });
});
