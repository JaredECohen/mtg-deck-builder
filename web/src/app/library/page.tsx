import type { Metadata } from "next";

import { DeckLibrary } from "@/components/deck-library";

export const metadata: Metadata = {
  title: "Your decks | MTG Deck Lab",
  description: "Decks you saved while signed in to MTG Deck Lab.",
  robots: { index: false, follow: false },
  alternates: { canonical: "/library" }
};

export default function LibraryPage() {
  return (
    <main className="shell legal-page">
      <h1>Your library</h1>
      <DeckLibrary />
    </main>
  );
}
