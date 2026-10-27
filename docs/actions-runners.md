# Actions runners

Self-hosted GitHub Actions runners for private repositories that run out
of GitHub-hosted minutes. The controller and the one scale set are
namespace `actions-runner-system`. Charts are
`ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set-controller`
and `gha-runner-scale-set`, both tag `0.15.1`.

| Piece | Name | What it does |
| --- | --- | --- |
| Controller | HelmRelease `gha-runner-scale-set-controller` | Installs the scale-set CRDs and the controller. Service account `gha-rs-controller` |
| Scale set | HelmRelease `sam-tracker` | Repo `https://github.com/carpenike/sam-tracker`. `runs-on` name `sam-tracker-k8s`. `minRunners` 0, `maxRunners` 3 |
| Secret | ExternalSecret `actions-runner-controller` | GitHub App credentials from 1Password |

Runners are ephemeral. A pod takes one job and is deleted. That is the
scale-set default. There is no idle pool: `minRunners` is 0.

The scale set is its own Flux Kustomization. It depends on the controller
and on external-secrets. Nothing depends on it. A missing 1Password item
leaves that Kustomization unready and leaves the controller Ready.

## Policy

Runners execute workflow code on the home network. They are for private
repositories that have used up GitHub-hosted minutes.

Do not register a public repository. A pull request from a fork of a
public repository runs the fork's workflow, and that code would run here.
`nix-config` stays on GitHub-hosted runners for that reason. A new private
repository gets its own scale set and its own GitHub App installation.
This one is installed on `sam-tracker` only.

`sam-tracker` is a personal account repository, not an organization. The
scale set is repo-scoped. `githubConfigUrl` is
`https://github.com/carpenike/sam-tracker`.

## Container mode

The scale set does not set `containerMode`. The runner pod is
`ghcr.io/actions/actions-runner:2.338.2` and `/home/runner/run.sh`. There
is no Docker daemon in the pod.

This environment's GitHub credential cannot read
`carpenike/sam-tracker` (the API returns 404), so
`.github/workflows/tests.yml`, `deploy-functions.yml`, and
`main_ryholt-sam-appservice.yml` were not opened from here.
`main_<app>.yml` is the file Azure App Service Deployment Center writes
for a code publish, and a Functions deploy of that name publishes a
package with the Azure Functions action. Neither starts Docker.
`services:`, `docker build`, and `docker/build-push-action` need a
daemon. If `tests.yml` uses those, set `containerMode.type` to `dind` and
label this namespace `pod-security.kubernetes.io/enforce: privileged`
(and the audit and warn labels). Baseline is the cluster default, and
the namespace is unlabeled while dind is off.

Requests and limits: runner `500m` / `1Gi` up to `2` CPU / `2Gi`. The
listener is `50m` / `64Mi` up to `200m` / `256Mi`. The controller is
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
- Install App. Choose Only select repositories, and select `sam-tracker` only
- After install, the browser URL is `https://github.com/settings/installations/<installation id>`. The number at the end is the installation ID

A PAT is not used.

## 1Password

Vault `k8s-secrets`, id `h3aojtbptukuxixo5ysdco7r6u`. Item
`actions-runner-controller`. The item does not exist yet.

| 1Password field | Secret key | Value |
| --- | --- | --- |
| `github_app_id` | `github_app_id` | App ID, as digits |
| `github_app_installation_id` | `github_app_installation_id` | Installation ID, as digits |
| `github_app_private_key` | `github_app_private_key` | Entire PEM |

The ExternalSecret uses `remoteRef.key: actions-runner-controller/<field>`.
The chart is pointed at the Secret by name (`githubConfigSecret:
actions-runner-controller`) and does not create that Secret itself.

## Opting in

In `.github/workflows` on `sam-tracker`, set the job's runner:

```yaml
runs-on: sam-tracker-k8s
```

Jobs that omit it stay on GitHub-hosted runners. This repository does not
change `sam-tracker`'s workflows.
