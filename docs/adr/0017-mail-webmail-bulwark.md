---
status: proposed
date: 2026-11-11
decision-makers: Ryan Holt
---

# Bulwark as the webmail for Stalwart

## Context and Problem Statement

Stalwart v1.1.0 has no webmail. Its WebUI at `/admin` and `/account`
covers administration and account self-service only. The household signs
in with Pocket ID (ADR 0015) and should be able to read mail in a browser
without setting up a mail app or an app password.

## Decision Drivers

- The same Pocket ID sign-in as the WebUI, with no app password to make
- Mail, calendars and contacts, which Stalwart already serves
- Little to keep: no database, no volume, one container
- Internal only, like the WebUI (`envoy-internal`)

## Considered Options

- Bulwark, a JMAP webmail built for Stalwart, in its own pod
- Roundcube over IMAP and SMTP submission
- SnappyMail over IMAP and SMTP submission
- A webmail bundle served by Stalwart itself as an Application

## Decision Outcome

Chosen option: "Bulwark", because it speaks JMAP, signs in with an
external OIDC provider and sends the RFC 8707 `resource` that Pocket ID
needs to issue a token Stalwart accepts, and keeps nothing on disk.

- Deployment `bulwark` in namespace `mail`, image
  `ghcr.io/bulwarkmail/webmail`, one replica, route
  `webmail.holthome.net` on `envoy-internal` with label
  `gateway.holthome.net/auth: native`
- Pocket ID gets a second public client, `bulwark`, with PKCE, gated to
  `family`, and the existing API `Stalwart Mail`
  (`https://mail.holthome.net`) is granted to it
- Bulwark asks for the four service scopes
  (`urn:ietf:params:oauth:scope:mail`, `contacts`, `calendars`, `files`).
  Stalwart refuses a token from a client other than its WebUI unless it
  carries one of them, and ignores its own scopes on tokens from an
  outside provider. Pocket ID grants them as permissions of the
  `Stalwart Mail` API. Account security (app passwords) stays in the
  WebUI
- The browser calls Stalwart's JMAP API on `mail.holthome.net` directly,
  from another origin, so Stalwart's `usePermissiveCors` is on
- Settings sync and Bulwark's admin dashboard stay off. Each browser keeps
  its own settings

### Consequences

- Good, because webmail uses the same Pocket ID sign-in as everything
  else, and nobody makes an app password for it
- Good, because nothing is backed up or restored: the pod holds no state
  but a session secret in 1Password
- Bad, because `usePermissiveCors` sends `Access-Control-Allow-Origin: *`
  on every Stalwart HTTP response. It opens no endpoint, since every call
  still needs credentials, and `*` stops browsers from sending cookies or
  cached Basic credentials with a cross-origin call. A page on any origin
  can still call the API with a token it already holds
- Bad, because Bulwark is young (first release March 2026) and releases
  often. Renovate pins the digest, so updates arrive as reviewed changes
- Bad, because the token is a bearer token in the browser, so a script
  injected into Bulwark could read and send mail as the user
- Neutral, because Bulwark is AGPL-3.0. Running it unmodified for the
  household adds no obligation

## Pros and Cons of the Options

### Bulwark

- Good, because of JMAP, calendars and contacts, and Pocket ID sign-in
  with `resource`
- Bad, because it is new, and it needs Stalwart's permissive CORS

### Roundcube

- Good, because it is mature and widely used with Stalwart
- Bad, because IMAP and SMTP from a server-side client need either an app
  password per user or OAuth configured through a plugin
- Bad, because it needs its own database

### SnappyMail

- Good, because it is lighter than Roundcube
- Bad, because of the same IMAP sign-in problem as Roundcube

### Stalwart Application bundle

- Good, because it would be same-origin with JMAP and need no CORS
- Bad, because Stalwart downloads the bundle unverified, and Bulwark is a
  Next.js server, not a static bundle
