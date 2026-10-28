export type DeckVisibilityChoice = "public" | "unlisted";

/** What the save button sends. The API's own default is unlisted. */
export function visibilityForNewDeck(hideFromSearch: boolean): DeckVisibilityChoice {
  return hideFromSearch ? "unlisted" : "public";
}
