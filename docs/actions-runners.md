# Actions runners

Self-hosted GitHub Actions runners for private repositories that run out
of GitHub-hosted minutes. The controller and the scale sets are
namespace `actions-runner-system`. Charts are
`ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set-controller`
and `gha-runner-scale-set`, both tag `0.15.1`.

| Piece | Name | What it does |
| --- | --- | --- |
| Controller | HelmRelease `gha-runner-scale-set-controller` | Installs the scale-set CRDs and the controller. Service account `gha-rs-controller` |
| Scale set | HelmRelease `sam-tracker` | Repo `https://github.com/carpenike/sam-tracker`. `runs-on` name `sam-tracker-k8s`. `minRunners` 0, `maxRunners` 3 |
| Scale set | HelmRelease `sam-tracker-app-k8s` | Repo `https://github.com/carpenike/sam-tracker-app`. `runs-on` name `sam-tracker-app-k8s`. Same limits and mode as `sam-tracker` |
| Secret | ExternalSecret `actions-runner-controller` | One GitHub App credential, read by both scale sets |

Runners are ephemeral. A pod takes one job and is deleted. That is the
scale-set default. There is no idle pool: `minRunners` is 0.

Both scale sets are one Flux Kustomization. It depends on the controller
and on external-secrets. Nothing depends on it. A missing 1Password item
leaves that Kustomization unready and leaves the controller Ready.

The chart values that both scale sets share live in
`kubernetes/apps/actions-runner-system/gha-runner-scale-set/app/scale-set`.
Each repository is a Kustomize overlay that sets the HelmRelease name,
`githubConfigUrl`, and `runnerScaleSetName`. The shared values set
`githubConfigSecret` to `actions-runner-controller`.

## Policy

Runners execute workflow code on the home network. They are for private
repositories that have used up GitHub-hosted minutes.

Do not register a public repository. A pull request from a fork of a
public repository runs the fork's workflow, and that code would run here.
`nix-config` stays on GitHub-hosted runners for that reason. A new private
repository gets its own scale set. It uses this GitHub App when the
installation includes that repository.

These repositories are on the personal account `carpenike`, not an
organization. Each scale set is repo-scoped. Installation `175991169`
includes `sam-tracker` and `sam-tracker-app`. `githubConfigUrl` is
`https://github.com/carpenike/sam-tracker` or
`https://github.com/carpenike/sam-tracker-app`.

## Container mode

`containerMode.type` is `dind` on both scale sets. `sam-tracker`
`.github/workflows/tests.yml` starts a `postgres:17` service container,
and that needs a Docker daemon in the runner pod. `sam-tracker-app` uses
the same mode. The chart adds a privileged `docker:dind` sidecar
(on Kubernetes 1.29 and newer it is an init container with
`restartPolicy: Always`) and sets `DOCKER_HOST` on the runner. The
runner image stays `ghcr.io/actions/actions-runner:2.338.2`.

The namespace `actions-runner-system` is labeled
`pod-security.kubernetes.io/enforce: privileged`, and the same value for
audit and warn. Baseline is the cluster default. The dind sidecar is
why this namespace is privileged.

Requests and limits: runner `500m` / `1Gi` up to `2` CPU / `4Gi`. The
memory limit is `4Gi` so the runner and a Postgres service container fit.
The listener is `50m` / `64Mi` up to `200m` / `256Mi`. The controller is
`50m` / `128Mi` up to `200m` / `256Mi`.

## GitHub App

Create the app on the `carpenike` account. Settings, Developer settings,
GitHub Apps, New GitHub App.

- GitHub App name: something you will recognize, for example `holthome-arc`
- Homepage URL: `https://github.com/carpenike/sam-tracker`
- Webhook: leave Active unchecked. The scale set polls GitHub. It does not receive webhooks
- Repository permissions: Administration, Read and write. Metadata, Read-only, which GitHub selects on its own
- Where can this GitHub App be installed: Only on this account
- Create the app
- On the app page, note the App ID
- Generate a private key and download the `.pem` file. That file is the whole private key, including the `BEGIN` and `END` lines
- Install App. Choose Only select repositories, and select the private repositories that will have a scale set
- After install, the browser URL is `https://github.com/settings/installations/<installation id>`. The number at the end is the installation ID. This cluster uses installation `175991169`, which includes `sam-tracker` and `sam-tracker-app`

A PAT is not used.

## 1Password

Vault `k8s-secrets`, id `h3aojtbptukuxixo5ysdco7r6u`. Item
`actions-runner-controller`. The item is in the vault. An older 2023
duplicate was renamed, and the private key was rewrapped.

| 1Password field | Secret key | Value |
| --- | --- | --- |
| `github_app_id` | `github_app_id` | App ID, as digits |
| `github_app_installation_id` | `github_app_installation_id` | Installation ID, as digits |
| `github_app_private_key` | `github_app_private_key` | Entire PEM |

The ExternalSecret uses `remoteRef.key: actions-runner-controller/<field>`.
Both charts are pointed at the Secret by name (`githubConfigSecret:
actions-runner-controller`) and neither creates that Secret.

## Opting in

In `.github/workflows` on `sam-tracker`, set the job's runner:

```yaml
runs-on: sam-tracker-k8s
```

On `sam-tracker-app`:

```yaml
runs-on: sam-tracker-app-k8s
```

Jobs that omit it stay on GitHub-hosted runners. This repository does not
change either repository's workflows.
