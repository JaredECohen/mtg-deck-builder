import type { Metadata } from "next";
import Link from "next/link";

import { AUTHOR, SITE_NAME } from "@/lib/blog";

export const metadata: Metadata = {
  title: `About | ${SITE_NAME}`,
  description:
    "MTG Deck Lab is a free Magic: The Gathering deck builder that explains every pick. Who makes it, how it works, and where its data comes from.",
  alternates: { canonical: "/about" },
};

export default function AboutPage() {
  return (
    <main className="shell legal-page">
      <h1>About MTG Deck Lab</h1>
      <p>
        MTG Deck Lab is a free deck builder for Magic: The Gathering. Tell it a format, colors and a play style, or
        describe the deck you want in a sentence, and it builds a complete, legal deck. Then it shows its work: why each
        card is there, what the mana curve looks like, how the deck plans to win and what it costs to buy.
      </p>
      <p>
        It is built and run by {AUTHOR}. The goal is a deck builder that teaches instead of just handing over a list:
        every choice should be something you can read, question and change.
      </p>

      <h2>What it does</h2>
      <ul>
        <li>
          <strong>Builds decks for five formats:</strong> Standard, Pioneer, Modern, Legacy and Commander, with card
          legality and Commander color identity checked before anything is returned.
        </li>
        <li>
          <strong>Explains every card.</strong> Each card has a &ldquo;Why?&rdquo; note: whether it came from the
          archetype&apos;s core list, fills a role like removal or card draw, or works with your commander.
        </li>
        <li>
          <strong>Writes a game plan</strong> with the deck&apos;s roles, mana curve, key mechanics and, for
          best-of-three formats, a 15-card sideboard grouped by the matchups it answers.
        </li>
        <li>
          <strong>Respects a budget.</strong> Set a price limit and expensive cards are swapped for cheaper ones that do
          the same job. Every deck shows an estimated price and a ready-made TCGplayer cart.
        </li>
        <li>
          <strong>Estimates Commander brackets</strong> using the official bracket system, and can build to the bracket
          your playgroup uses.
        </li>
        <li>
          <strong>Analyzes your own lists.</strong> Paste a decklist to see its curve, roles, archetype and suggested
          improvements.
        </li>
      </ul>

      <h2>How it works</h2>
      <p>
        Decks start from archetype templates for each format and are filled from a database of more than 30,000 cards.
        Every card is profiled by what it actually does, read from its rules text. Card data comes from{" "}
        <a href="https://scryfall.com" rel="noopener noreferrer" target="_blank">
          Scryfall
        </a>{" "}
        and is refreshed every week. When you describe a deck in words, an AI model (Anthropic&apos;s Claude) reads the
        brief and the coaching notes are written with it. The deck itself is assembled and legality-checked by Deck
        Lab&apos;s own rules engine.
      </p>

      <h2>Guides</h2>
      <p>
        The <Link href="/blog">guides section</Link> covers the game from the ground up: how to play, how every major
        format works, the classic deck archetypes, and strategy topics like mulligans and sideboarding. Each guide links
        into the builder so you can try the idea right away.
      </p>

      <h2>Fan content</h2>
      <p>
        MTG Deck Lab is unofficial Fan Content permitted under the Fan Content Policy. It is not approved or endorsed by
        Wizards of the Coast. Portions of the materials used are property of Wizards of the Coast. ©Wizards of the Coast
        LLC.
      </p>

      <h2>Get in touch</h2>
      <p>
        Found a bad pick, a bug or a card that should be in a deck? <Link href="/contact">Contact us</Link>.
      </p>
    </main>
  );
}
