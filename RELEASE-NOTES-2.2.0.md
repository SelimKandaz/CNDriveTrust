# CNDriveTrust 2.2.0 release notes

## IMPLEMENTED

- Protocol-aware, read-only erase/sanitize capability discovery.
- NVMe Identify Controller capability decoding and sanitize-status observation.
- ATA Identify security, frozen-state and sanitize-feature parsing.
- SCSI/SAS REPORT SUPPORTED OPERATION CODES inspection.
- Generic-block/HDD future-overwrite classification without execution.
- JSON, HTML, terminal, raw evidence, manifest and SHA-256 capability reports.
- CNDriveAI optional interface and authority contract.
- Drive Tools entries for Erase/Sanitize discovery and CNDriveAI placeholder.
- Rotational-media inventory field using `lsblk ROTA`.

## TESTED

- 48 offline regression tests including all 32 tests from 2.1.0.
- Boot ancestry and fail-closed protection.
- NVMe, ATA, SCSI and generic protocol classification fixtures.
- Query-failure versus unsupported/unknown semantics.
- Capability report parsing and hashes.
- Absence of destructive command invocation from discovery and menus.
- Dell/top-level/Drive Tools routing and back-navigation contracts.
- Live no-target preflight on the protected production boot SSD.

## PLACEHOLDER

- CNDriveAI technician screen and lightweight data/authority contract.
- Future `/var/lib/cndriveai/` data root is documented but not created.
- Future erase state machine after `CHECK_CAPABILITIES`.

## DISABLED

- Erase, sanitize, format, namespace management, ATA security-state changes,
  overwrite and verification execution.

## FUTURE

- Explicitly authorized destructive backends with independent target confirmation.
- Physical capability discovery against representative NVMe, SATA and SAS media.
- Optional offline CNDriveAI implementation in a separate release.

## Physical acceptance status

`PHYSICAL_ACCEPTANCE_PARTIAL`: on 2026-09-24 the live runner exposed only its
protected `/dev/sda` boot media. No non-boot target was available, so physical
Health Summary and capability-discovery artifact generation remain pending.

