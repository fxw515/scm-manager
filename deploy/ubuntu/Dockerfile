# SPDX-License-Identifier: AGPL-3.0-only
FROM scmmanager/scm-manager:3.12.2 AS upstream

FROM node:22-bookworm-slim AS frontend
WORKDIR /src
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY . .
RUN yarn install --frozen-lockfile --ignore-scripts --non-interactive \
    && yarn build

FROM python:3.12-slim AS localization
WORKDIR /src
COPY . .
COPY --from=frontend /src/scm-ui/build/webapp/assets /src/scm-ui/build/webapp/assets
COPY --from=upstream /opt/scm-server/var/webapp/scm-webapp.war /tmp/upstream.war
RUN python deploy/ubuntu/localize.py --check \
    && python deploy/ubuntu/localize.py --input-war /tmp/upstream.war --output-war /tmp/zh.war

FROM upstream
COPY --from=localization --chown=1000:0 /tmp/zh.war /opt/scm-server/var/webapp/scm-webapp.war
LABEL io.scm-manager.zh.version="3.12.2-zh.1" \
      org.opencontainers.image.licenses="AGPL-3.0-only"
# Inherit upstream non-root user, entrypoint and health check.
