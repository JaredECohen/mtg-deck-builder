import type { FormatName, GenerationMode } from "@/lib/types";

/** One-click example briefs, per format. */
export const EXAMPLE_BRIEFS: Record<FormatName, string[]> = {
  modern: [
    "Mono-red burn under $150",
    "U/R prowess with cheap cantrips",
    "Golgari midrange with discard and graveyard value",
    "Azorius control with counterspells and planeswalkers"
  ],
  standard: [
    "Mono-white aggro with an efficient curve",
    "Dimir control that wins with one big threat",
    "Gruul stompy with big creatures",
    "Budget Rakdos sacrifice under $60"
  ],
  pioneer: [
    "Mono-green devotion ramp",
    "Rakdos midrange with removal and discard",
    "Izzet phoenix spells deck",
    "Boros heroic aggro"
  ],
  legacy: [
    "Delver tempo with free counterspells",
    "Mono-red prison with chalice effects",
    "Reanimator that cheats in a big threat early",
    "Death and Taxes white weenie"
  ],
  commander: [
    "Elf tribal that goes wide and draws lots of cards",
    "Spellslinger that copies instants and sorceries",
    "Lifegain with a strong drain finish",
    "Budget artifact tokens under $100"
  ]
};

export const MODE_OPTIONS: { value: GenerationMode; label: string; description: string }[] = [
  {
    value: "constraint-aware",
    label: "Balanced",
    description: "Proven shells bent to fit your budget, colors and card choices."
  },
  {
    value: "fast-competitive",
    label: "Fast competitive",
    description: "Stick closely to the strongest known lists. Least creative."
  },
  {
    value: "creative-but-viable",
    label: "Creative but viable",
    description: "Rotate in less common cards while keeping a legal, playable shell."
  }
];

/** WotC Commander brackets with plain-English names. */
export const BRACKET_OPTIONS: { value: number; label: string; description: string }[] = [
  { value: 1, label: "1 · Exhibition", description: "Theme first; power is secondary." },
  { value: 2, label: "2 · Core", description: "Roughly a modern preconstructed deck. No game changers." },
  { value: 3, label: "3 · Upgraded", description: "Stronger than a precon; up to three game changers." },
  { value: 4, label: "4 · Optimized", description: "High power with no restrictions, but not tuned for cEDH." },
  { value: 5, label: "5 · cEDH", description: "Competitive Commander: the fastest, most efficient lists." }
];

export function bracketLabel(value: number | null | undefined): string {
  return BRACKET_OPTIONS.find((option) => option.value === value)?.label ?? "Unknown";
}

/** "4 Lightning Bolt" / "4x Lightning Bolt" / "Lightning Bolt" → "Lightning Bolt". */
export function parseCardNameLines(text: string): string[] {
  const names: string[] = [];
  const seen = new Set<string>();
  for (const line of text.split(/\r?\n/)) {
    const name = line.replace(/^\s*\d+\s*x?\s+/i, "").trim();
    if (!name || seen.has(name.toLowerCase())) continue;
    seen.add(name.toLowerCase());
    names.push(name);
  }
  return names;
}
