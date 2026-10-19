# Deploying: Vercel (web) + Fly.io (API)

The Next.js app runs on Vercel. The FastAPI server runs on one Fly.io machine,
and its SQLite database lives on a Fly volume. The browser only talks to
Vercel. The proxy route `web/src/app/api/backend/[...path]/route.ts` forwards
each request to Fly and adds the `X-API-Key` header, so the key never reaches
the client.

```
browser ──► Vercel (Next.js, /api/backend proxy) ──X-API-Key──► Fly (uvicorn, 1 worker)
                                                                   └─ /data volume: SQLite
```

Expected cost is about $6–7/month: Fly shared-cpu-1x with 1 GB is about
$5.70, and the 1 GB volume is $0.15. Vercel Hobby is free. LLM spend is
separate (see "Spend caps").

## What's in the repo

| File | Purpose |
| --- | --- |
| `fly.toml` | Fly app config: 1 GB VM, `/data` volume, health check, no auto-stop |
| `api/Dockerfile` | API image (Python 3.13, `DATABASE_URL=sqlite:////data/...`) |
| `api/deploy/start.sh` | Entrypoint: `bootstrap_data`, then uvicorn |
| `api/app/scripts/bootstrap_data.py` | Builds the DB on an empty volume and skips work that is already done |
| `.github/workflows/refresh-cards.yml` | Weekly Scryfall re-ingest (manual runs work too) |
| `.dockerignore` | Keeps `web/`, `node_modules`, local DBs and `.env` out of the image |

**First boot.** On an empty volume the server needs time before it starts
listening: about 1–2 minutes on a laptop, but 10–15 minutes on Fly. Fly's
shared CPU is throttled under sustained load, and card profiling is the slow
step. `fly deploy` may report failed health checks in the meantime; watch
`fly logs` for "caches warmed". During that time it:

1. downloads Scryfall (about 35k cards);
2. ingests the tournament decks;
3. builds archetypes and card profiles.

Ordinary restarts skip all of this and take about 10 seconds, most of it
cache warm-up.

## 1. Fly.io (API)

