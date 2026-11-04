# Hermes agent pod image: upstream nousresearch/hermes-agent, unchanged, plus
# what Hermes would otherwise fetch at runtime (the agent pod has no internet
# egress). Each piece is inert unless the bot's inputs turn it on
# (docs/hermes.md):
#   - the Outlook MCP server (Softeria ms-365-mcp-server): OUTLOOK_MCP_ENABLED
#   - the Hindsight memory provider plugin and hindsight-client:
#     HINDSIGHT_ENABLED (docs/hermes-memory.md)
#   - the matrix-profile plugin (local, matrix-profile/): the bot changes its
#     own Matrix display name and avatar; MATRIX_PROFILE_TOOLS
#
# Pins: the base by digest (below, and Renovate's docker datasource); the
# Outlook server and every transitive package by outlook-mcp/package-lock.json
# (integrity hashes; `npm ci` refuses a mismatch), with optional dependencies
# (keytar, Azure identity/Key Vault) and install scripts left out; the
# Hindsight plugin by its vendored source (hindsight/plugin, from
# vectorize-io/hindsight d952b6e655fccab4581ee0722b51c5f103873d12, the commit
# Hermes v0.22.6's plugin-catalog/hindsight.yaml names) and hindsight-client
# by hindsight/requirements.txt (hashes).

ARG HERMES_AGENT_IMAGE=docker.io/nousresearch/hermes-agent:v0.22.6@sha256:d27689bc6e8581ec884a7227c9101fdaebf6c853cff8859020dac14f21452b4d

# Pure-Python wheels for Hermes' venv, built against the same Python (3.14.9).
FROM docker.io/library/python:3.14.9-slim@sha256:35caba83af2fe6da9a5d922f9b0156f21d1246a48278c58a08bd253303ba42e8 AS hindsight-client
COPY hindsight/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --no-deps --require-hashes --only-binary=:all: \
      --target /out -r /tmp/requirements.txt

FROM ${HERMES_AGENT_IMAGE}

COPY outlook-mcp/package.json outlook-mcp/package-lock.json /opt/outlook-mcp/
RUN cd /opt/outlook-mcp \
    && HOME=/tmp npm ci --omit=optional --omit=dev --ignore-scripts --no-audit --no-fund \
    && rm -rf /tmp/.npm \
    && node node_modules/@softeria/ms-365-mcp-server/dist/index.js --version

COPY --chmod=0644 outlook-mcp/enabled-tools.txt /opt/outlook-mcp/enabled-tools.txt
COPY --chmod=0755 outlook-mcp/outlook-mcp /usr/local/bin/outlook-mcp
COPY --chmod=0755 hermes-outlook-config /usr/local/bin/hermes-outlook-config

# Hindsight. The plugin lives OUTSIDE /opt/data (the bot's PVC would shadow
# anything baked there); the config init container copies it to
# $HERMES_HOME/plugins/hindsight, where Hermes finds user memory providers
# (plugins/memory/__init__.py: bundled, then $HERMES_HOME/plugins/<name>,
# then project, then entry points; activated by memory.provider).
COPY --from=hindsight-client /out/ /opt/hermes/.venv/lib/python3.14/site-packages/
COPY hindsight/plugin /opt/hermes-plugins/hindsight
COPY hindsight/LICENSE.hindsight /opt/hermes-plugins/hindsight/LICENSE
RUN /opt/hermes/.venv/bin/python -c "import hindsight_client, aiohttp_retry; from hindsight_client import Hindsight; print('hindsight-client ok')" \
    && HERMES_HOME=/tmp/hermes-plugin-check sh -c ' \
         mkdir -p "$HERMES_HOME/plugins" \
         && cp -r /opt/hermes-plugins/hindsight "$HERMES_HOME/plugins/hindsight" \
         && cd /opt/hermes \
         && /opt/hermes/.venv/bin/python -c "import sys; sys.path.insert(0, \"/opt/hermes\"); from plugins.memory import find_provider_dir, load_memory_provider; d = find_provider_dir(\"hindsight\"); assert d is not None, \"hindsight not discovered\"; p = load_memory_provider(\"hindsight\"); assert p is not None, \"hindsight did not load\"; print(\"hindsight provider ok:\", d, type(p).__name__)"' \
    && rm -rf /tmp/hermes-plugin-check

# matrix-profile (local plugin, matrix-profile/): tools matrix_get_profile,
# matrix_set_display_name, matrix_set_avatar. Copied into
# $HERMES_HOME/plugins and listed in plugins.enabled by the component's init
# container when MATRIX_PROFILE_TOOLS is on. Build check: discovery loads it
# and its three tools register.
COPY matrix-profile /opt/hermes-plugins/matrix-profile
RUN HERMES_HOME=/tmp/hermes-plugin-check sh -c ' \
         mkdir -p "$HERMES_HOME/plugins" \
         && cp -r /opt/hermes-plugins/matrix-profile "$HERMES_HOME/plugins/matrix-profile" \
         && printf "plugins:\n  enabled:\n    - matrix-profile\n" > "$HERMES_HOME/config.yaml" \
         && cd /opt/hermes \
         && /opt/hermes/.venv/bin/python -c "import sys; sys.path.insert(0, \"/opt/hermes\"); from hermes_cli.plugins import discover_plugins; discover_plugins(); from tools.registry import registry; names = (\"matrix_get_profile\", \"matrix_set_display_name\", \"matrix_set_avatar\"); missing = [n for n in names if registry.get_entry(n) is None]; assert not missing, missing; print(\"matrix-profile plugin ok\")"' \
    && rm -rf /tmp/hermes-plugin-check
