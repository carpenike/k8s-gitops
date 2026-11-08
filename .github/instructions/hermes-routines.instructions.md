---
description: Moving a Grok Bot routine into a Hermes bot's git-declared routines
applyTo: "kubernetes/apps/hermes/*/routines.yaml"
---

# Hermes routines from Grok

`AGENTS.md` is canonical. This file is the path-scoped supplement for
`routines.yaml` (docs/hermes.md, "Routines from git").

Ryan tries a routine in a Grok bot first, then moves it here once it is
settled. Grok Chief hands it over in three parts:

1. a public spec: key, name, cron schedule in Eastern time, end date,
   what it needs (web, browser, Outlook, task board), and prose
   instructions that say "in your notepad" for anything private;
2. a private block: senders, links, items, targets, baselines;
3. what can't move.

## 1. Check it qualifies

It qualifies only if it:

- reads and reports, and never sends, replies, buys, signs up, deletes
  or changes a system. A scheduled run refuses anything that needs
  approval, and Outlook is read-only there;
- needs only the target bot's toolsets: `web`, `browser`, an MCP server
  the bot has (Chief: `outlook`, `openproject`), or the board;
- does not hand off to another Grok bot (Coach, Steward, Deacon and the
  rest), and does not need a connector Hermes lacks (iCloud, Home
  Services, Personal Finance, the printer, Grok's email inbox).

If it fails a check, say which and stop, or move only the part that
qualifies and say what stays in Grok.

## 2. Write the entry

Add the routine under `routines:` in the bot's `routines.yaml`
(`kubernetes/apps/hermes/<bot>/routines.yaml`):

- **key:** lowercase letters, digits and `-`, at most 41 characters. It is
  also the 1Password field name.
- **schedule:** a cron expression in Eastern time. Don't set `timezone`
  unless it isn't America/New_York.
- **`until`:** `YYYY-MM-DD`, if the spec gives an end date.
- **`toolsets`:** the smallest list that works. Naming an MCP server keeps
  only that server.
- **`private: true`:** when there is a private block.
- **prompt:** in plain prose.

The prompt must not repeat what the component adds to every prompt: the
`[SILENT]` reply when nothing is new; "never send, reply, buy, sign up or
delete"; the end-date note; where the private notes are.

If the bot has no `routines.yaml` yet, add a `hermes-bot-routines`
`configMapGenerator` to its `kustomization.yaml`. With private routines,
also set `ROUTINES_PRIVATE_ENABLED=true` in its inputs.

## 3. Keep the private block out of git

The repository is public (`secrets.instructions.md`).

- **Prompt:** no names, email addresses, links, account numbers or lists
  from the private block. Public service names and the bot's own domains
  are fine.
- **Private block:** stays out of commits, pull request text and
  docs.
- **Hand it to Ryan instead:** give him a script, in the session's
  scratchpad, that adds or replaces field `<key>` on 1Password Secure Note
  `hermes-<bot>-routines` in vault `k8s-secrets`. Write the item through
  `op item edit|create --template` from a 0600 temp file, and print only
  field names and lengths. Agents can't write to 1Password here; Ryan
  runs it.

## 4. Validate and hand over

Run `bash scripts/validate.sh`, then open a draft pull request. In it,
list Ryan's steps:

1. Run the 1Password script.
2. After the merge, the bot's restart makes the routine live. Confirm it
   in the `config` log (`grep routine`).
3. Run it once: `hermes cron run <id>` in the agent's `app` container. A
   `[SILENT]` run delivers nothing.
4. After a few clean days, pause the Grok copy, or trim it to the part
   that couldn't move.
