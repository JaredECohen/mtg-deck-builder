import type { Metadata } from "next";
import Link from "next/link";

import { PreconStatsTable } from "@/components/precon-stats-table";
import { GUIDE_AUTHOR, SITE_NAME, formatDate } from "@/lib/blog";
import { loadPreconStats } from "@/lib/precon-stats";
import { PRECON_STATS_PATH, PRECON_STATS_PUBLISHED, PRECON_STATS_UPDATED } from "@/lib/precon-stats-path";
import { formatCountMedian, formatMoney } from "@/lib/precon-stats-shared";
import { DEFAULT_SOCIAL_IMAGE, documentTitle, metaDescription, socialTitle } from "@/lib/seo";

const stats = loadPreconStats();

const PAGE_TITLE = "Commander precon stats";
const PAGE_DESCRIPTION = metaDescription(
  `Land count, mana curve, ramp, draw, removal, Game Changers, and Scryfall prices for ${stats.productCount} official Commander precons. Price snapshot ${stats.sources.priceDate}.`,
);

export const dynamic = "force-static";

export const metadata: Metadata = {
  title: documentTitle(PAGE_TITLE),
  description: PAGE_DESCRIPTION,
  alternates: { canonical: PRECON_STATS_PATH },
  robots: { index: true, follow: true },
  openGraph: {
    type: "website",
    title: socialTitle(PAGE_TITLE),
    description: PAGE_DESCRIPTION,
    url: PRECON_STATS_PATH,
    siteName: SITE_NAME,
    images: [DEFAULT_SOCIAL_IMAGE],
  },
  twitter: {
    card: "summary_large_image",
    title: socialTitle(PAGE_TITLE),
    description: PAGE_DESCRIPTION,
    images: [DEFAULT_SOCIAL_IMAGE.url],
  },
};

function PriceCell({ price, pricedDecks, decks }: { price: number | null; pricedDecks: number; decks: number }) {
  if (price == null) return <>No complete price ({pricedDecks} of {decks})</>;
  return (
    <>
      {formatMoney(price)} <span className="muted">({pricedDecks} of {decks})</span>
    </>
  );
}

