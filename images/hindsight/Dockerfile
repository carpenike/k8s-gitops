# Hindsight memory server for the Hermes bots (namespace hermes-memory;
# docs/apps/hermes-memory.md).
#
# Base: vectorize-io's hindsight-api 1.2.0, the full (non-slim) API image the
# Helm chart deploys, which bakes the local embedding model
# (BAAI/bge-small-en-v1.5, 384 dimensions) and reranker
# (hindsight-ai/hs-rerank-1), so the pod runs with HF_HUB_OFFLINE=1 and no
# internet egress. Pinned by index digest.
#
# Added: the static-keys tenant extension (one Postgres schema per bot, keyed
# by a static API key), vendored from vectorize-io/hindsight at the v1.2.0
# release commit 34a138684a899b6ec34175f7a2b633860466d289,
# hindsight-extensions/static-keys-tenant (MIT, LICENSE.hindsight). Upstream
# ships extensions only as source to copy into a derived image; this follows
# its own Dockerfile. One local change: list_tenants() also returns the base
# schema, so startup migrates it and installs the maintenance routines
# (docs/apps/hermes-memory.md).
ARG HINDSIGHT_IMAGE=ghcr.io/vectorize-io/hindsight-api:1.2.0@sha256:ef1a5ac515a7652fbff605277d44a39e7616e421503c61841189e63ef6db6705
FROM ${HINDSIGHT_IMAGE}

COPY hindsight_ext_static_keys_tenant /app/extensions/hindsight_ext_static_keys_tenant
COPY LICENSE.hindsight /app/extensions/LICENSE.hindsight
ENV PYTHONPATH=/app/extensions

# Fail the build, not the first authenticated request, if the extension does
# not import against this server.
RUN /app/api/.venv/bin/python -c "from hindsight_ext_static_keys_tenant import StaticKeysTenantExtension; print('tenant extension ok:', StaticKeysTenantExtension.__name__)"
