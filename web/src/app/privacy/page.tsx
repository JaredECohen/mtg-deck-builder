import type { Metadata } from "next";
import Link from "next/link";

import { ADSENSE_CLIENT } from "@/lib/ads";

export const metadata: Metadata = {
  title: "Privacy | MTG Deck Lab",
  description: "What MTG Deck Lab stores, what it shares, how anonymous usage is counted, and the cookies used by advertising.",
  alternates: { canonical: "/privacy" },
};

const CONTACT_EMAIL = process.env.NEXT_PUBLIC_CONTACT_EMAIL ?? "";
const UPDATED = "October 27, 2026";

export default function PrivacyPage() {
  return (
    <main className="shell legal-page">
      <h1>Privacy</h1>
      <p className="legal-updated">Last updated {UPDATED}</p>

      <h2>No accounts</h2>
      <p>
        MTG Deck Lab has no sign-up and asks for no personal information. You can build, analyze and share decks
        without telling us who you are.
      </p>

      <h2>What we store</h2>
      <ul>
        <li>
          <strong>Decks you save or share.</strong> The deck list, its name, notes and evaluation are stored on our
          server so the share link works. Anyone with a share link can view that deck.
        </li>
        <li>
          <strong>Preferences and drafts in your browser.</strong> Your beginner or expert mode setting and unsaved
          deck drafts are kept in your browser&apos;s local storage. They never leave your device, and clearing site
          data removes them.
        </li>
        <li>
          <strong>Request handling.</strong> To limit abuse, the server tracks how many requests come from each IP
          address over the last few minutes. This is held in memory only. Our request logs record the page or
          endpoint, the response status and timing, not your IP address.
        </li>
      </ul>

      <h2>Analytics</h2>
      <p>
        We use Vercel Web Analytics to understand which pages are visited and which deck-building steps people
        complete, such as generating, refining, exporting, or sharing a deck, opening a guide, or opening a TCGplayer
        cart. It does not use cookies and it does not identify you.
      </p>
      <p>
        Those events include only a format, an export target, or a guide&apos;s public address and category. They do
        not include the text you type, deck names, card lists, email addresses, or share links. The page address
        stored with a visit has the brief and share-token parameters removed.
      </p>

      <h2>What we share</h2>
      <ul>
        <li>
          <strong>AI providers.</strong> When you describe a deck in words or ask for coaching, that text and the deck
          list are sent to Anthropic or OpenAI to generate the response.
        </li>
        <li>
          <strong>Hosting.</strong> The site runs on Vercel and Fly.io, which process requests to deliver the pages
          and the API.
        </li>
        <li>
          <strong>Card shopping links.</strong> Links to TCGplayer may be affiliate links. If you buy through them we
          may earn a commission, and TCGplayer and its affiliate network may set their own cookies once you are on
          their site.
        </li>
      </ul>

      {ADSENSE_CLIENT ? (
        <>
          <h2>Advertising and cookies</h2>
          <p>
            We show ads served by Google. Google and its partners use cookies to serve ads based on your visits to
            this and other websites. Google&apos;s use of advertising cookies lets it and its partners serve ads
            based on those visits.
          </p>
          <p>
            You can opt out of personalized advertising in{" "}
            <a href="https://adssettings.google.com" rel="noopener noreferrer" target="_blank">
              Google&apos;s Ad Settings
            </a>
            , and learn more in{" "}
            <a href="https://policies.google.com/technologies/partner-sites" rel="noopener noreferrer" target="_blank">
              how Google uses information from sites that use its services
            </a>
            . Visitors in the EEA, the UK and Switzerland are asked for consent before personalized ads are shown.
          </p>
        </>
      ) : null}

      <h2>Contact</h2>
      <p>
        {CONTACT_EMAIL ? (
          <>
            Questions or deletion requests for a saved deck: <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
          </>
        ) : (
          <>Questions or deletion requests for a saved deck can be sent through the contact details on this site.</>
        )}
      </p>

      <p>
        <Link href="/">Back to the Deck Lab</Link>
      </p>
    </main>
  );
}
