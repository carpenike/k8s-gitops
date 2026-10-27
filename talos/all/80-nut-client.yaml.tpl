# Forge (forge.holthome.net, 10.20.0.30) is the NUT server Ryan chose.
# The UPS name `apc` is the stand-in from the nix-config plan; that plan
# did not name the UPS, so confirm it before apply. Forge's NUT service
# is a nix-config change and is not done yet.
# The password is read from the environment at apply time. It is not in git.
# No v1 item. Proposed item: nut, fields username and password.
# The password is read at apply time. It is not committed.
apiVersion: v1alpha1
kind: ExtensionServiceConfig
name: nut-client
configFiles:
  - content: |
      MONITOR apc@forge.holthome.net 1 upsmon {{ required "Set NUT_UPSMON_PASSWORD from 1Password item PLACEHOLDER_ITEM_nut (proposed item nut, field password)" (env "NUT_UPSMON_PASSWORD") }} secondary
      SHUTDOWNCMD "/sbin/poweroff"
    mountPath: /usr/local/etc/nut/upsmon.conf
