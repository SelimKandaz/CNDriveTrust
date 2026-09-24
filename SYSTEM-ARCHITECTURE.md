# CNDriveTrust system architecture

## Network policy

- Host network: **ENABLED**
- CNDriveTrust LAN access: **ENABLED**
- Central access: **ENABLED**
- Future CNDriveAI Internet/LAN access: **DENIED BY DEFAULT**

```text
CloudNinjas Hardware Operations
|
+-- Dell Server Program (unchanged)
|
+-- CNDriveTrust
    +-- Test Disk
    +-- Health Summary
    +-- Erase Capability Discovery [read-only]
    +-- CNDriveAI [placeholder, NOT INSTALLED]
    +-- Central Sync
        +-- authoritative local finalized run
        +-- persistent SQLite queue + immutable tar.gz spool
        +-- authenticated TLS PUT
            v
        Windows CNDriveTrust Central (separate namespace/service)
        +-- incoming temporary file
        +-- SHA-256 + internal checksums verification
        +-- atomic publish
        +-- serial/run/batch SQLite index
```

The test result and delivery state are independent. A network failure leaves the
run locally successful and moves only Central state to `SYNC_PENDING` or
`SYNC_FAILED_RETRYABLE`.

CNDriveTrust reuses the proven CNServerOps architecture—not ASUS schemas—of
local-first evidence, SQLite store-and-forward, TLS/Bearer authentication,
streaming upload, SHA-256 verification, temporary intake, atomic finalization,
idempotent retries, and conflict preservation. ASUS BMC, firmware, reports,
semantics, and storage trees are not imported.

Central uses `PUT /v1/runs/{kind}/{serial}/{run_id}/{bundle_sha256}` with an
`X-CNDriveTrust-Batch` header. Tokens and TLS material live outside Git.

