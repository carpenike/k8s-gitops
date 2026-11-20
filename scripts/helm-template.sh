#!/usr/bin/env bash
# Render every Flux HelmRelease's spec.values against its chart with
# `helm template`, so values that break a chart's values.schema.json (or its
# templates) fail here instead of at `helm upgrade` in the cluster.
# No cluster, no secrets; charts are pulled anonymously from public registries.
#
# Each Flux Kustomization in kubernetes/apps/**/ks.yaml is built the way
# kustomize-controller builds it: `kustomize build` of spec.path, then, when
# spec.postBuild is set, `flux envsubst --strict` with the values of
# cluster-secrets (kubernetes/components/sops/cluster-secrets.yaml, plaintext
# by design) overlaid by spec.postBuild.substitute. Values that are sops
# ciphertext become the string "placeholder". --strict fails on a ${VAR} that
# no source defines; in the cluster Flux would silently replace it with "".
# Kustomizations without postBuild are not substituted, which keeps literal
# ${VAR} strings that apps expand at runtime.
#
# Flux Kustomizations can also come from a Kustomize Component: a directory
# under kubernetes/apps whose kustomization.yaml uses a component other than
# sops (for example kubernetes/apps/hermes/<bot> with
# kubernetes/components/hermes-bot). That directory is built, and the Flux
# Kustomizations in the result are handled like ks.yaml entries. There,
# substituteFrom ConfigMap/<name> resolves from the ConfigMap of that name in
# the same build.
#
# Chart sources, looked up by name in the same build:
#   spec.chartRef OCIRepository   ref.tag or ref.digest (ref.semver is skipped)
#   spec.chart.spec HelmRepository  default or oci type
# Anything else is skipped with a message. spec.valuesFrom is not resolved.
#
# Charts are cached by url and ref in HELM_TEMPLATE_CACHE.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

CACHE="${HELM_TEMPLATE_CACHE:-${XDG_CACHE_HOME:-${HOME}/.cache}/k8s-gitops/charts}"
CLUSTER_SECRETS="kubernetes/components/sops/cluster-secrets.yaml"
KUBE_VERSION="$(yq -N '.kubernetesVersion' talos/topf.yaml)"

want_helm="$(yq -p toml -o yaml '.tools.helm' mise.toml)"
have_helm="$(helm version --template '{{ .Version }}')"
if [[ "${have_helm}" != "v${want_helm}" ]]; then
  echo "warning: helm ${have_helm} found, mise.toml pins ${want_helm}" >&2
fi

work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT
mkdir -p "${CACHE}"

# Keep the workstation's helm repositories and registry logins out of it.
export HELM_CONFIG_HOME="${work}/helm/config"
export HELM_CACHE_HOME="${work}/helm/cache"
export HELM_DATA_HOME="${work}/helm/data"

