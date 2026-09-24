# CNDriveTrust 2.3.0 release notes

Adds offline-first Central delivery without coupling test disposition to
network availability. Finalized bundles are spooled locally, uploaded over
authenticated TLS, verified by SHA-256 and internal checksums, and atomically
published to an isolated Windows CNDriveTrust archive. Retries are idempotent;
different bytes under the same run ID are preserved as a conflict.

Adds Drive Tools option 5 for Central status/retry and documents that host LAN
connectivity remains enabled while a future CNDriveAI process will be isolated.
No AI runtime and no destructive erase backend are included.

