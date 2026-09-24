# CloudNinjas Hardware Operations Menu Architecture

## Current navigation

```text
Boot / tty1
└── CloudNinjas Hardware Operations
    ├── 1. Dell Server Program
    │   └── Existing Dell options 1-4 and maintenance tools
    └── 2. CNDriveTrust / Drive Tools
        ├── 1. Test Disk -> CNDriveTrust 2.0.0
        ├── 2. Health Score -> reserved, no command
        └── 3. Erase / Secure Erase -> reserved, no command
```

The product selector owns only navigation. Dell workflow implementation remains
in `cngpu-dell-server-menu`; drive workflow navigation remains in
`cngpu-drive-tools-menu`; the existing evidence collector remains independently
callable as `cngpu-drive-evidence-test`.

## Extension rules

1. Add a new drive capability as a separate executable, with its own version,
   tests, evidence schema, and rollback unit.
2. The menu entry may launch that executable but must not duplicate its logic.
3. Read-only collection and destructive operations must remain separate modules.
4. Any erase module must require target re-identification, boot-disk exclusion,
   explicit technician confirmation, and a pre/post evidence record.
5. Unsupported or unfinished entries must remain explicit `NOT_IMPLEMENTED`
   placeholders and must execute no device command.
6. Dell workflow changes are out of scope for drive-tool additions.

## Planned modules

- **Health Score:** human-readable identity, capacity, interface/speed, SMART or
  NVMe health, power-on time, host reads/writes, NAND writes where available,
  erase-cycle evidence, unsafe shutdowns, temperature, error logs, semantic
  contradictions, and evidence confidence. It must expose raw facts alongside
  any interpretation; it must not reduce every device to one opaque percentage.
- **Erase / Secure Erase:** separate SAS/SATA overwrite support and later native
  NVMe sanitize/format workflows. No destructive implementation is enabled yet.
- **Optional offline assistant:** a separately packaged, read-only advisory
  component consuming normalized evidence and project documentation. It must not
  select erase targets, bypass safety gates, or deploy its own code changes.

## Rollback

The pre-split live menu and systemd unit are preserved at:

`/opt/cngpustress/backups/pre-two-product-launcher-20260924T204850Z/`
