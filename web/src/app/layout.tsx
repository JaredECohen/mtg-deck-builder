import "./globals.css";

import type { ReactNode } from "react";

export const metadata = {
  title: "MTG Deck Builder",
  description: "Generate Magic: The Gathering decks with transparent reasoning."
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
