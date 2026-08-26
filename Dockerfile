# HarnessRouter — self-hosted, all-in-one.
#
# One container runs the whole product: the UI, the gateway, and the agent runner. There is
# no cloud dependency, no control plane to reach, and nothing to provision. State is SQLite
# and files on one mounted volume.
#
# Why one container rather than compose-by-default: self-hosting should be `docker run`. The
# three processes are supervised by a tiny entrypoint, and because the gateway talks to the
# runner over loopback it needs no pool, no service discovery and no cloud identity.
#
# AGENT CLIs ARE INSTALLED ON FIRST RUN, NOT BAKED IN. This is a licensing requirement, not a
# size optimisation: Claude Code ships under Anthropic's own terms ("SEE LICENSE IN README.md")
# and hermes-agent declares no license at all, so neither may be redistributed inside a public
# image. Installing them at first start means YOU install them, under their terms, exactly as
# if you had run npm/pip yourself — and it keeps this image redistributable.
#
# They land in the data volume, so the cost is paid once per volume rather than once per start.
# Choose backends at RUN time:
#
#   docker run -e HR_BACKENDS=claude,codex,hermes,pi,dsh,opencode ...   # the default
#   docker run -e HR_BACKENDS=opencode                            ...   # lean
#
# WITH_BROWSER is still a build arg because Chromium and its system libraries genuinely belong
# in the image layer.

# ── UI build ──────────────────────────────────────────────────────────────────
# This is the SAME console the hosted product runs. Surfaces with no self-hosted backend
# (billing, marketplace, analytics, sign-in) are hidden by the edition flag rather than removed,
# so the two stay one codebase. See ui/src/lib/edition.ts.
FROM node:22-slim AS ui
WORKDIR /ui
# git: the UI depends on the ReifyUI component library straight from its repository.
RUN apt-get update -y && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
# .npmrc matters at THIS layer: it carries legacy-peer-deps, without which npm refuses the
# tree (several deps still declare React 18 peers while the app runs 19).
COPY ui/package.json ui/package-lock.json* ui/.npmrc ./
RUN npm ci --no-audit --no-fund 2>/dev/null || npm install --no-audit --no-fund
COPY ui/ ./
# Inlined into the client bundle at build time, so a self-hosted image can never present a
# hosted-only surface no matter how it is run.
ENV NEXT_TELEMETRY_DISABLED=1 \
    NEXT_PUBLIC_HR_EDITION=selfhost
RUN npm run build

# ── runtime ───────────────────────────────────────────────────────────────────
FROM python:3.12-slim

ARG WITH_BROWSER=0

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NEXT_TELEMETRY_DISABLED=1 \
    HOME=/home/agent \
    HARNESS_WORKSPACE=/data/workspaces \
    HR_DATA_DIR=/data

