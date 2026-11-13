# Hermes screen pod image.
#
# Vendored from NousResearch/hermes-agent v0.23.0 docker/sandbox-desktop.Dockerfile
# (the image Hermes expects behind a docker/ssh terminal backend: Xvnc, Xfce,
# headed Playwright Chromium, cua-driver, user pn). nousresearch/hermes-sandbox
# is not published for v0.22.x or v0.23.x (latest tag v0.21.7-desktop, which
# still bakes agent-browser), so this builds the v0.23.0 recipe (unchanged from
# v0.22.6 upstream). Local changes, each marked
# "k8s-gitops:" below:
#   - base image pinned by digest; Playwright pinned instead of playwright@1
#   - pn's NOPASSWD sudo removed (the pod runs with no_new_privs anyway)
#   - openssh-server, run as pn on port 22 (sshd_config, entrypoint.sh)
#   - Claude Code and the GitHub CLI, pinned, with their wrappers (claude-code/)
#   - kubectl and the Flux CLI, pinned, with a kubeconfig for the pod's ServiceAccount (kube/)
# Upstream text from here on is unchanged except where marked.
#
# Terminal-backend sandbox image WITH a desktop: the default sandbox base every
# docker/modal/daytona/singularity user already runs (nikolaik/python-nodejs), plus
# the tools that base was missing, plus the same display stack the -desktop Hermes
# image carries (TigerVNC + Xfce components + headed Chromium) and cua-driver, so
# Bot Screen, computer_use and the browser can live INSIDE the sandbox instead of
# on the gateway host. No Hermes runtime in here; the gateway shells in.
#
#   docker build -f docker/sandbox-desktop.Dockerfile -t nousresearch/hermes-sandbox:desktop .
#
# Published as nousresearch/hermes-sandbox:desktop by .github/workflows/sandbox-image.yml
# on releases and manual dispatch only: it carries no Hermes code, so it does not track main.
# The tag lives in the ARG so CI and a local build read one place; hadolint cannot
# see through the substitution, hence the inline ignore.
# k8s-gitops: pinned by digest.
ARG SANDBOX_BASE=docker.io/nikolaik/python-nodejs:python3.13-nodejs26@sha256:e41de97aef65d5fff26c3f433c0a6d8335c4cbd05e7e9a36bd0b252593933064
# hadolint ignore=DL3006
FROM ${SANDBOX_BASE}
SHELL ["/bin/bash", "-euo", "pipefail", "-c"]

# k8s-gitops: Renovate bumps both versions below (the annotations; the
# trycua/cua tag format is handled in .renovaterc.json5).
# renovate: datasource=github-releases depName=trycua/cua
ARG CUA_DRIVER_VERSION=0.41.3
# k8s-gitops: exact Playwright version instead of playwright@1.
# renovate: datasource=npm depName=playwright
ARG PLAYWRIGHT_VERSION=1.65.0
ARG TARGETARCH

ENV DEBIAN_FRONTEND=noninteractive \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright \
    LANG=C.UTF-8

