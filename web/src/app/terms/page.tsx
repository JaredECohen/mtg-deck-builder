import type { Metadata } from "next";
import Link from "next/link";

import { SITE_NAME } from "@/lib/blog";
import { DEFAULT_SOCIAL_IMAGE, documentTitle, socialTitle } from "@/lib/seo";

const TERMS_TITLE = "Terms of use for MTG Deck Lab";
const TERMS_DESCRIPTION =
  "The terms for using MTG Deck Lab: fan content, decks you save, no warranty, and how ads and affiliate links work.";

export const metadata: Metadata = {
  title: documentTitle(TERMS_TITLE),
  description: TERMS_DESCRIPTION,
  alternates: { canonical: "/terms" },
  openGraph: {
    type: "website",
    title: socialTitle(TERMS_TITLE),
    description: TERMS_DESCRIPTION,
    url: "/terms",
    siteName: SITE_NAME,
    images: [DEFAULT_SOCIAL_IMAGE],
  },
  twitter: {
    card: "summary_large_image",
    title: socialTitle(TERMS_TITLE),
    description: TERMS_DESCRIPTION,
    images: [DEFAULT_SOCIAL_IMAGE.url],
  },
};

const UPDATED = "November 17, 2026";

export default function TermsPage() {
  return (
    <main className="shell legal-page">
      <h1>Terms of use</h1>
      <p className="legal-updated">Last updated {UPDATED}</p>

      <p>
        MTG Deck Lab is a free Magic: The Gathering deck builder and a set of guides. By using the site you agree to
        these terms. If you do not agree, don&apos;t use the site.
      </p>

      <h2>Fan content</h2>
      <p>
        MTG Deck Lab is unofficial Fan Content permitted under the Fan Content Policy. It is not approved or endorsed by
        Wizards of the Coast. Portions of the materials used are property of Wizards of the Coast. ©Wizards of the Coast
        LLC. Card names, rules text, and symbols remain the property of their owners. Magic: The Gathering and its
        logos are trademarks of Wizards of the Coast.
      </p>

      <h2>What the site provides</h2>
      <p>
        The builder returns deck lists, legality checks, prices, and notes from third-party data, including Scryfall and
        MTGJSON. Those sources can be wrong or out of date. A generated deck is a suggestion. You are responsible for
        checking it against the current format rules before you register it in a tournament or buy the cards.
      </p>
      <p>
        Guides marked reviewed cite the data files described on the <Link href="/method">method page</Link>. A guide
        that is not marked reviewed is not held to that checklist.
      </p>

      <h2>Decks you save</h2>
      <p>
        You can build a deck without an account. If you save or share a deck, you keep ownership of the list you
        entered. You give Deck Lab permission to store it and to show it to anyone with the link. A public deck may be
        indexed by search engines. You can hide a deck from search engines or delete it from your library. Don&apos;t
        save a list you don&apos;t have the right to share.
      </p>

      <h2>Acceptable use</h2>
      <p>Don&apos;t misuse the site. That includes:</p>
      <ul>
        <li>Trying to break, overload, or get around the service.</li>
        <li>Using the site to break the law or to violate someone else&apos;s rights.</li>
        <li>Scraping the site in a way that degrades it for other people.</li>
        <li>Submitting someone else&apos;s private information.</li>
      </ul>

      <h2>Advertising and affiliate links</h2>
      <p>
        Some pages may show ads. Some links to TCGplayer are affiliate links: if you buy through them, Deck Lab may earn
        a commission. That does not change the price you pay. The <Link href="/privacy">privacy page</Link> describes
        the cookies those services use.
      </p>

      <h2>No warranty</h2>
      <p>
        The site is provided as is. Deck Lab does not warrant that a deck is legal, that a price is what a store will
        charge, or that the service will be available without interruption. To the extent the law allows, Deck Lab is
        not liable for lost cards, lost matches, or other damages arising from use of the site.
      </p>

      <h2>Changes</h2>
      <p>
        These terms can change. The date at the top of this page is the latest revision. Continuing to use the site
        after a change means you accept the revised terms.
      </p>

      <h2>Contact</h2>
      <p>
        Questions about these terms: <Link href="/contact">contact us</Link>.
      </p>
    </main>
  );
}
