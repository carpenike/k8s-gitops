"""Provision one Hermes bot account on Tuwunel through the hermes-bots appservice.

Run by the Job in ../template. Standard library only. Steps:

0. Refuse unless Secret hermes-<BOT_NAME>/hermes-<BOT_NAME>-matrix carries
   this provisioner's labels, so a mistyped name never writes into some
   other Secret.
1. If that Secret already holds a token that /account/whoami accepts for the
   same user, only refresh the non-secret fields and stop.
2. Register @<MATRIX_USER> with m.login.application_service. M_USER_IN_USE
   means it already exists and is not an error. The name has to be in the
   hermes-bots appservice namespace, or Tuwunel answers M_EXCLUSIVE.
3. Log in as that user with the as_token to get a per-user access token.
   The device id is fixed per user (HERMES_<USER>), so a re-run replaces the
   token on the same device instead of adding devices, and a restored crypto
   store keeps matching it.
4. Merge-patch MATRIX_HOMESERVER (in-cluster URL), MATRIX_USER_ID,
   MATRIX_DEVICE_ID, MATRIX_ACCESS_TOKEN into the Secret. RBAC allows get and
   patch on that one Secret and nothing else.

Tokens are never printed.
"""

import base64
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

SA_DIR = "/var/run/secrets/kubernetes.io/serviceaccount"
KUBE_API = "https://kubernetes.default.svc"
LABEL_NAME = "hermes-bot-provisioner"


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


def main():
    bot = os.environ["BOT_NAME"]
    namespace = os.environ["BOT_NAMESPACE"]
    localpart = os.environ["MATRIX_USER"]
    server_name = os.environ["SERVER_NAME"]
    internal_url = os.environ["HOMESERVER_URL"].rstrip("/")
    bot_url = os.environ["BOT_HOMESERVER_URL"].rstrip("/")
    as_token = os.environ["AS_TOKEN"].strip()

    # Lowercase DNS label, so it is a valid namespace and Secret name part.
    label = r"[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?"
    if not re.fullmatch(label, bot):
        sys.exit(f"invalid BOT_NAME {bot!r}: use lowercase letters, digits, and '-'")
    if namespace != f"hermes-{bot}":
        sys.exit(f"BOT_NAMESPACE {namespace!r} is not hermes-{bot}")
    if not re.fullmatch(label, localpart):
        sys.exit(f"invalid MATRIX_USER {localpart!r}: use lowercase letters, digits, and '-'")

    user_id = f"@{localpart}:{server_name}"
    secret_name = f"hermes-{bot}-matrix"
    device_id = f"HERMES_{localpart.upper().replace('-', '_')}"

    with open(f"{SA_DIR}/token") as f:
        kube_token = f.read().strip()
    kube_ctx = ssl.create_default_context(cafile=f"{SA_DIR}/ca.crt")
    secret_url = f"{KUBE_API}/api/v1/namespaces/{namespace}/secrets/{secret_name}"

    status, secret = request("GET", secret_url, token=kube_token, context=kube_ctx)
    if status != 200:
        sys.exit(f"GET secret {namespace}/{secret_name}: HTTP {status} {secret.get('message', '')}")
    labels = (secret.get("metadata") or {}).get("labels") or {}
    if labels.get("app.kubernetes.io/name") != LABEL_NAME or labels.get("app.kubernetes.io/instance") != bot:
        sys.exit(f"refusing to write {namespace}/{secret_name}: it lacks the labels "
                 f"app.kubernetes.io/name={LABEL_NAME}, app.kubernetes.io/instance={bot}")

    def b64(value):
        return base64.b64encode(value.encode()).decode()

    def patch(fields):
        status, body = request("PATCH", secret_url, token=kube_token, context=kube_ctx,
                               content_type="application/merge-patch+json",
                               body={"data": {k: b64(v) for k, v in fields.items()}})
        if status != 200:
            sys.exit(f"PATCH secret {namespace}/{secret_name}: HTTP {status} {body.get('message', '')}")

    public = {"MATRIX_HOMESERVER": bot_url, "MATRIX_USER_ID": user_id, "MATRIX_DEVICE_ID": device_id}
    data = secret.get("data") or {}
    current = {k: base64.b64decode(data.get(k, "")).decode() for k in (*public, "MATRIX_ACCESS_TOKEN")}
    if current["MATRIX_ACCESS_TOKEN"] and current["MATRIX_USER_ID"] == user_id:
        status, whoami = request(
            "GET", f"{internal_url}/_matrix/client/v3/account/whoami", token=current["MATRIX_ACCESS_TOKEN"]
        )
        if status == 200 and whoami.get("user_id") == user_id:
            if any(current[k] != v for k, v in public.items()):
                patch(public)
                log(f"{user_id}: stored token is valid, refreshed homeserver/device fields")
            else:
                log(f"{user_id}: stored token is valid, nothing to do")
            return
        log(f"{user_id}: stored token rejected (HTTP {status}), logging in again")

    status, body = request(
        "POST",
        f"{internal_url}/_matrix/client/v3/register",
        token=as_token,
        body={
            "type": "m.login.application_service",
            "username": localpart,
            "inhibit_login": True,
        },
    )
    if status == 200:
        log(f"{user_id}: registered")
    elif body.get("errcode") == "M_USER_IN_USE":
        log(f"{user_id}: already registered")
    else:
        sys.exit(f"register {user_id}: HTTP {status} {body.get('errcode')} {body.get('error')}")

    status, body = request(
        "POST",
        f"{internal_url}/_matrix/client/v3/login",
        token=as_token,
        body={
            "type": "m.login.application_service",
            "identifier": {"type": "m.id.user", "user": localpart},
            "device_id": device_id,
            "initial_device_display_name": f"{localpart} (provisioned)",
        },
    )
    if status != 200 or "access_token" not in body:
        sys.exit(f"login {user_id}: HTTP {status} {body.get('errcode')} {body.get('error')}")
    if body.get("user_id") != user_id:
        sys.exit(f"login returned {body.get('user_id')!r}, expected {user_id!r}")

    patch({**public, "MATRIX_ACCESS_TOKEN": body["access_token"]})
    log(f"{user_id}: wrote {namespace}/{secret_name}")


if __name__ == "__main__":
    main()