# KEY=value lines from cluster-secrets, the only substituteFrom source in use.
mapfile -t secret_vars < <(
  yq -N '(.stringData // {} | to_entries | .[] | .key + "=" + .value),
      (.data // {} | to_entries | .[] | .key + "=" + (.value | @base64d))' \
    "${CLUSTER_SECRETS}" |
    sed -E 's/^([^=]+)=ENC\[.*$/\1=placeholder/'
)

# Print the cached chart directory for a pull reference, pulling it first.
# $1 is the cache key, the rest are `helm pull` arguments.
chart_dir() {
  local key="$1" dir tmp
  shift
  dir="${CACHE}/$(printf '%s' "${key}" | tr -c 'A-Za-z0-9._-' '_')"
  if [[ ! -f "${dir}/Chart.yaml" ]]; then
    tmp="$(mktemp -d "${work}/pull.XXXXXX")"
    helm pull "$@" --untar --untardir "${tmp}" >&2 || return 1
    rm -rf "${dir}"
    mv "${tmp}"/*/ "${dir}" || return 1
  fi
  printf '%s\n' "${dir}"
}

status=0
rendered=0
skipped=0

# Flux Kustomization sources: every ks.yaml, then the build of every
# directory that uses a non-sops component.
ks_sources=()
while IFS= read -r -d '' f; do
  ks_sources+=("${f}")
done < <(find kubernetes/apps -type f -name ks.yaml -print0 | sort -z)
mkdir -p "${work}/components"
while IFS= read -r -d '' f; do
  yq -N -e '.components // [] | .[] | select(test("components/") and (test("components/sops$") | not))' \
    "${f}" >/dev/null 2>&1 || continue
  dir="$(dirname "${f}")"
  out="${work}/components/$(printf '%s' "${dir}" | tr '/' '_').yaml"
  if ! kustomize build "${dir}" --load-restrictor LoadRestrictionsNone >"${out}"; then
    echo "${dir}: kustomize build failed" >&2
    status=1
    continue
  fi
  ks_sources+=("${out}")
done < <(find kubernetes/apps -type f -name kustomization.yaml -print0 | sort -z)

for ks_file in "${ks_sources[@]}"; do
  ks_label="${ks_file}"
  if [[ "${ks_file}" == "${work}/components/"* ]]; then
    ks_label="$(basename "${ks_file}" .yaml | tr '_' '/') (built)"
  fi
  while IFS=$'\t' read -r ks_name ks_path ks_target has_post; do
    # yq prints an empty row for each non-matching document in a build.
    [[ -n "${ks_name}" ]] || continue
    ks_path="${ks_path#./}"
    label="${ks_label} (${ks_name})"
    if [[ ! -f "${ks_path}/kustomization.yaml" ]]; then
      echo "=== ${label}: ${ks_path} has no kustomization.yaml, skipped ==="
      continue
    fi

    built="${work}/built.yaml"
    kustomize build "${ks_path}" --load-restrictor LoadRestrictionsNone >"${built}"
    if ! yq -N -e 'select(.kind == "HelmRelease")' "${built}" >/dev/null 2>&1; then
      continue
    fi

    if [[ "${has_post}" == "true" ]]; then
      vars=()
      while IFS= read -r ref; do
        case "${ref}" in
          Secret/cluster-secrets/*) vars+=("${secret_vars[@]}") ;;
          ConfigMap/*)
            cm="${ref#ConfigMap/}"
            cm="${cm%/*}"
            mapfile -t cm_vars < <(yq -N "select(.kind == \"ConfigMap\" and .metadata.name == \"${cm}\")
              | .data // {} | to_entries | .[] | .key + \"=\" + (.value | tostring)" "${ks_file}")
            if [[ ${#cm_vars[@]} -eq 0 ]]; then
              echo "${label}: substituteFrom ConfigMap ${cm} is not in the same build" >&2
              status=1
              continue 2
            fi
            vars+=("${cm_vars[@]}")
            ;;
          */true) ;;
          *)
            echo "${label}: substituteFrom ${ref%/*} is not supported here" >&2
            status=1
            continue 2
            ;;
        esac
      done < <(yq -N "select(.kind == \"Kustomization\" and .metadata.name == \"${ks_name}\")
        | .spec.postBuild.substituteFrom // [] | .[]
        | .kind + \"/\" + .name + \"/\" + (.optional // false | tostring)" "${ks_file}")
      mapfile -t inline < <(yq -N "select(.kind == \"Kustomization\" and .metadata.name == \"${ks_name}\")
        | .spec.postBuild.substitute // {} | to_entries | .[]
        | .key + \"=\" + (.value | tostring)" "${ks_file}")
      vars+=("${inline[@]}")
      if ! env -i PATH="${PATH}" HOME="${HOME}" "${vars[@]}" \
        flux envsubst --strict <"${built}" >"${built}.sub"; then
        echo "${label}: postBuild substitution failed" >&2
        status=1
        continue
      fi
      mv "${built}.sub" "${built}"
    fi

    while IFS= read -r hr; do
      sel="select(.kind == \"HelmRelease\" and .metadata.name == \"${hr}\")"
      ns="$(yq -N "${sel} | .spec.targetNamespace // \"${ks_target}\"" "${built}")"
      [[ -n "${ns}" ]] || ns="$(yq -N "${sel} | .metadata.namespace // \"default\"" "${built}")"
      release="$(yq -N "${sel} | .spec.releaseName // ((.spec.targetNamespace | select(.) | . + \"-\") // \"\") + .metadata.name" "${built}")"
      ref_kind="$(yq -N "${sel} | .spec.chartRef.kind // (\"chart:\" + (.spec.chart.spec.sourceRef.kind // \"none\"))" "${built}")"
      hr_label="${ks_path} HelmRelease/${hr}"

      case "${ref_kind}" in
        OCIRepository)
          src="$(yq -N "${sel} | .spec.chartRef.name" "${built}")"
          osel="select(.kind == \"OCIRepository\" and .metadata.name == \"${src}\")"
          url="$(yq -N "${osel} | .spec.url" "${built}")"
          tag="$(yq -N "${osel} | .spec.ref.tag // \"\"" "${built}")"
          digest="$(yq -N "${osel} | .spec.ref.digest // \"\"" "${built}")"
          if [[ -z "${url}" ]]; then
            echo "${hr_label}: OCIRepository ${src} is not in the same build" >&2
            status=1
            continue
          elif [[ -n "${digest}" ]]; then
            pull=("${url}@${digest}" "${url}@${digest}")
          elif [[ -n "${tag}" ]]; then
            pull=("${url}:${tag}" "${url}" --version "${tag}")
          else
            echo "=== ${hr_label}: OCIRepository ${src} has no tag or digest, skipped ==="
            skipped=$((skipped + 1))
            continue
          fi
          ;;
        chart:HelmRepository)
          src="$(yq -N "${sel} | .spec.chart.spec.sourceRef.name" "${built}")"
          chart="$(yq -N "${sel} | .spec.chart.spec.chart" "${built}")"
          version="$(yq -N "${sel} | .spec.chart.spec.version // \"*\"" "${built}")"
          rsel="select(.kind == \"HelmRepository\" and .metadata.name == \"${src}\")"
          url="$(yq -N "${rsel} | .spec.url" "${built}")"
          type="$(yq -N "${rsel} | .spec.type // \"default\"" "${built}")"
          if [[ -z "${url}" ]]; then
            echo "${hr_label}: HelmRepository ${src} is not in the same build" >&2
            status=1
            continue
          elif [[ "${type}" == "oci" ]]; then
            pull=("${url}/${chart}:${version}" "${url}/${chart}" --version "${version}")
          else
            pull=("${url}#${chart}:${version}" --repo "${url}" "${chart}" --version "${version}")
          fi
          ;;
        *)
          echo "=== ${hr_label}: chart source ${ref_kind#chart:} not supported, skipped ==="
          skipped=$((skipped + 1))
          continue
          ;;
      esac

      if ! dir="$(chart_dir "${pull[@]}" </dev/null)"; then
        echo "${hr_label}: helm pull failed" >&2
        status=1
        continue
      fi
      if yq -N -e "${sel} | .spec.valuesFrom" "${built}" >/dev/null 2>&1; then
        echo "note: ${hr_label} valuesFrom is not resolved; inline values only" >&2
      fi
      yq -N "${sel} | .spec.values // {}" "${built}" >"${work}/values.yaml"

      echo "=== ${hr_label} (${ref_kind#chart:} ${url}) ==="
      if ! helm template "${release}" "${dir}" --namespace "${ns}" \
        --kube-version "${KUBE_VERSION}" -f "${work}/values.yaml" </dev/null >/dev/null; then
        echo "${hr_label}: helm template failed" >&2
        status=1
        continue
      fi
      rendered=$((rendered + 1))
    done < <(yq -N 'select(.kind == "HelmRelease") | .metadata.name' "${built}")
  done < <(yq -N 'select(.kind == "Kustomization" and .apiVersion == "kustomize.toolkit.fluxcd.io/v1")
    | [.metadata.name, .spec.path, .spec.targetNamespace // "", (.spec.postBuild != null | tostring)]
    | @tsv' "${ks_file}")
done

echo "helm template: ${rendered} rendered, ${skipped} skipped"
exit "${status}"
