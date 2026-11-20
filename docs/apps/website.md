# ryanholt.net website

A static site on the apex, `kubernetes/apps/web/ryanholt-net`. Two
replicas of `nginx-unprivileged` (uid 101, read-only root, no
capabilities) serve `index.html` and `404.html` from a ConfigMap in the
HelmRelease. Namespace `web` is Pod Security `restricted` with a
default-deny Cilium policy; the only allow is ingress from the
`envoy-external` proxies on 8080. The pods have no egress.

| Name | Route | Answer |
| --- | --- | --- |
| `ryanholt.net` | `ryanholt-net` in `web`, prefix `/` | The site |
| `ryanholt.net` | `tuwunel-well-known` in `matrix`, prefix `/.well-known/matrix/` | Matrix delegation ([matrix.md](matrix.md)) |
| `www.ryanholt.net` | `ryanholt-net-www` in `web` | 301 to `https://ryanholt.net` |

Both apex routes attach to the same `envoy-external` listener. Gateway API
sends each request to the longest matching path prefix across routes, so
the Matrix paths never reach nginx. Every route here is labeled
`gateway.holthome.net/auth: public`; a public site cannot sit behind the
Pocket ID login.

`cloudflare-dns` publishes `ryanholt.net` and `www.ryanholt.net` as
proxied CNAMEs to `external.holthome.net`. The tunnel and the
`ryanholt-net-production` certificate already cover both. The mail records
that stay on the apex are covered in [matrix.md](matrix.md#names-and-dns).

## Changing the page

Edit `configMaps.site.data` in
`kubernetes/apps/web/ryanholt-net/app/helmrelease.yaml`. Reloader rolls
the pods when the ConfigMap changes. Assets that are not text (images,
fonts) do not fit a ConfigMap well; inline SVG or `data:` URIs work for
small ones. The Content-Security-Policy in `default.conf` allows inline
styles and `data:` or same-origin images, and no scripts. Loosen it in
the same file if the page grows.

A site larger than a page or two should be its own repository built
into an image (for example a static generator whose output is copied
into `nginx-unprivileged`), pinned here by tag and digest so Renovate
moves it. The route, policy, and namespace stay as they are.

The site goes down with the cluster. The chassis is one failure domain
([architecture.md](../architecture.md)).
