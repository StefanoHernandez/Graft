# The widget is built here so the image carries a bundle nobody has to remember
# to build. Node is pinned by digest: a silently newer toolchain is how two
# builds of the same commit stop being the same image.
FROM node:22.12.0-slim@sha256:35531c52ce27b6575d69755c73e65d4468dba93a25644eed56dc12879cae9213 AS widget
WORKDIR /w
COPY widget/package.json widget/package-lock.json ./
RUN npm ci
COPY widget/ ./
RUN npm run build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.13@sha256:b485bd65cc2cf1c9a93b3554012c9c3778cf7b1b5fd3d3096ce9e1226c97e1e6 /uv /usr/local/bin/uv
WORKDIR /app

# Lockfile first, and --frozen: the build installs what was resolved and tested,
# or it fails. Without the lock, `uv sync` is free to pick newer versions than
# anything that was ever run against this code.
COPY server/pyproject.toml server/uv.lock ./
RUN uv sync --no-dev --frozen --no-install-project

COPY server/ ./
RUN uv sync --no-dev --frozen
COPY --from=widget /w/dist /widget/dist
RUN chmod +x entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
