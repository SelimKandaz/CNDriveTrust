# CloudNinjas Hardware Operations Menu Architecture

## Current navigation

```text
Boot / tty1
`-- CloudNinjas Hardware Operations
    |-- 1. Dell Server Program
    |   `-- Existing Dell options 1-4 and maintenance tools
    `-- 2. CNDriveTrust / Drive Tools
        |-- 1. Test Disk
        |-- 2. Health & Usage Summary
        |-- 3. Erase / Sanitize (read-only discovery; execution disabled)
        `-- 4. CNDriveAI (NOT INSTALLED placeholder)
```

The product selector owns only navigation. Dell workflow implementation remains
in `cngpu-dell-server-menu`; drive workflow navigation remains in
`cngpu-drive-tools-menu`. Each Drive Tools entry launches an independent module.

## Extension rules

1. Add a new capability as a separate executable with its own version, tests,
   evidence schema, and rollback unit.
2. Menus route only and must not duplicate analysis or device-command logic.
3. Read-only collection and destructive operations remain separate modules.
4. A future erase module must consume the shared boot-protection result, repeat
   target identity before mutation, require explicit confirmation, and preserve
   pre/post evidence.
5. Unsupported or unfinished execution remains explicitly disabled.
6. Drive-tool additions must not modify Dell workflow behavior.

## Components

- **Test Disk:** existing read-only full-device evidence and read verification.
- **Health & Usage Summary:** current health/usage plus explicitly labeled
  preserved performance and history-trust evidence.
- **Erase / Sanitize:** protocol-aware capability discovery is implemented.
  Destructive SAS/SATA/SCSI/NVMe execution is not implemented or enabled.
- **CNDriveAI:** optional future advisory component. Version 2.2.0 contains only
  a `NOT INSTALLED` screen and authority contract; no model/runtime is installed.

## Rollback

The pre-split live menu and systemd unit remain preserved at:

`/opt/cngpustress/backups/pre-two-product-launcher-20260924T204850Z/`