# Everyday tools the nikolaik base lacks (checked 2026-09: no jq, rg, fd, tmux,
# less, vim/nano, zip, rsync, tree, procps beyond ps). Kept to what agents reach
# for from a shell; language toolchains come from the base.
RUN apt-get -o Acquire::Retries=3 update && \
    apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
        jq ripgrep fd-find tmux less nano vim-tiny zip rsync tree procps htop \
        file bsdextrautils ca-certificates locales sudo && \
    ln -sf /usr/bin/fdfind /usr/local/bin/fd && \
    rm -rf /var/lib/apt/lists/*

# Display stack: identical package set to the Hermes -desktop image (Dockerfile,
# HERMES_BOT_DESKTOP=1) so tools/bot_desktop/launcher.sh finds the same binaries.
# Components are launched individually by the launcher, never xfce4-session.
RUN apt-get -o Acquire::Retries=3 update && \
    apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
        tigervnc-standalone-server xfce4-panel xfwm4 xfdesktop4 xfce4-settings xfce4-terminal \
        dbus-x11 x11-xserver-utils x11-utils x11-xkb-utils xauth fonts-dejavu-core \
        at-spi2-core libgtk-3-0 libnss3 libasound2 libxss1 && \
    rm -rf /var/lib/apt/lists/*

# Headed Chromium through Playwright (the same build the Hermes -desktop image
# uses), so the agent's browser and the dock's Browser icon share one binary and
# one --user-data-dir: tools/bot_desktop/sandbox_host.py finds it under
# /opt/playwright. --with-deps pulls the Chromium runtime libraries.
RUN for i in 1 2 3; do \
        npx --yes "playwright@${PLAYWRIGHT_VERSION}" install --with-deps chromium && break || \
        { [ "$i" = 3 ] && exit 1; echo "playwright chromium install failed (attempt $i); retrying in 10s"; sleep 10; }; \
    done && chmod -R a+rX /opt/playwright

# cua-driver: computer_use's MCP driver. Pinned release tarball from the
# cua-driver-rs-v* tags (never releases/latest: prereleases publish 0 assets).
RUN set -eu; \
    case "${TARGETARCH:-amd64}" in \
        amd64) arch=x86_64 ;; \
        arm64) arch=arm64 ;; \
        *) echo "unsupported TARGETARCH ${TARGETARCH}"; exit 1 ;; \
    esac; \
    mkdir -p /opt/cua-driver; \
    curl -fsSL "https://github.com/trycua/cua/releases/download/cua-driver-rs-v${CUA_DRIVER_VERSION}/cua-driver-rs-${CUA_DRIVER_VERSION}-linux-${arch}-binary.tar.gz" \
        | tar -xz -C /opt/cua-driver; \
    ln -sf /opt/cua-driver/cua-driver /usr/local/bin/cua-driver; \
    /usr/local/bin/cua-driver --version

# Pillow: the Screen pane's thumbnail is grabbed INSIDE the sandbox (the X socket and its cookie live
# here, not on the gateway host). Also used by the base for ad-hoc image work.
RUN pip install --no-cache-dir "pillow>=10" && python3 -c "from PIL import ImageGrab"

# The base's default user stays root, exactly like nikolaik today, so existing
# docker_image users see no ownership or PATH change. Desktop processes (Xvnc,
# Xfce, Chromium, cua-driver) are exec'd as the base's unprivileged `pn` (uid
# 1000): Chromium refuses to run as root without --no-sandbox and cua-driver's
# AT-SPI bus wants a real user session. `pn` may sudo for ad-hoc installs.
# k8s-gitops: no sudoers entry for pn.
RUN mkdir -p /tmp/.X11-unix && chmod 1777 /tmp/.X11-unix && \
    mkdir -p /tmp/hermes-runtime && chown pn:pn /tmp/hermes-runtime && chmod 0700 /tmp/hermes-runtime

# Runtime dir for dbus/Xvnc; containers have no logind to create it. Both /tmp
# paths above are fixed by the X11 protocol / seeded per container, never shared.
ENV XDG_RUNTIME_DIR=/tmp/hermes-runtime
# Dockerfile ENV reaches `docker exec` only. When this image is the target of the
# ssh backend (sshd added on top), a login session gets its environment from PAM,
# so the browser location must also live where pam_env reads it, or Playwright
# launched over ssh without an explicit executable path (agent or user scripts)
# looks in ~/.cache/ms-playwright and finds no browser while working under
# docker exec.
RUN printf 'PLAYWRIGHT_BROWSERS_PATH=/opt/playwright\nXDG_RUNTIME_DIR=/tmp/hermes-runtime\n' >> /etc/environment
# k8s-gitops: sshd for the Hermes ssh terminal backend, run as pn. Host keys
# come from the pod's Secret at start; none are baked into the image.
RUN apt-get -o Acquire::Retries=3 update && \
    apt-get -o Acquire::Retries=3 install -y --no-install-recommends openssh-server && \
    rm -rf /var/lib/apt/lists/* /etc/ssh/ssh_host_* && \
    rm -f /etc/sudoers.d/* && \
    usermod --shell /bin/bash pn
COPY --chmod=0644 sshd_config /etc/ssh/sshd_config.hermes
COPY --chmod=0755 entrypoint.sh /usr/local/bin/hermes-screen-entrypoint
# k8s-gitops: Claude Code and the GitHub CLI, for multi-turn coding sessions
# (docs/apps/hermes.md, "Coding with Claude Code"). No credential is baked in: with
# the bot's CLAUDE_CODE_ENABLED, the pod mounts the Claude subscription token
# and the GitHub token under /etc/hermes-claude-code, and the wrappers in
# claude-code/ read them from there (ssh sessions do not inherit the pod's
# environment). Claude Code never updates itself; its version moves with
# this file.
# renovate: datasource=npm depName=@anthropic-ai/claude-code
ARG CLAUDE_CODE_VERSION=2.1.319
# renovate: datasource=github-releases depName=cli/cli
ARG GH_VERSION=v2.103.3
RUN npm install -g --prefix /opt/claude-code "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" && \
    npm cache clean --force && \
    /opt/claude-code/bin/claude --version
RUN set -eu; \
    case "${TARGETARCH:-amd64}" in \
        amd64|arm64) arch="${TARGETARCH:-amd64}" ;; \
        *) echo "unsupported TARGETARCH ${TARGETARCH}"; exit 1 ;; \
    esac; \
    ver="${GH_VERSION#v}"; tarball="gh_${ver}_linux_${arch}.tar.gz"; \
    cd /tmp; \
    curl -fsSLO "https://github.com/cli/cli/releases/download/v${ver}/${tarball}"; \
    curl -fsSL "https://github.com/cli/cli/releases/download/v${ver}/gh_${ver}_checksums.txt" \
        | grep " ${tarball}\$" | sha256sum -c -; \
    tar -xzf "${tarball}"; mv "gh_${ver}_linux_${arch}" /opt/gh; rm -f "${tarball}"; \
    /opt/gh/bin/gh --version
COPY --chmod=0755 claude-code/claude claude-code/gh /usr/local/bin/
# k8s-gitops: kubectl and the Flux CLI for a bot with CLUSTER_ACCESS_ENABLED
# (docs/apps/hermes.md, "Cluster access"), pinned and checksum-verified. The
# wrappers in kube/ point both at kube/kubeconfig, which reads the pod's own
# ServiceAccount token; what that token may do is the bot's RBAC, not this
# image. Keep kubectl near the cluster's version and flux at Flux's.
# renovate: datasource=github-releases depName=kubernetes/kubernetes
ARG KUBECTL_VERSION=v1.37.1
# renovate: datasource=github-releases depName=fluxcd/flux2
ARG FLUX_VERSION=v2.10.0
RUN set -eu; \
    case "${TARGETARCH:-amd64}" in \
        amd64|arm64) arch="${TARGETARCH:-amd64}" ;; \
        *) echo "unsupported TARGETARCH ${TARGETARCH}"; exit 1 ;; \
    esac; \
    install -d -m 0755 /opt/kube; cd /tmp; \
    curl -fsSLo kubectl "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${arch}/kubectl"; \
    echo "$(curl -fsSL "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${arch}/kubectl.sha256")  kubectl" | sha256sum -c -; \
    install -m 0755 kubectl /opt/kube/kubectl; rm -f kubectl; \
    ver="${FLUX_VERSION#v}"; tarball="flux_${ver}_linux_${arch}.tar.gz"; \
    curl -fsSLO "https://github.com/fluxcd/flux2/releases/download/v${ver}/${tarball}"; \
    curl -fsSL "https://github.com/fluxcd/flux2/releases/download/v${ver}/flux_${ver}_checksums.txt" \
        | grep " ${tarball}\$" | sha256sum -c -; \
    tar -xzf "${tarball}" flux; install -m 0755 flux /opt/kube/flux; rm -f flux "${tarball}"; \
    /opt/kube/kubectl version --client; /opt/kube/flux version --client
COPY --chmod=0755 kube/kubectl kube/flux /usr/local/bin/
RUN install -d -m 0755 /etc/hermes-kube
COPY --chmod=0644 kube/kubeconfig /etc/hermes-kube/kubeconfig
# The directory first: BuildKit gives a directory that COPY --chmod creates
# the same mode as the file (0644, not traversable), and Claude Code then
# runs without its managed settings (EACCES, policies not in effect).
RUN install -d -m 0755 /etc/claude-code
COPY --chmod=0644 claude-code/managed-settings.json /etc/claude-code/managed-settings.json
COPY --chmod=0644 claude-code/gitconfig /etc/gitconfig
USER pn
# As pn: managed settings and git config must be readable by the login user.
RUN cat /etc/claude-code/managed-settings.json /etc/gitconfig > /dev/null
WORKDIR /home/pn
EXPOSE 22
CMD ["/usr/local/bin/hermes-screen-entrypoint"]
