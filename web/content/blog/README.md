# Writing a Deck Lab guide

Each `.mdx` file in this folder is one article at `/blog/<file name>`. The
file name is the URL slug. Lowercase, hyphenated, and it carries the article's
primary keyword (`how-to-play-magic-the-gathering.mdx`). Files that aren't
`.mdx` (like this one) are ignored.

## Frontmatter

```yaml
---
title: "How to Play Magic: The Gathering: A Complete Beginner's Guide"
description: "One or two sentences, 140-160 characters. It is the Google snippet: say what the reader learns."
date: 2026-10-19          # publish day (YYYY-MM-DD), New York time; future dates are scheduled
updated: 2026-10-19       # optional, last meaningful revision
category: learn-to-play   # learn-to-play | formats | deck-archetypes | strategy | sets
keywords: ["how to play magic the gathering", "mtg rules for beginners"]
related: ["how-to-read-a-magic-card", "your-first-game-of-magic"]  # 2-4 slugs
draft: false              # true hides it everywhere (index, sitemap, RSS)
---
```

The title renders as the page's only `<h1>`. Don't repeat it in the body.

## Scheduling

Guides publish one per day. Set guides (`category: sets`) alternate with the
other guides while there are set guides left to publish. A guide with a future `date` is hidden everywhere
(index, hubs, related, sitemap, RSS, its own URL) until midnight New York
time on that day; listing pages re-render hourly, so it appears without a
deploy. `SCHEDULE.md` is the calendar: take the next open date, one guide
per day. Preview the site as of another day with `GUIDES_TODAY=2026-11-01`.

Links to a guide that hasn't published yet are fine: they render as plain
text until it goes live. Every guide still needs at least one link that
works on its own publish day.

Run `npm run check:guides` (CI does too) before committing.

## Body

- Markdown plus GitHub tables. `##` for sections (they become the table of
  contents, so make them scannable) and `###` for subsections. Never `#`.
- Open with 2-3 sentences that answer the search query directly. No
  throat-clearing ("Magic is a fun game enjoyed by millions...").
- Link to 2-4 other guides with root-relative links (`[mana curve](/blog/mana-curve-explained)`)
  and to the builder (`/`). Only link slugs that exist (see the launch list in
  the PR or `ls`).
- Components available without imports:
  - `<InArticleAd />`: put one after the intro section (~300 words in), and a
    second roughly midway through any article over 1,200 words. Always on its
    own line between paragraphs, never inside a list or table.
  - `<Callout title="Tip">…</Callout>`: short asides. Use sparingly.
  - `<DeckLabCTA format="commander" brief="Elf tribal that goes wide" />`: a
    button that opens the builder with the brief filled in. `format` is one of
    standard, modern, pioneer, legacy, commander. Every article ends with one,
    and the brief should match the article ("Mono-red burn under $50").

## Quality bar

- 1,000-2,500 words (flagship guides 2,000+). Original writing in your own
  words: no copying or close paraphrase of Wizards' rules text, articles,
  Reddit, EDHREC or any other site.
- Accurate. Use stable rules and facts. Avoid anything that goes stale quickly:
  no current ban lists, card prices, "best deck right now" claims, tournament
  results or set release dates beyond what is long-settled. When in doubt,
  describe the principle and cite the official source by name (the
  Comprehensive Rules, the official Commander brackets) instead of a number
  you are unsure of.
- Set guides are the exception to "nothing that goes stale": they cover a
  set's meta by design. Verify every card name and rarity on Scryfall, verify
  bans and deck names against a dated source, and anchor anything
  time-sensitive ("in its first months in Standard", "as of October 2026").
  Revisit the meta section (and set `updated`) when a set's Standard season
  changes, e.g. after a ban or rotation.
- Concrete. Use real, long-standing example cards (Lightning Bolt, Llanowar
  Elves, Counterspell, Sol Ring, Wrath of God) to illustrate, and name them
  exactly as printed.
- Written for the reader in the title. A beginner guide defines every term
  the first time it appears. A strategy guide can assume the basics.
- No filler, no keyword stuffing, no "In conclusion". End with a short,
  practical takeaway and the `<DeckLabCTA />`.
- Spell out "Magic: The Gathering" at the first mention in the body, e.g.
  "Magic: The Gathering (MTG)". After that, "Magic" or "MTG" is fine. Titles
  and slugs can keep "MTG", since that's what people search for. The checker
  enforces the first mention.
- Card names and game terms follow Wizards' capitalization (the battlefield,
  the stack, mana value, Commander, Limited).