export default function CommanderPreconStatsPage() {
  const { sources } = stats;
  return (
    <main className="shell precon-stats">
      <header className="precon-stats-prose">
        <div className="eyebrow">Counts from the deck files</div>
        <h1 className="headline">Commander precon stats</h1>
        <p className="subhead">
          One row for each of the {stats.productCount} Commander Deck products in the MTGJSON snapshot.{" "}
          {stats.reprintCount} of those products repeat an earlier list. {stats.pioneerExcluded} Pioneer Challenger
          Decks are in the same snapshot and are not in this table.
        </p>
        <p className="blog-byline muted">
          By {GUIDE_AUTHOR} · {SITE_NAME} · Published{" "}
          <time dateTime={PRECON_STATS_PUBLISHED}>{formatDate(PRECON_STATS_PUBLISHED)}</time>
          {PRECON_STATS_UPDATED !== PRECON_STATS_PUBLISHED ? (
            <>
              {" "}
              · Updated <time dateTime={PRECON_STATS_UPDATED}>{formatDate(PRECON_STATS_UPDATED)}</time>
            </>
          ) : null}{" "}
          · <Link href="/method">How we count</Link>
        </p>
        <p className="muted">
          Facts file fetched {sources.fetchedAt}. Oracle bulk {sources.oracleUpdatedAt}. Prices use {sources.priceField}{" "}
          from the bulk dated {sources.priceUpdatedAt}. Game Changers as of {sources.gameChangersAsOf} (
          {sources.gameChangerListSize} names).
        </p>
      </header>

      <section className="precon-stats-prose" aria-labelledby="medians-heading">
        <h2 id="medians-heading">Medians</h2>
        <p>
          The first row is every product in the table. The second drops the {stats.reprintCount} reprints, so a repeated
          list is counted once. A price median uses only products with a price for every counted card. Mana value is
          the nonland average, with the stored 7+ bucket counted as 7.
        </p>
        <div className="table-scroll">
          <table className="data-table">
            <caption className="sr-only">Median land count, mana value, ramp, draw, removal, Game Changers, and price</caption>
            <thead>
              <tr>
                <th scope="col">Sample</th>
                <th scope="col" className="num">Decks</th>
                <th scope="col" className="num">Lands</th>
                <th scope="col" className="num">Avg MV</th>
                <th scope="col" className="num">Ramp</th>
                <th scope="col" className="num">Draw</th>
                <th scope="col" className="num">Removal</th>
                <th scope="col" className="num">Game Changers</th>
                <th scope="col" className="num">Price</th>
              </tr>
            </thead>
            <tbody>
              {[
                { label: "All products", group: stats.all },
                { label: "Unique lists", group: stats.unique },
              ].map((row) => (
                <tr key={row.label}>
                  <th scope="row">{row.label}</th>
                  <td className="num">{row.group.decks}</td>
                  <td className="num">{formatCountMedian(row.group.land)}</td>
                  <td className="num">{row.group.averageManaValue.toFixed(2)}</td>
                  <td className="num">{formatCountMedian(row.group.ramp)}</td>
                  <td className="num">{formatCountMedian(row.group.draw)}</td>
                  <td className="num">{formatCountMedian(row.group.removal)}</td>
                  <td className="num">{formatCountMedian(row.group.gameChangers)}</td>
                  <td className="num">
                    <PriceCell price={row.group.price} pricedDecks={row.group.pricedDecks} decks={row.group.decks} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="precon-stats-prose" aria-labelledby="year-heading">
        <h2 id="year-heading">By release year</h2>
        <p>
          Each product is grouped by the year of its release date, including a reprint in the year that printing was
          released. Years with no product in the snapshot are not rows.
        </p>
        <div className="table-scroll">
          <table className="data-table">
            <caption className="sr-only">Medians by release year</caption>
            <thead>
              <tr>
                <th scope="col">Year</th>
                <th scope="col" className="num">Decks</th>
                <th scope="col" className="num">Lands</th>
                <th scope="col" className="num">Avg MV</th>
                <th scope="col" className="num">Ramp</th>
                <th scope="col" className="num">Draw</th>
                <th scope="col" className="num">Removal</th>
                <th scope="col" className="num">Game Changers</th>
                <th scope="col" className="num">Price</th>
              </tr>
            </thead>
            <tbody>
              {stats.byYear.map((row) => (
                <tr key={row.year}>
                  <th scope="row">{row.year}</th>
                  <td className="num">{row.decks}</td>
                  <td className="num">{formatCountMedian(row.land)}</td>
                  <td className="num">{row.averageManaValue.toFixed(2)}</td>
                  <td className="num">{formatCountMedian(row.ramp)}</td>
                  <td className="num">{formatCountMedian(row.draw)}</td>
                  <td className="num">{formatCountMedian(row.removal)}</td>
                  <td className="num">{formatCountMedian(row.gameChangers)}</td>
                  <td className="num">
                    <PriceCell price={row.price} pricedDecks={row.pricedDecks} decks={row.decks} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <h3>By year range</h3>
        <div className="table-scroll">
          <table className="data-table">
            <caption className="sr-only">Medians by release-year range</caption>
            <thead>
              <tr>
                <th scope="col">Years</th>
                <th scope="col" className="num">Decks</th>
                <th scope="col" className="num">Lands</th>
                <th scope="col" className="num">Avg MV</th>
                <th scope="col" className="num">Ramp</th>
                <th scope="col" className="num">Draw</th>
                <th scope="col" className="num">Removal</th>
                <th scope="col" className="num">Game Changers</th>
                <th scope="col" className="num">Price</th>
              </tr>
            </thead>
            <tbody>
              {stats.byRange.map((row) => (
                <tr key={row.label}>
                  <th scope="row">{row.label}</th>
                  <td className="num">{row.decks}</td>
                  <td className="num">{formatCountMedian(row.land)}</td>
                  <td className="num">{row.averageManaValue.toFixed(2)}</td>
                  <td className="num">{formatCountMedian(row.ramp)}</td>
                  <td className="num">{formatCountMedian(row.draw)}</td>
                  <td className="num">{formatCountMedian(row.removal)}</td>
                  <td className="num">{formatCountMedian(row.gameChangers)}</td>
                  <td className="num">
                    <PriceCell price={row.price} pricedDecks={row.pricedDecks} decks={row.decks} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section aria-labelledby="table-heading">
        <div className="precon-stats-prose">
          <h2 id="table-heading">Every Commander precon</h2>
          <p>
            Default order is release date, newest first, then name. The curve column is eight counts, mana value 0
            through 7 or more.{" "}
            {stats.rows.every((row) => row.href == null)
              ? "No product in this table has a page on this site, so the deck name is text."
              : "A deck name links to its page when this site has one."}
          </p>
        </div>
        <PreconStatsTable rows={stats.rows} sets={stats.sets} priceDate={sources.priceDate} />
      </section>

      <section className="precon-stats-prose" aria-labelledby="method-heading">
        <h2 id="method-heading">How this was made</h2>
        <p>
          No model wrote a figure on this page. The numbers are counted from two checked-in files. Regenerating{" "}
          <code>precon_facts.json</code> changes them. The <Link href="/method">method page</Link> is the same
          definition the reviewed guides use. The census guides are{" "}
          <Link href="/blog/precon-lands-ramp-draw">lands, ramp, and draw</Link> and{" "}
          <Link href="/blog/commander-precon-game-changers">Game Changers in precons</Link>.
        </p>
        <h3>Sources</h3>
        <ul>
          <li>
            {sources.decksName}. Snapshot <code>{sources.decksSnapshot}</code>. License{" "}
            <a href={sources.decksLicense} rel="noopener noreferrer">
              {sources.decksLicense}
            </a>
            . The set column is that file&apos;s <code>set_code</code>. Collector editions are already excluded there.
          </li>
          <li>
            {sources.oracleName}.{" "}
            <a href={sources.oracleUrl} rel="noopener noreferrer">
              {sources.oracleUpdatedAt}
            </a>
            . Types, rules text, and mana value come from this bulk.
          </li>
          <li>
            {sources.priceName}, field <code>{sources.priceField}</code>, updated {sources.priceUpdatedAt}.{" "}
            <a href={sources.priceUrl} rel="noopener noreferrer">
              Bulk file
            </a>
            . {sources.priceNote}
          </li>
          <li>
            Game Changer names are the committed list dated {sources.gameChangersAsOf}, {sources.gameChangerListSize}{" "}
            names, copied from the Scryfall <code>game_changer</code> field. The bracket check uses the same list.
          </li>
        </ul>
        <h3>What a row counts</h3>
        <p>
          A row is one Commander Deck product. {stats.decksWithSideboard === 0
            ? "None of these products has a sideboard, so every count is the main list plus the rule below for Game Changers and price."
            : `${stats.decksWithSideboard} products have a sideboard. Ramp, draw, removal, lands, and the curve stay on the main list.`}
        </p>
        <ul>
          <li>
            <strong>Lands.</strong> Mainboard copies whose front-face types include Land.
          </li>
          <li>
            <strong>Curve and average mana value.</strong> Mainboard cards that are not lands. The facts file stores
            mana value as eight buckets, 0 through 7, and stores 7 or greater as 7. The average is the quantity-weighted
            mean of those buckets, so a card stored in the last bucket counts as 7. Tokens and cards missing from the
            oracle file are left out. This snapshot has none of those in a Commander product, and lands plus the curve
            equal the mainboard count on every row.
          </li>
          <li>
            <strong>Ramp.</strong> A nonland mainboard copy that adds mana, searches your library for a land and puts
            it onto the battlefield, lets you play an additional land, or creates a Treasure you get. A search that
            replaces a permanent for its controller is not ramp. The same rule is in <code>precon_stats.py</code>.
          </li>
          <li>
            <strong>Draw.</strong> A nonland mainboard copy that draws you cards, or exiles the top of your library and
            lets you play those cards. Parenthetical reminder text is ignored, so cycling does not count. A sentence
            that only draws for an opponent does not count. A sentence that only triggers when someone draws is not a
            draw spell.
          </li>
          <li>
            <strong>Removal.</strong> A nonland mainboard copy that destroys or exiles a permanent, deals damage to a
            creature or any target, gives a creature -N/-N, gives creatures -N/-N, fights, forces a sacrifice, or
            shuffles a permanent into a library. A counterspell is not removal. Exiling your own permanents and
            returning them is not removal.
          </li>
          <li>
            A card can match more than one of ramp, draw, and removal. Lands match none of them. The commander is not
            added into those three columns. That matches the guide census, which counts the main list.
          </li>
          <li>
            <strong>Game Changers.</strong> Distinct names on the mainboard or in the command zone that are on the Game
            Changer list.{" "}
            {stats.gameChangerCopiesMatch
              ? "On every product in this snapshot, that name count equals the copy count."
              : "The column is the name count. The copy count differs on at least one product."}
          </li>
          <li>
            <strong>Price.</strong> The sum in the facts file for the {sources.priceDate} snapshot. A cell marked
            partial leaves out each named card that had no usable price, and that product is left out of the price
            median. A cell marked foil commander used a foil price for that commander only. This is not the sealed
            product&apos;s price.
          </li>
        </ul>
        <p>
          An even count of decks takes the mean of the two middle values. Count medians are then rounded to one
          decimal. The mana-value median is rounded to two decimals, half away from zero. The price median is the mean
          of the two middle cent values, rounded to a cent.
        </p>
      </section>
    </main>
  );
}
