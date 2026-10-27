# Talos

`topf` (postfinance/topf) renders machine config from `topf.yaml` plus the
patches in `all/` and `control-plane/`. Files ending in `.tpl` still contain
topf Go templates; topf renders those per node.

This branch does not run `topf secrets` or `topf apply`. Generating a secrets
bundle writes a real Talos secret set, and applying it would touch hardware.
`secretsPath` points at `secrets.sops.yaml`, which is gitignored until an age
key exists and the bundle is encrypted.

The Image Factory schematic must include `siderolabs/nut-client`. The
`schematicId` in `topf.yaml` is 64 zeros on purpose. Build the schematic,
then replace the id on every node. Secure Boot and disk encryption stay off
until those hardware checks are decided.

See `docs/placeholders.md` for every value that has to change first.
