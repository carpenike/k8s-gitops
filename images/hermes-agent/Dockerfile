# Hermes agent pod image: upstream nousresearch/hermes-agent, unchanged, plus
# the Outlook MCP server (Softeria ms-365-mcp-server) baked in, so nothing is
# fetched with npx/npm at runtime (the agent pod has no internet egress).
# Inert unless a bot sets OUTLOOK_MCP_ENABLED=true (docs/hermes.md).
#
# Pins: the base by digest (below, and Renovate's docker datasource), the
# server and every transitive package by outlook-mcp/package-lock.json
# (integrity hashes; `npm ci` refuses a mismatch). Optional dependencies
# (keytar, Azure identity/Key Vault) and install scripts are left out.
ARG HERMES_AGENT_IMAGE=docker.io/nousresearch/hermes-agent:v0.22.6@sha256:d27689bc6e8581ec884a7227c9101fdaebf6c853cff8859020dac14f21452b4d
FROM ${HERMES_AGENT_IMAGE}

COPY outlook-mcp/package.json outlook-mcp/package-lock.json /opt/outlook-mcp/
RUN cd /opt/outlook-mcp \
    && HOME=/tmp npm ci --omit=optional --omit=dev --ignore-scripts --no-audit --no-fund \
    && rm -rf /tmp/.npm \
    && node node_modules/@softeria/ms-365-mcp-server/dist/index.js --version

COPY --chmod=0644 outlook-mcp/enabled-tools.txt /opt/outlook-mcp/enabled-tools.txt
COPY --chmod=0755 outlook-mcp/outlook-mcp /usr/local/bin/outlook-mcp
COPY --chmod=0755 hermes-outlook-config /usr/local/bin/hermes-outlook-config
