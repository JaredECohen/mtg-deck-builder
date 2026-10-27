import { ImageResponse } from "next/og";

import { formatLabel, formatPrice, type PublicDeck } from "@/lib/public-deck";

const COLOR_HEX: Record<string, string> = {
  W: "#f4efc7",
  U: "#0e68ab",
  B: "#3d3a3a",
  R: "#d3202a",
  G: "#00733e",
  C: "#c4c4c4"
};

const COLOR_INK: Record<string, string> = {
  W: "#1a1a1a",
  U: "#ffffff",
  B: "#ffffff",
  R: "#ffffff",
  G: "#ffffff",
  C: "#1a1a1a"
};

function clip(value: string, max: number): string {
  const text = value.trim();
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

/** 1200×630 card for Discord, X, and Reddit link previews. */
export function deckCardImage(deck: PublicDeck) {
  const colors = deck.colors.filter((color) => color in COLOR_HEX);
  const price = formatPrice(deck.price_usd);
  const keyCards = (deck.key_cards.length ? deck.key_cards : deck.mainboard.map((card) => card.name)).slice(0, 4);
  const meta = [formatLabel(deck.format), deck.commander ? clip(deck.commander, 40) : "", price ?? ""]
    .filter(Boolean)
    .join("  ·  ");

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
          padding: "64px 72px",
          fontFamily: "sans-serif"
        }}
      >
        <div style={{ display: "flex", flexDirection: "column" }}>
          <div style={{ display: "flex", fontSize: 22, letterSpacing: 3, color: "#f97316", fontWeight: 700 }}>
            MTG DECK LAB
          </div>
          <div style={{ display: "flex", fontSize: 68, fontWeight: 700, lineHeight: 1.05, marginTop: 28 }}>
            {clip(deck.name || "Untitled deck", 48)}
          </div>
          <div style={{ display: "flex", alignItems: "center", marginTop: 28, fontSize: 28, color: "#a9b5c5" }}>
            <div style={{ display: "flex" }}>{meta}</div>
            <div style={{ display: "flex", marginLeft: 20 }}>
              {colors.map((color) => (
                <div
                  key={color}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    width: 36,
                    height: 36,
                    borderRadius: 18,
                    marginRight: 8,
                    background: COLOR_HEX[color],
                    color: COLOR_INK[color],
                    fontSize: 18,
                    fontWeight: 700
                  }}
                >
                  {color}
                </div>
              ))}
            </div>
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column" }}>
          <div style={{ display: "flex", fontSize: 20, letterSpacing: 2, color: "#a9b5c5" }}>KEY CARDS</div>
          <div style={{ display: "flex", fontSize: 32, marginTop: 12 }}>
            {keyCards.length ? keyCards.map((name) => clip(name, 28)).join("   ·   ") : "Shared deck list"}
          </div>
        </div>
      </div>
    ),
    { width: 1200, height: 630 }
  );
}
