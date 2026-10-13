# API image for Fly.io (see docs/DEPLOY.md). Build context is the repo root:
# the API reads versioned LLM prompts from <repo>/.claude/skills.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv
COPY api/requirements.txt api/requirements.txt
RUN pip install -r api/requirements.txt

COPY api/ api/
COPY .claude/skills/ .claude/skills/

WORKDIR /srv/api
# SQLite on the Fly volume mounted at /data (fly.toml [[mounts]]).
ENV DATABASE_URL=sqlite:////data/mtg_deck_builder.db
EXPOSE 8080
CMD ["sh", "deploy/start.sh"]
