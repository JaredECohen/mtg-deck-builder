import { ImageResponse } from "next/og";

/** Default 1200×630 card for link previews. Deck pages use their own image. */
export function siteCardImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background: "#0c1118",
          color: "#edf3fb",
          padding: "72px",
          fontFamily: "sans-serif",
        }}
      >
        <div style={{ display: "flex", fontSize: 28, letterSpacing: 4, color: "#f97316", fontWeight: 700 }}>
          MTG DECK LAB
        </div>
        <div style={{ display: "flex", flexDirection: "column" }}>
          <div style={{ display: "flex", fontSize: 68, fontWeight: 700, lineHeight: 1.05 }}>
            Build a legal Magic deck
          </div>
          <div style={{ display: "flex", fontSize: 32, color: "#a9b5c5", marginTop: 28 }}>
            A reason for every card, a mana curve, and a price.
          </div>
        </div>
        <div style={{ display: "flex", fontSize: 26, color: "#38bdf8" }}>
          Standard · Pioneer · Modern · Legacy · Commander
        </div>
      </div>
    ),
    { width: 1200, height: 630 },
  );
}
