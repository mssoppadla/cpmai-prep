import { ImageResponse } from "next/og";

export const runtime = "edge";
export const alt = "CPMAI Prep — Pass the CPMAI Certification on Your First Attempt";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function Image() {
  return new ImageResponse(
    (
      <div
        style={{
          background: "linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%)",
          width: "100%", height: "100%",
          display: "flex", flexDirection: "column",
          alignItems: "center", justifyContent: "center",
          padding: 80, textAlign: "center",
          fontFamily: "system-ui, -apple-system, sans-serif",
        }}
      >
        <div style={{
          fontSize: 28, fontWeight: 600, color: "rgba(255,255,255,0.85)",
          letterSpacing: "0.15em", textTransform: "uppercase", marginBottom: 32,
        }}>
          CPMAI Prep
        </div>
        <div style={{
          fontSize: 80, fontWeight: 800, color: "white",
          lineHeight: 1.05, letterSpacing: "-0.02em",
        }}>
          Pass the CPMAI<br />Certification
        </div>
        <div style={{
          fontSize: 32, color: "rgba(255,255,255,0.92)",
          marginTop: 40, maxWidth: 900, lineHeight: 1.3,
        }}>
          Realistic mock exams · AI coaching · Detailed reasoning
        </div>
      </div>
    ),
    { ...size }
  );
}
