# upsmon on this host, talking to the local upsd. The password is
# data.upsmonPassword in topf.yaml, a vals ref to the one SOPS secret.
# topf 0.6.2 ships sprig 3.3.0, which has fail and not required.
# Until the DaemonSet is running, upsmon keeps retrying. That is expected.
apiVersion: v1alpha1
kind: ExtensionServiceConfig
name: nut-client
configFiles:
  - content: |
      MONITOR apc@127.0.0.1 1 upsmon {{ if not .Data.upsmonPassword }}{{ fail "nut upsmon password was not decrypted" }}{{ else }}{{ .Data.upsmonPassword }}{{ end }} secondary
      SHUTDOWNCMD "/sbin/poweroff"
    mountPath: /usr/local/etc/nut/upsmon.conf
