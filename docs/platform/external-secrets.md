# External Secrets and 1Password

External Secrets (chart 2.14.0) reads app secrets from the 1Password vault
`k8s-secrets` through one ClusterSecretStore, `onepassword`
(`kubernetes/apps/external-secrets/external-secrets/store/clustersecretstore.yaml`).
It uses the 1Password SDK provider and authenticates with a service account,
whose token is created out of band ([bootstrap/README.md](../../bootstrap/README.md)).

## 1Password rate limits

1Password limits service accounts
([rate limits](https://www.1password.dev/service-accounts/rate-limits/)):

| Plan | Reads per hour, per token | Reads and writes per day, whole account |
| --- | --- | --- |
| Business | 10,000 | 50,000 |
| Teams | 1,000 | 5,000 |
| 1Password and Families | 1,000 | 1,000 |

The daily limit is shared by the whole 1Password account, so `op` use and
any other service account count too. Over a limit, 1Password answers 429,
and External Secrets logs `performing a vault operation: rate limit
exceeded`. To see the limit, what is used, and when it resets:

```sh
op service-account ratelimit <service account name>
```

### What External Secrets spends

From the provider at v2.14.0 (`providers/v1/onepasswordsdk`):

- **One `Resolve` call per `data` entry per refresh.** An ExternalSecret
  with four fields costs four reads each time it syncs.
- The SDK client is built once per store version and reused, so a sync
  needs no new login. The vault lookup (`VaultsList`) runs only when the
  client is built.
- A failed sync is retried with backoff, and each retry reads again.
- The controller counts every call:
  `externalsecret_provider_api_calls_count{provider="1Password/SDK"}`,
  labelled by call (`Resolve`, `VaultsList`) and status. It is scraped by
  the ServiceMonitor.

On 6 Nov 2026 the cluster had 25 ExternalSecrets with 53 fields, all on a
1h refresh: about 1,270 reads a day, against 1,000 a day on a 1Password or
Families account. Reads started failing at 14:05 UTC that day, and the
failed retries spent more of the limit. Every ExternalSecret has since
refreshed every **12h**: about 106 reads a day for the same 53 fields.

### Rules

- **`refreshInterval: 12h`** on every ExternalSecret. Values here change
  only when someone rotates them, so a faster refresh buys nothing.
- **Push a rotation at once** with the force-sync annotation, instead of
  waiting up to 12h:

  ```sh
  kubectl -n <namespace> annotate externalsecret <name> force-sync="$(date +%s)" --overwrite
  ```

- **Client cache: 10 minutes** on the store (`cache.ttl`, ESO marks it
  experimental). It answers repeat reads of the same field from memory:
  fields several ExternalSecrets share, such as the R2 template fields and
  a bot's `hindsight_api_key`, and the burst after a controller restart.
  Caveat: if a field was read in the last 10 minutes, a force-sync right
  after rotating it can still get the old value. Wait 10 minutes and
  force-sync again.
- **Count the reads when adding secrets.** Each new field adds 2 reads a
  day, plus one on every controller restart and every change to its
  ExternalSecret. At about 500 fields the 12h refresh alone would reach
  1,000 a day. Keep well under that, because other `op` use counts too.

## When reads fail

The target Secret keeps its last value. Running pods are unaffected, and
restarted pods get the old value. What stops:

- new and rotated values;
- Flux Kustomizations whose health checks wait for an ExternalSecret to be
  Ready. For example `litellm`, then everything that depends on it (the
  LiteLLM key provisioner, Hindsight, and the Hermes bots' `provision` and
  `app`).

It recovers by itself once the window resets. Check with:

```sh
kubectl get externalsecret -A
kubectl -n external-secrets logs deploy/external-secrets --since=10m | grep -c 'rate limit exceeded'
```
