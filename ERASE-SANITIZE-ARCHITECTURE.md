# Erase / Sanitize architecture

Version 2.2.0 implements read-only capability discovery only. It contains no
destructive execution backend.

## Current modules

```text
cndrivetrust/erase/
├── discovery.py   shared protected target and protocol routing
├── nvme.py        Identify Controller capability decoding
├── ata.py         ATA Identify security/sanitize parsing
├── scsi.py        REPORT SUPPORTED OPERATION CODES interpretation
├── reports.py     JSON/HTML/text evidence and hashes
└── cli.py         technician discovery UI; execution permanently disabled
```

The discovery layer consumes the existing CNDriveTrust boot-ancestry guard and
device labels. It does not implement a second, weaker target selector.

## Future state machine

```text
DISCOVER -> IDENTIFY -> CHECK_CAPABILITIES -> SELECT_METHOD
-> CONFIRM_TARGET -> PRE_ERASE_EVIDENCE -> EXECUTE -> MONITOR
-> VERIFY -> POST_ERASE_EVIDENCE -> REPORT
```

Only the first three read-only states exist in v2.2.0. `SELECT_METHOD` and all
later states are design placeholders.

Future backend families must remain isolated:

- HDD overwrite with verification;
- ATA Secure Erase / Enhanced Secure Erase;
- SCSI/SAS SANITIZE service actions;
- NVMe Sanitize Block Erase, Crypto Erase, or Overwrite;
- NVMe Format only where an explicitly reviewed policy considers it suitable.

Zero fill is not treated as equivalent to controller-native secure erase or
sanitize. Method selection must depend on protocol, media type, controller
visibility, supported capabilities, and an independently re-identified target.

