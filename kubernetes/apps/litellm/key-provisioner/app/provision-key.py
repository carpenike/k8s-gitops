"""Provision one LiteLLM virtual key and write it into a Kubernetes Secret.

Run by the Job in ../template, in namespace litellm, with the proxy's
master key from Secret litellm-env. Standard library only. Steps:

0. Refuse unless Secret TARGET_NAMESPACE/SECRET_NAME carries this
   provisioner's labels (app.kubernetes.io/name=litellm-key-provisioner,
   app.kubernetes.io/instance=KEY_ALIAS), so a mistyped name never writes
   into some other Secret.
1. Find team TEAM_ALIAS, or create it. The team groups spend for every key
   in it; it sets no model list, so each key's own list applies.
2. If Secret TARGET_NAMESPACE/SECRET_NAME already holds a key that
   /key/info knows under KEY_ALIAS, update that key's models and budget to
   match and stop. The key value does not change.
3. Otherwise delete any key with alias KEY_ALIAS (LiteLLM stores only a
   hash, so a lost Secret cannot be read back), generate a new one, and
   merge-patch it into the Secret under SECRET_KEY_NAME (default
   LITELLM_API_KEY). RBAC allows get and
   patch on that one Secret and nothing else.

Keys are never printed.
"""

import base64
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

SA_DIR = "/var/run/secrets/kubernetes.io/serviceaccount"
KUBE_API = "https://kubernetes.default.svc"
LABEL_NAME = "litellm-key-provisioner"


def log(msg):
    print(msg, flush=True)


def request(method, url, token=None, body=None, content_type="application/json", context=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", content_type)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30, context=context) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as err:
        raw = err.read()
        try:
            return err.code, json.loads(raw or b"{}")
        except ValueError:
            return err.code, {"error": raw.decode(errors="replace")[:200]}
    except (urllib.error.URLError, OSError) as err:
        # DNS, refused, timeout: status 0, and the reason in the message.
        reason = getattr(err, "reason", err)
        host = urllib.parse.urlsplit(url).netloc
        return 0, {"error": f"{host}: {reason}", "message": f"{host}: {reason}"}


def error_text(body):
    err = body.get("error") if isinstance(body, dict) else body
    if isinstance(err, dict):
        return str(err.get("message", err))[:300]
    return str(err or body)[:300]


def main():
    alias = os.environ["KEY_ALIAS"]
    team_alias = os.environ["TEAM_ALIAS"]
    models = [m.strip() for m in os.environ["MODELS"].split(",") if m.strip()]
    # "<USD>/<duration>", for example 25/30d. One string, because Flux
    # substitutes after kustomize build has dropped the quotes, so a bare
    # number would reach the API server as an int.
    amount, _, budget_duration = os.environ["BUDGET"].partition("/")
    try:
        max_budget = float(amount)
    except ValueError:
        sys.exit(f"invalid BUDGET {os.environ['BUDGET']!r}: use <USD>/<duration>, e.g. 25/30d")
    if not budget_duration:
        sys.exit(f"invalid BUDGET {os.environ['BUDGET']!r}: missing /<duration>")
    namespace = os.environ["TARGET_NAMESPACE"]
    secret_name = os.environ["SECRET_NAME"]
    base = os.environ["LITELLM_URL"].rstrip("/")
    master = os.environ["LITELLM_MASTER_KEY"].strip()
    secret_key = os.environ.get("SECRET_KEY_NAME", "").strip() or "LITELLM_API_KEY"

    with open(f"{SA_DIR}/token") as f:
        kube_token = f.read().strip()
    kube_ctx = ssl.create_default_context(cafile=f"{SA_DIR}/ca.crt")
    secret_url = f"{KUBE_API}/api/v1/namespaces/{namespace}/secrets/{secret_name}"

    status, secret = request("GET", secret_url, token=kube_token, context=kube_ctx)
    if status != 200:
        sys.exit(f"GET secret {namespace}/{secret_name}: HTTP {status} {secret.get('message', '')}")
    labels = (secret.get("metadata") or {}).get("labels") or {}
    if labels.get("app.kubernetes.io/name") != LABEL_NAME or labels.get("app.kubernetes.io/instance") != alias:
        sys.exit(f"refusing to write {namespace}/{secret_name}: it lacks the labels "
                 f"app.kubernetes.io/name={LABEL_NAME}, app.kubernetes.io/instance={alias}")
    stored = base64.b64decode((secret.get("data") or {}).get(secret_key, "")).decode()

    status, teams = request("GET", f"{base}/team/list", token=master)
    if status != 200:
        sys.exit(f"team/list: HTTP {status} {error_text(teams)}")
    if isinstance(teams, dict):
        teams = teams.get("teams", teams.get("data", []))
    team_id = next((t["team_id"] for t in teams if t.get("team_alias") == team_alias), None)
    if team_id:
        log(f"team {team_alias}: exists")
    else:
        status, body = request("POST", f"{base}/team/new", token=master, body={"team_alias": team_alias})
        if status != 200 or "team_id" not in body:
            sys.exit(f"team/new {team_alias}: HTTP {status} {error_text(body)}")
        team_id = body["team_id"]
        log(f"team {team_alias}: created")

    settings = {
        "team_id": team_id,
        "models": models,
        "max_budget": max_budget,
        "budget_duration": budget_duration,
        "metadata": {"managed_by": "k8s-gitops"},
    }

    if stored:
        query = urllib.parse.urlencode({"key": stored})
        status, info = request("GET", f"{base}/key/info?{query}", token=master)
        info = info.get("info", info) if isinstance(info, dict) else {}
        if status == 200 and info.get("key_alias") == alias:
            status, body = request("POST", f"{base}/key/update", token=master, body={"key": stored, **settings})
            if status != 200:
                sys.exit(f"key/update {alias}: HTTP {status} {error_text(body)}")
            log(f"key {alias}: valid, settings reconciled")
            return
        log(f"key {alias}: stored key not found (HTTP {status}), issuing a new one")

    status, body = request("POST", f"{base}/key/delete", token=master, body={"key_aliases": [alias]})
    if status == 200:
        log(f"key {alias}: deleted the previous key")

    status, body = request("POST", f"{base}/key/generate", token=master, body={"key_alias": alias, **settings})
    if status != 200 or not body.get("key"):
        sys.exit(f"key/generate {alias}: HTTP {status} {error_text(body)}")

    status, patched = request(
        "PATCH",
        secret_url,
        token=kube_token,
        context=kube_ctx,
        content_type="application/merge-patch+json",
        body={"data": {secret_key: base64.b64encode(body["key"].encode()).decode()}},
    )
    if status != 200:
        sys.exit(f"PATCH secret {namespace}/{secret_name}: HTTP {status} {patched.get('message', '')}")
    log(f"key {alias}: generated, wrote {namespace}/{secret_name}")


if __name__ == "__main__":
    main()