RUN apt-get update -y && apt-get install -y --no-install-recommends \
        curl ca-certificates git bash tini \
    && rm -rf /var/lib/apt/lists/*

# Document preview. The built-in skills create .docx/.pptx/.xlsx routinely, and LibreOffice is
# also how those become a PDF — the officecli skill's own PDF export needs a plugin that is not
# installed. A presentation you can only download is a worse answer than one you can look at. Browsers render none of them, so the console asks the gateway for a PDF rendition and
# LibreOffice headless is what makes it. Impress/Writer/Calc only, no recommends: the full
# libreoffice metapackage drags in Java and a desktop stack for no benefit here.
ARG WITH_DOC_PREVIEW=1
RUN set -eux; \
    if [ "$WITH_DOC_PREVIEW" = "1" ]; then \
      apt-get update -y && apt-get install -y --no-install-recommends \
        libreoffice-impress libreoffice-writer libreoffice-calc fonts-dejavu-core \
      && rm -rf /var/lib/apt/lists/*; \
    fi

# Assembling generated clips into one film. ffmpeg cuts and letterboxes the shots; ffprobe is how
# the gateway learns a clip's real duration and how the assembled film's length is checked against
# the timeline it was cut from. Built without it, the media server reports export unavailable and
# refuses honestly — every clip is still downloadable on its own — rather than degrading silently.
ARG WITH_MEDIA=1
RUN set -eux; \
    if [ "$WITH_MEDIA" = "1" ]; then \
      apt-get update -y && apt-get install -y --no-install-recommends ffmpeg \
      && rm -rf /var/lib/apt/lists/*; \
    fi

# Node is needed for the UI server and for the npm-based agent CLIs. 22, not 20: pi's
# engine floor is >=22.19, and node 20 has been end-of-life since April 2026 anyway —
# the other CLIs (claude >=18, codex >=20) run unchanged on 22.
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/* /root/.npm

# Optional: browser automation for harnesses that verify their own output.
RUN set -eux; \
    if [ "$WITH_BROWSER" = "1" ]; then \
      pip install --no-cache-dir playwright && playwright install --with-deps chromium; \
    fi

WORKDIR /app

COPY gateway/requirements.txt /app/gateway/requirements.txt
COPY runner/requirements.txt  /app/runner/requirements.txt
# The gateway's requirements include hosted-only clients (cloud identity, the hosted document
# store). They are imported lazily and never touched self-hosted, so they are stripped here to
# keep the image small and the dependency surface honest about what this build actually uses.
RUN grep -viE "^(azure-|azure_)" /app/gateway/requirements.txt > /app/gateway/req.local.txt \
    && pip install --no-cache-dir -r /app/gateway/req.local.txt \
    && pip install --no-cache-dir -r /app/runner/requirements.txt

# Built-in skills, from their own repository. Pinned by ref so two builds of the same image tag
# ship the same catalogue; HR_SKILLS_REF=<sha> for an exact pin, WITH_BUILTIN_SKILLS=0 for none.
ARG WITH_BUILTIN_SKILLS=1
ARG HR_SKILLS_REPO=https://github.com/HarnessRouter/skills.git
ARG HR_SKILLS_REF=main
ENV HR_BUILTIN_SKILLS_DIR=/opt/harnessrouter/skills
# officecli keeps an edited document open in a resident process and flushes it to disk some seconds
# after that process goes idle. A task that writes a document and then ENDS races that timer: the
# last file it touched is collected before the flush, and the user downloads a workbook whose
# content silently is not there — `validate` still passes, because the in-memory document is fine.
# Observed exactly that way: a spreadsheet whose every cell went into a sheet the saved file did
# not contain. Flushing on every command costs some speed and removes the race entirely, which is
# the right trade for a document a person is going to open.
ENV OFFICECLI_RESIDENT_FLUSH=each
COPY docker/install-skills.sh /tmp/install-skills.sh
# The RUN layer is keyed on this ARG, so passing a commit sha is what makes the layer rebuild when
# the skills repo moves. Leaving HR_SKILLS_REF at `main` keeps whatever catalogue an earlier build
# fetched — release CI resolves the sha and passes it, which is both the cache-bust and the record
# of exactly what shipped. A local build that wants the newest skills should pass a sha too.
#
# This used to be an `ADD https://api.github.com/...` fetching the branch head. That call is
# unauthenticated, GitHub allows 60 an hour per IP, and CI runners share a busy pool — so every
# release build eventually died on "failed to load cache key: invalid response status 403" before
# it compiled a line.
RUN chmod +x /tmp/install-skills.sh \
    && WITH_BUILTIN_SKILLS="$WITH_BUILTIN_SKILLS" HR_SKILLS_REPO="$HR_SKILLS_REPO" \
       HR_SKILLS_REF="$HR_SKILLS_REF" HR_SKILLS_DIR=/opt/harnessrouter/skills \
       /tmp/install-skills.sh \
    && rm -f /tmp/install-skills.sh

# Starter Kits: a Harness plus an app, both baked in. Same pull-and-pin shape as the skills
# bundle above, and the same rule: pass a commit sha to get the newest catalogue, because that
# is what changes the layer's inputs.
# What this build IS, for the discovery document and anything else that reports a version. The
# release workflow passes the tag; a local build says so honestly rather than claiming a number.
# Without this the gateway fell back to a literal that had been six releases stale, so every
# install told clients it was 0.3.0 (found by the 0.9.0 release sanity run).
ARG HR_VERSION=dev
ENV HR_VERSION=${HR_VERSION}

ARG WITH_STARTER_KITS=1
ARG HR_KITS_REPO=https://github.com/HarnessRouter/starter-kit.git
ARG HR_KITS_REF=main
ENV HR_KITS_DIR=/opt/harnessrouter/kits
COPY docker/install-kits.sh /tmp/install-kits.sh
RUN chmod +x /tmp/install-kits.sh \
    && WITH_STARTER_KITS="$WITH_STARTER_KITS" HR_KITS_REPO="$HR_KITS_REPO" \
       HR_KITS_REF="$HR_KITS_REF" HR_KITS_DIR=/opt/harnessrouter/kits \
       /tmp/install-kits.sh \
    && rm -f /tmp/install-kits.sh

COPY gateway/ /app/gateway/
COPY runner/  /app/runner/
COPY docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Next.js standalone output: server + only the modules it actually needs.
COPY --from=ui /ui/.next/standalone /app/ui/
COPY --from=ui /ui/.next/static     /app/ui/.next/static
COPY --from=ui /ui/public           /app/ui/public

# `agent` is the PRODUCT's user: the gateway and the console run as it and it owns the data
# volume. The container itself starts as root and the entrypoint drops privileges per process,
# because the runner needs root for one thing: every agent CLI runs as its own per-session uid,
# which owns its session directory and nothing else (the write-wall; see docker/entrypoint.sh).
# The CLIs refuse to run as root anyway (they gate their own permission bypass on it), and they
# never do.
#
# The `rm -rf /home/agent/.npm` is not tidying. HOME is already /home/agent while the kit apps are
# built above, and those builds run as root — so npm leaves ~1600 root-owned files in the cache
# the RUNTIME user then cannot write to. First start-up installs the agent CLIs into the data
# volume as `agent`, npm hits EACCES on its own cache, and the install fails. Its output is
# discarded (entrypoint.sh: `|| true`), so the only symptom is one WARN line and then every turn
# on Claude Code or Codex failing. Hermes survives because it installs through pip, into a venv.
#
# That made two of the three backends unusable on any fresh volume — which is EVERY new install of
# this image. It was invisible here because a long-lived volume keeps CLIs installed before the
# fault existed. The cache is build-time garbage with no runtime value, so it is deleted rather
# than chowned: nothing can inherit ownership of something that is not there.
RUN useradd -m -u 10001 agent \
    && rm -rf /home/agent/.npm /root/.npm \
    && mkdir -p /data \
    && chown -R agent:agent /data /app /home/agent \
    && chmod -R a+rX /opt/harnessrouter/skills /opt/harnessrouter/kits

EXPOSE 3000
VOLUME ["/data"]

# The UI is the only published port. The gateway and runner stay on loopback — nothing else
# needs to be reachable from outside the container.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s \
  CMD curl -fsS http://127.0.0.1:8080/healthz >/dev/null || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/app/entrypoint.sh"]
