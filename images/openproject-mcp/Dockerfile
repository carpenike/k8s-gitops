# openproject-mcp: a small streamable-HTTP MCP server for the OpenProject task
# board the Hermes bots share (README.md). The server holds no OpenProject
# secret: each MCP request brings the caller's own OpenProject API token.
#
# Pins: both base images by tag and index digest (Renovate's docker
# datasource); Python packages by uv.lock (exact versions and sha256 hashes;
# `uv sync --locked` refuses a lock that does not match pyproject.toml).
# The test stage runs the suite, and the final stage copies a marker from it,
# so a failing test fails the image build. The final stage has no uv and no
# test dependencies. It runs as 65532 and writes nothing outside /tmp, so it
# works with readOnlyRootFilesystem.
#
# Tags live in the ARGs; hadolint cannot see through the substitution, hence
# the inline ignores.
ARG PYTHON_IMAGE=docker.io/library/python:3.13.18-slim@sha256:09a17cad02668ae61ece136b4fd36ac3849e14f670ebedb637ea3e15580525bc
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff

# hadolint ignore=DL3006
FROM ${UV_IMAGE} AS uv

# Runtime dependencies into /app/.venv, against the same Python as the final stage.
# hadolint ignore=DL3006
FROM ${PYTHON_IMAGE} AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3 \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

# The test suite, in its own venv (runtime + dev group). Never shipped.
FROM build AS test
ENV UV_PROJECT_ENVIRONMENT=/opt/test-venv \
    PYTHONDONTWRITEBYTECODE=1
COPY src ./src
COPY tests ./tests
RUN uv sync --locked \
    && /opt/test-venv/bin/python -m pytest -q -p no:cacheprovider \
    && touch /tests-passed

# hadolint ignore=DL3006
FROM ${PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PATH=/app/.venv/bin:$PATH \
    HOME=/tmp \
    PORT=8000
COPY --from=build /app/.venv /app/.venv
COPY src /app/src
COPY LICENSE.homelab-mcp README.md /app/
# Ties this stage to the test stage: no marker, no image.
COPY --from=test /tests-passed /app/.tests-passed
RUN python -m compileall -q /app/src \
    && python -c "import openproject_mcp.app; print('openproject-mcp', openproject_mcp.__version__)"
USER 65532:65532
EXPOSE 8000
ENTRYPOINT ["python", "-m", "openproject_mcp.app"]
