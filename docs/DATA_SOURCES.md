# Data sources

Deck Lab does not scrape tournament websites at request time. Card data and
deck data are ingested offline, on the weekly refresh, into our own database.
This note is the allow-list. If a source is not listed as used, do not add a
scraper for it.

Checked October 2026.

## Used

### Scryfall bulk data

- Docs: https://scryfall.com/docs/api/bulk-data
- Terms: https://scryfall.com/docs/api (use of Scryfall data)
- What we do: download the bulk card file on the weekly refresh. That is the
  documented way to read the whole catalog. We do not walk the live API for
  every card. Prices in the bulk file are estimates and go stale after a day;
  we treat them as estimates.
- Conditions we follow: identify the app in `User-Agent`, don't paywall the
  card data, don't imply Scryfall endorses the site, and refresh gameplay data
  about weekly rather than in a tight loop.
- Profiles: `build_card_profiles` now profiles every card in that file. The
  old default (Modern-legal only) left coverage around 65% (22,718 of 35,134).

### MTGJSON official product decks

- License: https://www.mtgjson.com/license/ (MIT grant covering the site's
  content)
- Files: `DeckList.json` plus each deck at `https://mtgjson.com/api/v5/decks/{fileName}.json`
- What we keep:
  - `Commander Deck` (precons). These are complete 99-card lists, not
    skeletons padded with basics. They also power the precon upgrade catalog.
  - `Pioneer Challenger Deck`. Pioneer does not rotate, so these published
    lists are still meaningful evidence. They are products, not a current
    tournament metagame, and the archetype builder keeps a higher-weight
    recent template as the representative list when one exists.
- Attribution: each record keeps the Wizards (or other) `source` URL MTGJSON
  published, plus the MTGJSON license notice in `api/app/data/OFFICIAL_DECKS_NOTICE.txt`.
- What we download and then drop, and why:
  - Collector's editions of the same precon (duplicate lists).
  - Theme decks, intro packs, planeswalker decks, jumpstart, Secret Lair drops:
    real products, but they are not competitive shells and would crowd clusters.
  - Standard Challenger Decks: the feed's newest are from 2022, and that
    Standard has rotated.
  - World Championship Decks (1997–2004) and Pro Tour Decks (1996): official
    products, and real tournament lists, but they are not a current
    constructed metagame. Seeding archetypes with them would surface
    20-year-old decks.
  - The single 2014 Modern Event Deck, for the same reason.

The snapshot committed in `api/app/data/official_decks.json` is names and
quantities only. The weekly refresh (`bootstrap_data --refresh-cards`)
re-downloads it onto the data volume and re-ingests.

## Not used

### MTGGoldfish

- Robots: https://www.mtggoldfish.com/robots.txt disallows `/deck/download`.
- Terms (https://www.mtggoldfish.com/policies/terms-of-use, version 1.1): the
  site and its contents are for personal, non-commercial use. You may not
  reproduce, publish, distribute, or exploit the contents.
- Skipped. A deck builder with affiliate links and ads is not personal use,
  and the deck-download path is disallowed for robots.

### EDHREC

- Terms (https://edhrec.com/terms, effective 2024-08-06): access is a personal,
  noncommercial license. You may not copy the site, and you may not access it
  to build a similar or competitive website. Automated searches, requests, or
  queries are prohibited.
- Robots file only blocks a few preview paths, which is not permission to copy
  the statistics.
- Skipped, including the undocumented `json.edhrec.com` endpoints. Commander
  synergy in this app comes from the cards' own rules text, the official
  precons, and our templates.

### MTGTop8

- https://www.mtgtop8.com/robots.txt returns 404. The privacy policy does not
  grant a license to copy the deck database.
- Other people scrape it. That is not permission, and the compilation is their
  database even when an individual list is a reported fact.
- Skipped. We will not infer a license from the absence of a ban.

### Deck-hosting sites (Moxfield, Archidekt, and similar)

Not used. They don't publish a bulk license for other players' lists, and
copying those lists to seed a deck builder is the thing their terms exist to
prevent. A user can still paste their own list into the upgrade flow.

## What this does not fix

There is still no licensed feed of current Modern, Legacy, or Standard
tournament standings. Those formats keep the curated archetype templates
(`synthesized-from-builtin`), which the API labels as template evidence. The
official lists augment that corpus; they do not replace a metagame report.
A follow-up needs a source that actually grants redistribution of event
decklists.
