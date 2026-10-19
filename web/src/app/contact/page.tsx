import type { Metadata } from "next";
import Link from "next/link";

import { SITE_NAME } from "@/lib/blog";

export const metadata: Metadata = {
  title: `Contact | ${SITE_NAME}`,
  description: "Contact MTG Deck Lab with feedback, bug reports, card suggestions or questions about your data.",
  alternates: { canonical: "/contact" },
};

const CONTACT_EMAIL = process.env.NEXT_PUBLIC_CONTACT_EMAIL ?? "";

export default function ContactPage() {
  return (
    <main className="shell legal-page">
      <h1>Contact</h1>
      <p>
        Questions, bug reports and feedback are all welcome. Feedback on generated decks is especially useful: if a deck
        made a pick you disagree with, tell us which deck and which card.
      </p>
      {CONTACT_EMAIL ? (
        <p className="contact-email">
          Email: <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>
        </p>
      ) : null}

      <h2>What to include</h2>
      <ul>
        <li>
          <strong>A deck that looks wrong:</strong> the format, what you asked for, the card that seems out of place,
          and the deck&apos;s share link if you saved it.
        </li>
        <li>
          <strong>A bug:</strong> what you clicked, what you expected and what happened instead. A screenshot helps.
        </li>
        <li>
          <strong>A saved deck you want deleted:</strong> its share link. See the <Link href="/privacy">privacy page</Link>{" "}
          for what is stored.
        </li>
        <li>
          <strong>Guide corrections or topic ideas:</strong> the guide&apos;s title and what should change.
        </li>
      </ul>
    </main>
  );
}
