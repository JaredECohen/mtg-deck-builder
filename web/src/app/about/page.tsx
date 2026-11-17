import type { Metadata } from "next";
import Link from "next/link";

import { AUTHOR, SITE_NAME } from "@/lib/blog";
import { DEFAULT_SOCIAL_IMAGE, documentTitle, socialTitle } from "@/lib/seo";

const ABOUT_TITLE = "Who makes MTG Deck Lab and where card data comes from";
const ABOUT_DESCRIPTION =
  "MTG Deck Lab is a free Magic: The Gathering deck builder that explains every pick. Who makes it, how it works, and where its data comes from.";

export const metadata: Metadata = {
  title: documentTitle(ABOUT_TITLE),
  description: ABOUT_DESCRIPTION,
  alternates: { canonical: "/about" },
  openGraph: {
    type: "website",
    title: socialTitle(ABOUT_TITLE),
    description: ABOUT_DESCRIPTION,
    url: "/about",
    siteName: SITE_NAME,
    images: [DEFAULT_SOCIAL_IMAGE],
  },
  twitter: {
    card: "summary_large_image",
    title: socialTitle(ABOUT_TITLE),
    description: ABOUT_DESCRIPTION,
    images: [DEFAULT_SOCIAL_IMAGE.url],
  },
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
        The <Link href="/blog">guides section</Link> covers deck archetypes and the censuses counted from official
        product lists. Each reviewed guide links into the builder so you can open the list it measured.
      </p>

      <h2>Editorial method</h2>
      <p>
        A guide is signed Deck Lab Editorial, and offered to search engines, only after it is marked reviewed. The
        review is a checklist against files in this repository. It does not ask a language model to invent or grade
        the article.
      </p>
      <ul>
        <li>Every card name has to match the Scryfall oracle-cards bulk dated 2026-11-01.</li>
        <li>A sentence that calls a card legal, not legal, or banned has to match that same bulk.</li>
        <li>
          A Comprehensive Rules number has to appear in the rules file effective November 6, 2026.
        </li>
        <li>A price, a ban, or a &ldquo;best deck&rdquo; claim has to come from a checked-in data file.</li>
        <li>The guide needs at least 1,000 words and a table whose numbers are in that data file.</li>
        <li>Guides that share the same section outline are treated as one template, not as separate articles.</li>
      </ul>
      <p>
        The count and price definitions are on the <Link href="/method">method page</Link>. A guide that has not passed
        review can stay on the site for readers. It is left out of the sitemap and marked noindex.
      </p>

      <h2>Data sources</h2>
      <ul>
        <li>
          <a href="https://scryfall.com/docs/api" rel="noopener noreferrer" target="_blank">
            Scryfall
          </a>{" "}
          oracle-cards bulk, snapshot 2026-11-01, for card names, rules text, and format legality. Deck Lab refreshes
          the builder&apos;s card database from Scryfall every week. Guide numbers stay on the snapshot named on the
          method page.
        </li>
        <li>
          <a href="https://mtgjson.com" rel="noopener noreferrer" target="_blank">
            MTGJSON
          </a>{" "}
          official deck lists and AllPricesToday, for the product lists and the printing prices shown on a deck block.
        </li>
        <li>
          <a href="https://magic.wizards.com/en/rules" rel="noopener noreferrer" target="_blank">
            Magic Comprehensive Rules
          </a>
          , effective November 6, 2026, for any rule number a guide cites.
        </li>
        <li>
          The precon census and the Game Changer counts in the checked-in facts file, described on the{" "}
          <Link href="/method">method page</Link>.
        </li>
      </ul>

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
