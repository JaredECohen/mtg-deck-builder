import type { CardRef, CardTypeMap, PrimaryCardType } from "@/lib/types";

// Display order for deck breakdown sections. Matches the convention used in
// most decklist tools (creatures and walkers up top, lands at the bottom).
export const PRIMARY_TYPE_ORDER: PrimaryCardType[] = [
  "Creature",
  "Planeswalker",
  "Instant",
  "Sorcery",
  "Enchantment",
  "Artifact",
  "Battle",
  "Land",
  "Other"
];

const PLURAL_LABELS: Record<PrimaryCardType, string> = {
  Creature: "Creatures",
  Planeswalker: "Planeswalkers",
  Instant: "Instants",
  Sorcery: "Sorceries",
  Enchantment: "Enchantments",
  Artifact: "Artifacts",
  Battle: "Battles",
  Land: "Lands",
  Other: "Other"
};

export function pluralLabel(type: PrimaryCardType): string {
  return PLURAL_LABELS[type];
}

export type CardTypeSection = {
  type: PrimaryCardType;
  label: string;
  cards: CardRef[];
  count: number;
};

export function groupByType(cards: CardRef[], typeMap: CardTypeMap | undefined): CardTypeSection[] {
  if (!cards.length) return [];
  const buckets = new Map<PrimaryCardType, CardRef[]>();
  for (const ref of cards) {
    const type = (typeMap?.[ref.name] ?? "Other") as PrimaryCardType;
    if (!buckets.has(type)) buckets.set(type, []);
    buckets.get(type)!.push(ref);
  }
  return PRIMARY_TYPE_ORDER.flatMap((type) => {
    const bucket = buckets.get(type);
    if (!bucket || !bucket.length) return [];
    bucket.sort((a, b) => a.name.localeCompare(b.name));
    return [{
      type,
      label: pluralLabel(type),
      cards: bucket,
      count: bucket.reduce((sum, ref) => sum + ref.quantity, 0)
    }];
  });
}
