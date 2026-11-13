#!/bin/sh
# Screen pod entrypoint: copy the host key and the agent's public key out of
# the read-only Secret mount into pn-owned 0600 files (sshd's StrictModes and
# host-key checks refuse group-readable files), then run sshd in the
# foreground as pn. The desktop (Xvnc, Xfce, Chromium, cua-driver) is started
# on demand by Hermes over ssh, not here.
set -eu
src=/etc/hermes-ssh
dst="$HOME/.sshd"
install -d -m 0700 "$dst"
install -m 0600 "$src/ssh_host_ed25519_key" "$dst/ssh_host_ed25519_key"
install -m 0600 "$src/authorized_keys" "$dst/authorized_keys"
exec /usr/sbin/sshd -D -e -f /etc/ssh/sshd_config.hermes
