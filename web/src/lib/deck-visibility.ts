export type DeckVisibilityChoice = "public" | "unlisted";

/** Public only when the user opts in. The unchecked save button stays unlisted. */
export function visibilityForNewDeck(publishPublic: boolean): DeckVisibilityChoice {
  return publishPublic ? "public" : "unlisted";
}
