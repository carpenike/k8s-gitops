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
# k8s-gitops: the bot's own SSH key for hosts outside the cluster (input
# HOST_SSH_ENABLED; docs/apps/hermes.md, "Host SSH"). ssh refuses a key
# others can read, so it is copied to a pn-owned 0600 file. The ssh config
# and the pinned host keys come with it. Absent: nothing changes.
hosts=/etc/hermes-host-ssh
if [ -s "$hosts/id_ed25519" ]; then
  install -d -m 0700 "$HOME/.ssh"
  install -m 0600 "$hosts/id_ed25519" "$HOME/.ssh/id_hosts"
  # The restart-only key (alias forge-svc): the host forces it into a
  # restart|reload-only command, so the bot may run those without a prompt.
  if [ -s "$hosts/id_svc" ]; then
    install -m 0600 "$hosts/id_svc" "$HOME/.ssh/id_hosts_svc"
  fi
  install -m 0600 "$hosts/config" "$HOME/.ssh/config"
  install -m 0644 "$hosts/known_hosts" "$HOME/.ssh/known_hosts_hosts"
fi
exec /usr/sbin/sshd -D -e -f /etc/ssh/sshd_config.hermes
