"""Connect Grafana's OnCall app plugin to the OnCall engine.

Port of Forge's one-shot grafana-oncall-plugin-setup unit (nix-config
hosts/forge/infrastructure/observability/grafana.nix). Idempotent:

- plugin enabled and pointing at the URLs below: ask the plugin to sync,
  and stop (a failed sync is reported, not fatal, as on Forge);
- otherwise (a fresh Grafana, or Forge's grafana.db with Forge's URLs after
  the cutover): write the settings, then call the plugin's install, which
  hands the engine Grafana's URL and a service account token.

stackId 5 and orgId 100 are the values self-hosted OnCall expects.
"""

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

GRAFANA_URL = os.environ["GRAFANA_URL"].rstrip("/")
ONCALL_API_URL = os.environ["ONCALL_API_URL"]
GRAFANA_URL_FOR_ONCALL = os.environ["GRAFANA_URL_FOR_ONCALL"]
ADMIN_USER = os.environ.get("GRAFANA_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ["GRAFANA_ADMIN_PASSWORD"]
PLUGIN = "/api/plugins/grafana-oncall-app"

AUTH = "Basic " + base64.b64encode(
    f"{ADMIN_USER}:{ADMIN_PASSWORD}".encode()
).decode()


def call(method, url, body=None, auth=True, timeout=30):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method)
    if auth:
        req.add_header("Authorization", AUTH)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        return resp.status, (json.loads(raw) if raw else None)


def wait_for(name, url, tries=60, delay=5):
    for i in range(1, tries + 1):
        try:
            status, _ = call("GET", url, auth=False, timeout=10)
            if status == 200:
                print(f"{name} is ready", flush=True)
                return
        except (urllib.error.URLError, OSError, ValueError) as exc:
            print(f"waiting for {name} ({i}/{tries}): {exc}", flush=True)
        time.sleep(delay)
    sys.exit(f"{name} did not become ready")


def main():
    wait_for("Grafana", f"{GRAFANA_URL}/api/health")
    wait_for("OnCall engine", f"{ONCALL_API_URL.rstrip('/')}/health/")

    try:
        _, settings = call("GET", f"{GRAFANA_URL}{PLUGIN}/settings")
    except urllib.error.HTTPError as exc:
        sys.exit(f"reading plugin settings failed: HTTP {exc.code}")
    settings = settings or {}
    json_data = settings.get("jsonData") or {}
    current = (
        settings.get("enabled") is True
        and json_data.get("onCallApiUrl") == ONCALL_API_URL
        and json_data.get("grafanaUrl") == GRAFANA_URL_FOR_ONCALL
    )

    if current:
        print("plugin already enabled with these URLs; syncing", flush=True)
        try:
            call("POST", f"{GRAFANA_URL}{PLUGIN}/resources/plugin/sync", timeout=120)
            print("sync requested", flush=True)
        except urllib.error.HTTPError as exc:
            print(f"warning: sync answered HTTP {exc.code}", flush=True)
        return

    print(
        "configuring plugin (was enabled=%s, onCallApiUrl=%s, grafanaUrl=%s)"
        % (
            settings.get("enabled"),
            json_data.get("onCallApiUrl"),
            json_data.get("grafanaUrl"),
        ),
        flush=True,
    )
    body = {
        "enabled": True,
        "jsonData": {
            "stackId": 5,
            "orgId": 100,
            "onCallApiUrl": ONCALL_API_URL,
            "grafanaUrl": GRAFANA_URL_FOR_ONCALL,
        },
    }
    try:
        call("POST", f"{GRAFANA_URL}{PLUGIN}/settings", body)
        call("POST", f"{GRAFANA_URL}{PLUGIN}/resources/plugin/install", timeout=120)
    except urllib.error.HTTPError as exc:
        sys.exit(f"{exc.url} answered HTTP {exc.code}")
    print("OnCall plugin configured", flush=True)


if __name__ == "__main__":
    main()
