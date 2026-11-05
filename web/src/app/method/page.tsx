import type { Metadata } from "next";
import Link from "next/link";

import { SITE_NAME } from "@/lib/blog";

export const metadata: Metadata = {
  title: `Method | ${SITE_NAME}`,
  description:
    "Where MTG Deck Lab guide numbers come from: MTGJSON lists, the Scryfall bulk, Game Changers, and the goldfish.",
  alternates: { canonical: "/method" },
};

export default function MethodPage() {
  return (
    <main className="shell legal-page">
      <h1>How the guide numbers are counted</h1>
      <p>
        Reviewed guides signed Deck Lab Editorial cite a checked-in facts file. A price, a count, or a percentage
        in a reviewed guide has to match that file. A guide that has not passed the rubric is not signed that way,
        and nothing on this page says its numbers were checked. This page is the definition for the reviewed guides.
        It is not a promise that a store will sell a card at the printed number. This page does not carry ads.
      </p>

      <h2>Deck lists</h2>
      <p>
        Official product lists come from{" "}
        <a href="https://mtgjson.com" rel="noopener noreferrer" target="_blank">
          MTGJSON
        </a>
        , which republishes Wizards of the Coast product decks under the{" "}
        <a href="https://www.mtgjson.com/license/" rel="noopener noreferrer" target="_blank">
          MIT grant on mtgjson.com
        </a>
        . The committed snapshot keeps Commander Deck products and Pioneer Challenger Deck products. Collector editions
        of the same precon are dropped as duplicate products. That leaves 182 Commander products and 8 Pioneer
        Challenger decks.
      </p>
      <p>
        Eight of those Commander products are Commander Anthology reprints of an earlier precon, with the same cards
        and the same counts. The medians and the Game Changer census use the earlier list once, so the sample is 174
        unique lists. The reprint is still a real product. It is not a second data point. Every Commander product in
        the snapshot is 100 cards once the commander or commanders are counted with the main list. A partner deck has
        98 cards in the main list and 2 commanders.
      </p>
      <p>
        World Championship decks from the same DeckList index can be opened with <code>?example=</code>. The builder
        loads them as Legacy so the editor has a format it understands. The note on the list says they are a
        Vintage/Old School example, and it names cards that are not legal in Legacy. They are not part of the precon
        census.
      </p>

      <h2>Cards and prices</h2>
      <p>
        Rules text, types, mana value, and legality come from the Scryfall oracle-cards bulk. A token, emblem, or
        art card that shares a name with a real card is skipped, so the lookup keeps the card. Prices come from the
        Scryfall default-cards bulk dated 2026-11-01. For each card the total uses the lowest nonfoil USD among
        English paper printings. Tokens, memorabilia, gold-bordered cards, and oversized cards are excluded. That
        price is not the printing inside the sealed product.
      </p>
      <p>
        A commander with no nonfoil price uses the lowest foil USD instead, and the facts file labels that commander
        as foil-priced. Any other card with no usable price is named and left out of the sum. Deck blocks on a guide
        are a second price: MTGJSON AllPricesToday for the printing in that product. The two totals answer different
        questions, and each guide says so once.
      </p>

      <h2>Lands, ramp, draw, and removal</h2>
      <p>Counts are copies in the main list. A card can match more than one of ramp, draw, and removal. Lands do not.</p>
      <ul>
        <li>
          <strong>Land.</strong> The front face types include Land.
        </li>
        <li>
          <strong>Ramp.</strong> A nonland that adds mana, searches your library for a land and puts it onto the
          battlefield, lets you play an additional land, or creates a Treasure you get. A search that replaces a
          permanent for its controller is not ramp.
        </li>
        <li>
          <strong>Draw.</strong> A nonland that draws you cards, or exiles the top of your library and lets you play
          those cards. Parenthetical reminder text is ignored, so cycling does not count. A sentence that only draws
          for an opponent does not count. A sentence that begins with whenever someone draws is a trigger, not a draw
          spell, so Psychosis Crawler, Smothering Tithe, and Ominous Seas do not count.
        </li>
        <li>
          <strong>Removal.</strong> A nonland that destroys or exiles a permanent, deals damage to a creature or any
          target, gives a target creature -N/-N, gives all creatures or each creature -N/-N, fights, forces a
          sacrifice, or shuffles a permanent into a library.
          A counterspell is not removal. Exiling your own creatures and returning them, including blink and a spell
          that exiles the creatures you control, is not removal. Damage to any target still counts when the deck
          points it at a player.
        </li>
      </ul>

      <h2>Game Changers and bracket floors</h2>
      <p>
        Game Changer names are the cards Scryfall marks with <code>game_changer</code> on the oracle-cards bulk dated
        2026-11-01. The committed file <code>game_changers.json</code> is copied from that field. The facts build
        fails if the file and the bulk disagree. The same file feeds the deck builder bracket check. The list-only
        floor can read 2, 3, or 4. Exhibition and competitive tables are about intent, so a list cannot show them.
      </p>

      <h2>The simulator</h2>
      <p>
        Clocks inside a deck block come from the Deck Lab goldfish (<code>app.sim.goldfish</code>): 120 games, seed
        1729, no opponent. A Commander list starts the opponent at 40 life and stops after 16 turns. Any other list
        starts the opponent at 20 life and stops after 12 turns. The commander stays in the command zone. Wins are
        combat or direct damage the policy casts. A combo that does not attack can record zero wins. That zero means
        the simulator did not play the combo.
      </p>

      <h2>Affiliate links</h2>
      <p>
        A deck block can include a TCGplayer link. Buy links are TCGplayer affiliate links. This site may earn a
        commission on purchases at no extra cost to you. The commission does not change a Scryfall or MTGJSON number.
      </p>

      <h2>Fan Content</h2>
      <p>
        MTG Deck Lab is unofficial Fan Content permitted under the{" "}
        <a href="https://company.wizards.com/en/legal/fancontentpolicy" rel="noopener noreferrer" target="_blank">
          Fan Content Policy
        </a>
        . Not approved or endorsed by Wizards of the Coast. Portions of the materials used are property of Wizards of
        the Coast. ©Wizards of the Coast LLC.
      </p>
      <p>
        Data terms for MTGJSON and Scryfall are in{" "}
        <Link href="/THIRD_PARTY_NOTICES.txt">THIRD_PARTY_NOTICES</Link>. The <Link href="/blog">guides</Link>{" "}
        link back here. From the API directory, regenerate with{" "}
        <code>python -m app.scripts.build_precon_facts</code> and{" "}
        <code>python -m app.scripts.build_study_guides</code>. A regenerated facts file changes the numbers in the
        guides, so the diff needs a review before it is treated as reviewed copy.
      </p>
    </main>
  );
}
