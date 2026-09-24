# CNDriveTrust module interfaces

## Normalized values

The existing `drive_evidence.normalize_device()` contract remains the shared
input. Each field is a record containing `value`, `status`, `source`, `time`,
and optional `unit`. Numerical zero is never converted to unavailable.

## Health analysis

`cndrivetrust.health.build_summary(current, last_result, run_id, observed_utc)`
is pure: it executes no command and writes no file. It returns schema 2.1 with
separate `media_health`, `endurance`, `error_state`, `usage`, `performance`,
and `history_trust` dimensions.

## Vendor boundary

`cndrivetrust.vendors.samsung.parse_extended_smart(record)` accepts the raw
command record and returns decoded values plus offsets. Callers must establish
Samsung PCI VID `0x144D` before collecting or interpreting page `0xCA`.

## Reporting

`cndrivetrust.reports.write_bundle()` produces raw, normalized JSON, terminal
text, HTML, manifest and checksums. Presentation code does not determine a
health verdict.

## Future modules

Erase and sanitize implementations must be independent backends. They may not
share a command path with read-only Health Summary. CNDriveAI may consume
normalized JSON but may never choose a destructive target or invoke firmware,
erase, sanitize, or production deployment actions.
