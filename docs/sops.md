# SOPS and the YubiKey

Personal access to encrypted files uses the same OpenPGP key v1 used.
`archive/talos-v1:.sops.yaml` names it `user_ryan` and stores only the
fingerprint:

```yaml
keys:
  - &user_ryan DA8002060402EC39B195451D5CED80362B5A4EF2
```

That fingerprint is public. The private key is on the YubiKey. Decryption
goes through `gpg-agent` and the card; this repo does not contain a copy
of the key, and it should not gain one.

v1 put that PGP key and a cluster age recipient in one SOPS `key_group`.
Inside a group, any one key can decrypt. The age key let Flux read the
files without the YubiKey. The PGP key let Ryan read them without the age
identity. This branch keeps that shape. The age line is not filled in yet:
the v1 age recipient is not reused, and a new one has not been generated.

## What you do on a workstation

The YubiKey has to be present, and `gpg` has to see it (`gpg --card-status`).
Then:

```sh
sops --encrypt --in-place path/to/file.sops.yaml
sops --decrypt path/to/file.sops.yaml
```

`talos/*.sops.yaml` is encrypted as a whole file. Other `*.sops.yaml` files
encrypt only `data` and `stringData`, which is the v1 rule for Kubernetes
Secrets. `.sops.yaml` at the repo root is the creation rules file. It is
not itself encrypted.

## What the cluster gets later

Flux still needs an age identity. Generate that on a workstation, keep
`age.key` out of git, and add the public recipient next to the fingerprint:

```yaml
key_groups:
  - pgp:
      - *user_ryan
    age:
      - age1... # new recipient, not the one in the archived tree
```

Re-encrypt any existing `*.sops.yaml` after that edit so both keys wrap the
data key. The cluster secret is the one in `bootstrap/README.md`
(`sops-age` in `flux-system`, key `age.agekey`). App credentials stay in
1Password. SOPS is for the bootstrap files Flux must read before External
Secrets is up, and for the Talos secrets bundle.
