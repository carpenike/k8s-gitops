---
status: proposed
date: 2026-11-11
decision-makers: Ryan Holt
---

# Stalwart accounts from Pocket ID

## Context and Problem Statement

Every app in this cluster that can sign people in with OIDC does so with
Pocket ID (`id.holthome.net`, on Forge), and its route is labelled
`native` (`docs/gateway-auth.md`). Stalwart's route is already `native`,
but its accounts would otherwise live in Stalwart's internal directory,
with their own passwords.

Stalwart can delegate a domain's accounts to an OpenID Connect directory.
It then acts only as a resource server: it validates the provider's
tokens and maps them to accounts. Stalwart's documentation names three
consequences that decide this:

- OIDC has no way to look up an address without its owner's token, so an
  account exists only after its first sign-in. Mail for an account that
  has never signed in is rejected
- Mail apps that support OAuth register with and get tokens from the
  provider directly. That needs the provider to implement the OAuth
  profile for open public clients; without it Stalwart advertises
  password authentication only and logs a warning, and apps such as Apple
  Mail cannot use OAuth
- Stalwart does not move accounts when the directory changes, so this is
  decided before the first account is created

## Decision Drivers

- One login for people, with passkeys, as for every other app
- Mail clients on phones and laptops must keep working
- Mail for a new address must be accepted from the start
- A way in when Pocket ID or Forge is down

## Considered Options

- An OIDC directory on Pocket ID for the mail domains
- Stalwart's internal directory, with Stalwart's own two-factor login

## Decision Outcome

Chosen option: "An OIDC directory on Pocket ID", because the WebUI, JMAP
and DAV then use the same sign-in as everything else, and the drawbacks
have workarounds that fit a household.

- Pocket ID gets a public client for the WebUI, with PKCE. It has no
  secret, so nothing is added to 1Password or this repo. The WebUI
  Application's `oauthClientId` is that client's id, and the directory's
  `acceptedAudiences` lists it. Pocket ID also needs an API whose
  resource is the public URL, granted to the client, because the WebUI
  sends that URL as the `resource` parameter
- The directory uses issuer `https://id.holthome.net`, `claimUsername`
  `preferred_username`, the mail domain as `usernameDomain`, and
  `claimGroups` `groups`
- Accounts are created in advance in the WebUI, so each address receives
  mail before its owner first signs in. The same addresses go on the edge
  relay's recipient list (ADR 0014)
- Mail clients use app passwords, created by each user in the WebUI after
  they sign in with Pocket ID
- `STALWART_RECOVERY_ADMIN` stays set. It is the administrator login when
  Forge or Pocket ID is down
- The network policy allows 443 to `id.${SECRET_DOMAIN}` by name, as
  Grafana's does

### Consequences

- Good, because people sign in to mail with the same passkey as every
  other app, and a user disabled in Pocket ID can no longer sign in
- Good, because no client secret has to be stored or rotated
- Bad, because a user disabled in Pocket ID keeps receiving mail until an
  administrator suspends the account. Stalwart never suspends accounts on
  its own
- Bad, because native mail clients need app passwords, which bypass
  Pocket ID's passkeys. Each one can be limited by address and expiry
- Bad, because WebUI sign-in depends on Forge. Mail delivery and app
  passwords do not
- Bad, because Stalwart's own two-factor login is not available for these
  accounts; the second factor is Pocket ID's

## Pros and Cons of the Options

### OIDC directory on Pocket ID

- Good, because of single sign-on and passkeys
- Bad, because accounts must be created in advance and mail clients need
  app passwords

### Internal directory

- Good, because accounts can receive mail as soon as they exist, and
  Stalwart offers its own two-factor login
- Bad, because it is a second password for every person, outside Pocket
  ID
