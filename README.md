# CNDriveTrust

**Evidence-Driven SSD/NVMe Readiness & Provenance**  
Version: 2.2.0

CNDriveTrust is the isolated storage-evidence product under the top-level
CloudNinjas Hardware Operations menu. It does not import ASUS platform, BMC,
firmware, or Dell production logic.

## Operator workflow

Drive Tools Option 1 waits for explicit technician input. It asks for a PO/Batch ID,
expected condition (`NEW`, `USED`, or `UNKNOWN`), notes, target selection, and
whether to perform the default full-capacity read verification.

The physical disk backing `/`, `/boot`, and `/boot/efi` is resolved dynamically
and displayed as `BOOT / PROTECTED`. If ancestry is ambiguous, all target
selection and full reads fail closed.

Drive Tools Option 2 is the read-only **Health & Usage Summary**. It performs
lightweight current identity/SMART/NVMe collection, consumes the most recent
preserved full-test result for performance context, and separately reports
media health, endurance, error state, usage, performance, and history trust.
It writes terminal, JSON and HTML summaries without rerunning a full read.

Drive Tools Option 3 performs read-only erase/sanitize capability discovery.
It identifies NVMe, ATA, SCSI/SAS, or generic block-device paths and records
supported capability evidence. Destructive execution is disabled and no
execution backend exists in this release.

Drive Tools Option 4 is a lightweight CNDriveAI placeholder and interface
contract. No model, inference runtime, service, AI framework, or model storage
is installed by CNDriveTrust 2.2.0.

Capability-discovery bundles are stored under:

`/var/lib/harddrive-test-results/ERASE_CAPABILITY/<SERIAL>/<ERASECAP_RUN_ID>/`

They contain raw read-only query output, normalized capability JSON,
technician text/HTML, manifest, and SHA-256 checksums. No bundle is created when
only the protected boot disk is present.

## Evidence layers

Every selected NVMe receives:

1. identity, namespace, PCI, firmware-slot, SMART, error-log and optional PEL collection;
2. `smartctl -x` text and JSON evidence;
3. NVMe sanitize-status/Global-Data-Erased observation;
4. Samsung PM9A3 vendor Extended SMART page `0xCA` when PCI VID `0x144D` is established;
5. an optional/default full-capacity read to `/dev/null`;
6. post-read SMART/error/vendor re-observation;
7. counter-delta and logical-consistency analysis.

The Samsung decoder preserves the original 512-byte page unchanged and labels
all decoded fields `VENDOR_SPECIFIC`. It extracts program/erase failures,
media wear, NAND erase-cycle minimum/average/maximum, workload timer, CRC/E2E
errors and raw NAND/user-write indicators. These fields are never assumed to
exist on another vendor.

## Logical evidence rules

CNDriveTrust distinguishes observed facts, possible explanations and what has
not been established. It never automatically reports fraud or SMART tampering.

- `LIFETIME_HISTORY_DISCONTINUITY`: physical wear/erase history exists while retained host writes are zero.
- `BLANK_STATE_VS_MEDIA_WEAR_CONFLICT`: Global Data Erased is asserted while material NAND wear remains.
- `COHERENT_NEAR_NEW_TELEMETRY`: sub-hour vendor time, zero writes, zero average erase cycles, maximum at most one, zero wear and blank state agree.
- `USED_BELOW_ONE_PERCENT_WEAR`: Percentage Used is zero but runtime/I/O shows a real lightly-used device.
- Standard/vendor wear or time-domain mismatches, counter regression, firmware change and serial/model conflicts.
- Full-read incompleteness, unexpected write/error/erase changes and read-counter delta mismatch.

`power_cycles > 0` with `power_on_hours = 0` is not suspicious by itself when
the higher-resolution vendor timer is below 60 minutes.

## Full-capacity read semantics

The verifier re-establishes target path, serial, size and boot protection immediately before invoking:

`dd if=<target> of=/dev/null bs=16M iflag=direct status=none`

No target write is issued. Success requires reading the complete advertised
capacity. Post-read counters must show no unexpected write, critical-warning,
media-error or erase-cycle change. The Data Units Read increase is compared
with `ceil(bytes / 512000)` using a small rounding/concurrency allowance.

## Results

Local immutable results remain under:

`/var/lib/harddrive-test-results/<PO>/<SERIAL>/<RUN_ID>/`

Each bundle contains raw stdout/stderr/binary pages, normalized JSON,
`reports/report.html`, `reports/report.md`, `manifest.json`, and
`checksums.sha256`.

Health Summary bundles remain under:

`/var/lib/harddrive-test-results/HEALTH_SUMMARY/<SERIAL>/<HEALTH_RUN_ID>/`

They contain live lightweight raw evidence, normalized `health-summary.json`,
technician text/HTML, manifest, and SHA-256 list.

Final states are `CONSISTENT`, `REVIEW_REQUIRED`, and `INSUFFICIENT_EVIDENCE`.
A consistent result means no contradiction or read failure was observed in the
bounded window. It is not proof of chain of custody, factory-new commercial
status, cryptographic firmware authenticity, or future reliability.

## Windows export

The optional direct-export adapter reads `/etc/harddrive-test/config.json` and
accepts only an already-mounted CIFS destination. It never stores an SMB
password. An unavailable destination produces `PENDING_EXPORT` without blocking
local evidence.

## Validation

`python3 -m unittest discover -s /opt/cngpu-drive-evidence -p 'test_*.py' -v`

With no external drives attached, `--preflight` must show the USB runner as
`BOOT / PROTECTED`. Physical release acceptance additionally requires known
near-new, used/consistent, and history-discontinuous samples.
