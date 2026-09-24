# Security and safety scope

CNDriveTrust treats disk identity and boot-media exclusion as safety-critical.
The current Test Disk and Health & Usage Summary workflows are read-only.

Do not add erase, format, sanitize, firmware, namespace-management, or target
write commands to these read-only paths. Future destructive backends require a
separate authorization boundary, target re-identification, boot-disk exclusion,
explicit technician confirmation, and preserved before/after evidence.

Do not commit credentials, Windows archive secrets, production result bundles,
serial-number inventories, or customer/business identifiers.

