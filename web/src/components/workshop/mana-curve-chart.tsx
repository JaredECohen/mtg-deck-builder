"use client";

/**
 * ManaCurveChart — a lightweight bar chart of spell counts by mana value.
 * Pure presentational SVG-free (div bars) so it has no chart-lib
 * dependency. Lands are excluded from the curve.
 */

export type CurveEntry = { name: string; quantity: number; manaValue: number; isLand: boolean };

const MAX_BUCKET = 7; // 7+ collapses into one bucket

export function ManaCurveChart({ cards }: { cards: CurveEntry[] }) {
  const buckets = new Array<number>(MAX_BUCKET + 1).fill(0);
  for (const card of cards) {
    if (card.isLand) continue;
    const idx = Math.min(MAX_BUCKET, Math.max(0, Math.round(card.manaValue)));
    buckets[idx] += card.quantity;
  }
  const peak = Math.max(1, ...buckets);

  return (
    <section aria-label="Mana curve" className="mana-curve">
      <h3>Mana curve</h3>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 6, height: 120 }}>
        {buckets.map((count, mv) => (
          <div key={mv} style={{ flex: 1, textAlign: "center" }}>
            <div
              role="img"
              aria-label={`${count} cards at mana value ${mv === MAX_BUCKET ? "7+" : mv}`}
              style={{
                height: `${(count / peak) * 100}%`,
                minHeight: count > 0 ? 4 : 0,
                background: "#6366f1",
                borderRadius: "3px 3px 0 0"
              }}
            />
            <div style={{ fontSize: 11, marginTop: 4 }}>{mv === MAX_BUCKET ? "7+" : mv}</div>
            <div style={{ fontSize: 11, color: "#6b7280" }}>{count}</div>
          </div>
        ))}
      </div>
    </section>
  );
}