Install flyctl (`brew install flyctl`) and run `fly auth login`. Add a credit
card first (https://fly.io/trial). Trial machines are stopped after 5 minutes,
which kills the first-boot bootstrap partway through.

```bash
# From the repo root. Pick a globally unique app name and put it in fly.toml.
fly apps create mtg-deck-lab-api
fly volumes create mtg_data --app mtg-deck-lab-api --region iad --size 1

# Secrets (never in fly.toml). Generate the shared key once:
openssl rand -hex 32
fly secrets set --app mtg-deck-lab-api \
  MTG_API_KEY=<that key> \
  ANTHROPIC_API_KEY=<key> \
  OPENAI_API_KEY=<key> \
  TCGPLAYER_AFFILIATE_URL=<impact deep-link prefix>

fly deploy
fly logs --app mtg-deck-lab-api   # watch the bootstrap JSON, then "caches warmed"
```

`ANTHROPIC_API_KEY`, `OPENAI_API_KEY` and `TCGPLAYER_AFFILIATE_URL` are
optional. Without the LLM keys, the deterministic fallbacks run.

Check it:

```bash
curl https://mtg-deck-lab-api.fly.dev/api/health
curl https://mtg-deck-lab-api.fly.dev/api/data-status
```

`/v1/decks/generate` and the other write endpoints should return 401 without
the key.

**Rate limiting.** Leave `MTG_TRUST_FORWARDED=0`. The API trusts
`X-Forwarded-For` only on requests that carry a valid `MTG_API_KEY`, and only
the Vercel proxy has that key. Everything else is limited by `Fly-Client-IP`.
Because of this, someone calling the Fly URL directly can't spoof their
address to escape the limit.

## 2. Vercel (web)

1. Import the GitHub repo in Vercel and set **Root Directory** to `web`.
   Next.js is detected automatically.
2. Under **Settings → Environment Variables** (Production and Preview), set:

   | Name | Value |
   | --- | --- |
   | `API_BASE` | `https://mtg-deck-lab-api.fly.dev` |
   | `MTG_API_KEY` | the same key as the Fly secret. Do **not** prefix it with `NEXT_PUBLIC_` |
   | `NEXT_PUBLIC_TCGPLAYER_AFFILIATE_URL` | same as `TCGPLAYER_AFFILIATE_URL` (optional) |

3. Deploy. Pushes to `main` deploy to production, and PRs get preview URLs.
   Previews use the same API. Set Preview-scoped variables if you want them
   kept apart.

**Request timeout.** The proxy declares `maxDuration = 60`, which is the
Vercel Hobby limit, and gives up on the upstream call at 58 s. Generation
finishes well inside that. Long work such as the critic loop and the
optimizer runs as background jobs that the client polls.

You don't need to set CORS: the browser never calls Fly directly.

## 3. Weekly card refresh

`.github/workflows/refresh-cards.yml` runs on Mondays and can also be started
by hand from the Actions tab. To enable it:

```bash
fly tokens create deploy --app mtg-deck-lab-api   # copy the token
gh secret set FLY_API_TOKEN                       # paste it
gh variable set FLY_APP --body mtg-deck-lab-api   # only if the name differs
```

The workflow:

1. touches `/data/.refresh-cards` over `fly ssh`;
2. restarts the app;
3. waits until `/api/data-status` answers again.

When `start.sh` sees the flag, it runs
`bootstrap_data --refresh-cards` before uvicorn starts. This is deliberate.
A re-ingest running next to a live server (about 600 MB of caches) would go
over the 1 GB machine. The cost is about a minute of downtime each week.

Until `FLY_API_TOKEN` is set, the workflow does nothing.

## Spend caps

The API calls Anthropic and OpenAI on generate, critic and coach requests.
Every write endpoint requires the key and is rate-limited per client, but the
public site still lets anyone spend your tokens. So:

- Set a monthly limit in the Anthropic Console (Settings → Limits) and in the
  OpenAI dashboard (Billing → Limits).
- `MTG_CRITIC_MAX_USD_PER_JOB` (default 1.50) caps each critic job. Set it
  lower with `fly secrets set` or under `[env]` in `fly.toml`.
- To turn LLM calls off completely, unset the provider keys:
  `fly secrets unset ANTHROPIC_API_KEY OPENAI_API_KEY`.

## Operations

| Task | Command |
| --- | --- |
| Logs | `fly logs --app mtg-deck-lab-api` |
| Shell | `fly ssh console --app mtg-deck-lab-api` |
| Refresh cards now | `gh workflow run refresh-cards.yml` |
| Rotate the API key | `fly secrets set MTG_API_KEY=new,old`, update Vercel, redeploy web, then `fly secrets set MTG_API_KEY=new` |
| Back up the DB | `fly ssh sftp get /data/mtg_deck_builder.db --app mtg-deck-lab-api` |
| Rebuild the DB from scratch | `fly ssh console -C "rm /data/mtg_deck_builder.db"`, then `fly apps restart` |

**Memory.** On Fly, uvicorn settles at about 650 MB on the 1 GB machine.
The bootstrap runs before the server starts and exits before it, so the two
never compete for memory. `swap_size_mb = 512` adds headroom, but only while
it stays above the first `[section]` header in `fly.toml`. If `fly logs` ever
shows an OOM, check `cat /proc/swaps` over `fly ssh console` first. Then set
`[[vm]] memory = "2gb"` (about $5/month more) and run `fly deploy`.

The first deploy needed 1.85 GB. The cause was concurrent cache builds during
the slow warm-up, now fixed with `app/services/locked_cache.py`. If memory is
well above 650 MB again, look for a new lazily built cache that doesn't use
`locked_cached_property`.

**Saved decks and history** live in the same SQLite file, so they survive
deploys and restarts. Fly snapshots volumes daily and keeps 5 days of them
(`fly volumes snapshots list`).
