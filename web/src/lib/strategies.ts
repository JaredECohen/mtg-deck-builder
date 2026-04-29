export const COLORS = ["W", "U", "B", "R", "G", "C"] as const;

export const STRATEGY_OPTIONS = [
  { id: "aggro", label: "Aggro", description: "Fast pressure with low-curve threats and efficient damage.", playstyleTags: ["aggro"], themeTags: [] },
  { id: "control", label: "Control", description: "Trade resources early, then win with inevitability.", playstyleTags: ["control", "interaction"], themeTags: [] },
  { id: "midrange", label: "Midrange", description: "Flexible threats and interaction aimed at stabilizing and pivoting.", playstyleTags: ["midrange"], themeTags: [] },
  { id: "combo", label: "Combo", description: "Assemble a compact engine or finish that ends the game quickly.", playstyleTags: ["combo"], themeTags: [] },
  { id: "tempo", label: "Tempo", description: "Protect a small lead with cheap interaction and efficient pressure.", playstyleTags: ["tempo", "spells", "aggro"], themeTags: [] },
  { id: "ramp", label: "Ramp", description: "Accelerate mana to deploy stronger threats ahead of schedule.", playstyleTags: ["ramp"], themeTags: [] },
  { id: "spellslinger", label: "Spellslinger", description: "High spell density with payoffs for casting instants and sorceries.", playstyleTags: ["spells", "prowess", "tempo"], themeTags: [] },
  { id: "tokens", label: "Tokens", description: "Go wide with scalable boards and anthem-style payoffs.", playstyleTags: ["tokens"], themeTags: ["tokens"] },
  { id: "tribal", label: "Tribal", description: "Synergy built around a creature type or tribe-specific payoffs.", playstyleTags: ["tribal"], themeTags: ["tribal", "slivers"] },
  { id: "lifegain", label: "Lifegain", description: "Snowball value from recurring life gain and payoff creatures.", playstyleTags: ["lifegain"], themeTags: ["lifegain"] },
  { id: "sacrifice", label: "Sacrifice", description: "Convert creatures or tokens into cards, damage, or board control.", playstyleTags: ["sacrifice", "combo"], themeTags: ["sacrifice"] },
  { id: "reanimator", label: "Reanimator", description: "Load the graveyard and cheat high-impact threats back into play.", playstyleTags: ["reanimator", "midrange"], themeTags: ["graveyard"] }
] as const;

export type StrategyId = (typeof STRATEGY_OPTIONS)[number]["id"];

export function activeTags(selected: StrategyId[]): { playstyle: string[]; theme: string[] } {
  const active = STRATEGY_OPTIONS.filter((option) => selected.includes(option.id));
  return {
    playstyle: [...new Set(active.flatMap((option) => option.playstyleTags))],
    theme: [...new Set(active.flatMap((option) => option.themeTags))]
  };
}

export function toggleValue<T>(value: T, values: T[]): T[] {
  if (values.includes(value)) return values.filter((item) => item !== value);
  return [...values, value];
}

export function parseBudgetInput(value: string): number | undefined {
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  const parsed = Number(trimmed);
  if (!Number.isFinite(parsed) || parsed < 0) return undefined;
  return parsed;
}
