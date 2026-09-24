# CNDriveAI future integration contract

CNDriveAI is an optional future offline assistant. CNDriveTrust must remain
fully operational without it. Version 2.2.0 installs no model, inference
runtime, framework, service, package, or preallocated model storage.

## Conceptual layout

```text
ai/
├── interface     authority and data contracts
├── context       normalized evidence adapters
├── retrieval     local documentation/report search
├── prompts       reviewed technician interaction templates
├── staging       proposed explanations and patches only
└── config        model-independent optional configuration

/var/lib/cndriveai/   future data root; not created by v2.2.0
```

## Permitted reads

- normalized CNDriveTrust JSON and manifests;
- raw evidence only when explicitly requested;
- local project documentation, source, runbooks and known issues;
- preserved previous reports.

## Permitted outputs

- explanations and diagnostic suggestions;
- comparisons;
- code suggestions;
- patch files written only to a future staging location.

## Prohibited authority

CNDriveAI may never select a destructive target, bypass boot protection,
execute erase/sanitize/format, modify namespaces, flash firmware, or deploy
production code automatically. Deterministic CNDriveTrust safety gates remain
authoritative and cannot be replaced by model output.

