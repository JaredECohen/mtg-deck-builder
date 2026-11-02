import type { Metadata } from "next";
import Link from "next/link";

import { EnableAds } from "@/components/enable-ads";
import { SITE_NAME } from "@/lib/blog";

export const metadata: Metadata = {
  title: `Method | ${SITE_NAME}`,
  description:
    "Where MTG Deck Lab's guide numbers come from: MTGJSON deck lists, Scryfall bulk prices, Commander bracket inputs, and the goldfish simulator.",
  alternates: { canonical: "/method" },
};

export default function MethodPage() {
  return (
    <main className="shell legal-page">
      <EnableAds />
      <h1>How the guide numbers are counted</h1>
      <p>
        Guides signed Deck Lab Editorial cite a checked-in facts file. A price, a count, or a percentage in those
        guides has to match that file. This page is the definition of the count. It is not a promise that a store will
        sell you a card at the printed number.
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
        . The snapshot this site commits keeps Commander Deck products and Pioneer Challenger Deck products. Collector
        editions of the same precon are dropped as duplicate lists. The census is 182 Commander precons and 8 Pioneer
        Challenger decks. World Championship decks from the same DeckList index are loaded into the builder as example
        lists. They are not part of the precon census.
      </p>
      <p>
        A token that a product file places in the main list is not a sleeveable card. It is left out of land counts,
        role counts, and prices. The commander name is not also counted inside the main list.
      </p>

      <h2>Cards and prices</h2>
      <p>
        Rules text, types, mana value, color, and legality come from the Scryfall oracle-cards bulk file. Prices come
        from the Scryfall default-cards bulk file. For each card the total uses the lowest nonfoil <code>prices.usd</code>{" "}
        among English printings. That is not the printing inside the sealed product. A card with no nonfoil USD is
        unpriced: it is named and left out of the sum. The fetch date is stored on the facts file and repeated in the
        guide that cites it.
      </p>
      <p>
        Deck blocks on a guide are a second price. They use MTGJSON AllPricesToday for the printing in that product
        file (TCGplayer nonfoil retail, or ManaPool nonfoil retail when TCGplayer has none). Do not add the two totals
        together. They answer different questions.
      </p>
      <p>
        The Scryfall terms are at{" "}
        <a href="https://scryfall.com/docs/api" rel="noopener noreferrer" target="_blank">
          scryfall.com/docs/api
        </a>
        . Card data is not paywalled here, and the site does not speak for Scryfall.
      </p>

      <h2>Lands, ramp, draw, and removal</h2>
      <p>Counts are copies in the main list. A card can match more than one of ramp, draw, and removal. Lands do not.</p>
      <ul>
        <li>
          <strong>Land.</strong> The front face types include Land. A land that draws or adds mana stays in the land
          count only.
        </li>
        <li>
          <strong>Ramp.</strong> A nonland that adds mana, searches your library for a land and puts it onto the
          battlefield, lets you play an additional land, puts a land from your hand onto the battlefield, or creates a
          Treasure you get. A search that replaces a permanent for its controller is not ramp.
        </li>
        <li>
          <strong>Draw.</strong> A nonland that draws you cards, or exiles the top of your library and lets you play or
          cast those cards. A sentence that only draws for an opponent is not draw. Target player and each player count,
          because you can be that player.
        </li>
        <li>
          <strong>Removal.</strong> A nonland that destroys or exiles a permanent, deals damage to a creature or any
          target, forces a sacrifice, fights, or gives creatures a toughness penalty. A counterspell is not removal.
          Damage to any target counts even when the deck points it at a player.
        </li>
      </ul>
      <p>
        The mana curve is nonland cards, with mana value 7 and above in one bucket. Color identity on a Commander
        product is the commander colors stored by MTGJSON.
      </p>

      <h2>Game Changers and bracket floors</h2>
      <p>
        Game Changer names are the list in this repo, dated 2025-04-22. A precon includes one when that card name is
        in the commander or the main list. The bracket floor is the same module the deck builder uses. It can read a
        floor of 2, 3, or 4 from a list. Exhibition and competitive tables are about intent, so the list cannot show
        those. One Game Changer moves the floor out of the core band. More than three, a mass-land-denial match, two
        extra-turn cards, or a listed two-card combo can move it further. The floor is a description of the list, not a
        ban and not Wizards assigning your table a number.
      </p>

      <h2>The simulator</h2>
      <p>
        Clocks inside a deck block come from the Deck Lab goldfish (<code>app.sim.goldfish</code>): 120 games, seed 1729,
        no opponent. A Commander list starts the opponent at 40 life and stops after 16 turns. Any other list starts
        the opponent at 20 life and stops after 12 turns. Basic lands add the mana of their land type. The commander
        stays in the command zone and is not in the library. Wins are combat damage or direct damage the policy
        actually casts. A combo that does not attack can record zero wins, and that zero means the simulator did not
        play the combo. It is not a match win rate.
      </p>

      <h2>Affiliate links</h2>
      <p>
        A deck block can include a TCGplayer link. Buy links are TCGplayer affiliate links. This site may earn a
        commission on purchases at no extra cost to you. The commission does not change the Scryfall or MTGJSON number
        next to a card.
      </p>

      <h2>Fan Content</h2>
      <p>
        MTG Deck Lab is unofficial Fan Content permitted under the{" "}
        <a href="https://company.wizards.com/en/legal/fancontentpolicy" rel="noopener noreferrer" target="_blank">
          Fan Content Policy
        </a>
        . Not approved or endorsed by Wizards of the Coast. Portions of the materials used are property of Wizards of
        the Coast. ©Wizards of the Coast LLC. Card data and images are used courtesy of Scryfall.
      </p>
      <p>
        The <Link href="/blog">guides</Link> that cite these files link back here. Regenerating the facts file is{" "}
        <code>python -m app.scripts.build_precon_facts</code> from the API directory, then{" "}
        <code>python -m app.scripts.build_study_guides</code>.
      </p>
    </main>
  );
}
