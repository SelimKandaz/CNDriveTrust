# CNDriveTrust Architecture

## Boundary

CNDriveTrust is an isolated product selected independently from the Dell server
program. The top-level and drive menus route only; analysis and reporting live
in Python modules. All Dell firmware/server workflows remain outside its code
path.

## Module boundary

```text
drive_evidence.py                 existing full Test Disk workflow
cndrivetrust/health_cli.py        lightweight interactive summary orchestration
cndrivetrust/health.py            explainable dimensions and history rules
cndrivetrust/history.py           read-only preserved-result lookup
cndrivetrust/formatting.py        units without loss of raw precision
cndrivetrust/reports.py           terminal, JSON, HTML, manifest and hashes
cndrivetrust/vendors/samsung.py   VID-gated Samsung 0xCA decoder
```

The core works without an AI component. Future erase backends and CNDriveAI
remain separate optional modules and cannot bypass boot protection.

## Data flow

```text
Technician input
      |
      v
Boot ancestry guard ---- unresolved ----> fail closed
      |
      v
Physical disk inventory / target identity lock
      |
      v
Pre-read evidence
  |-- NVMe standard logs
  |-- smartctl
  |-- firmware/error/PEL
  |-- sanitize/blank-state semantics
  `-- Samsung 0xCA vendor evidence (VID-gated)
      |
      v
Full-capacity read to /dev/null
      |
      v
Post-read independent re-observation
      |
      v
Consistency engine
  |-- current-state health
  |-- physical-media vs retained-history continuity
  |-- elapsed-time coherence
  |-- read-counter delta
  |-- unexpected write/error/erase changes
  `-- prior-run regression/conflict checks
      |
      v
Raw + JSON + Markdown + HTML + manifest + SHA-256
      |
      `----> optional pre-mounted CIFS export
```

## Principal decisions

1. **Read-only media boundary.** Full testing reads every advertised byte but
   never formats, sanitizes, updates firmware, changes namespaces or writes a
   test pattern. Trade-off: addressability/readability is proven, but write
   reliability is not.
2. **Vendor data is additive.** Samsung page `0xCA` is collected only after VID
   `0x144D` is established. Unsupported vendors retain standard evidence rather
   than receiving fabricated zeros.
3. **No health percentage shortcut.** Final interpretation combines wear,
   erase cycles, runtime, I/O, blank state and before/after behavior.
4. **Conservative language.** The engine reports observations and continuity
   conflicts; it does not infer fraud, actor, date or chain of custody.
5. **Fail-closed target selection.** Boot ancestry is recomputed and target
   serial/size are re-established immediately before the full read.
6. **Immutable evidence bundles.** Raw vendor bytes and tool output remain
   available for independent reinterpretation if rules evolve.

## Reliability and recovery

- A missing Windows destination does not block local evidence.
- Unsupported log pages are distinct from query failures and numerical zero.
- Existing run folders are never overwritten.
- The pre-2.0.0 live deployment and menu are preserved as a hash-verified
  rollback snapshot.
- The release tar is read-only and the runtime is covered by offline tests.

## Revisit as the system grows

- Add vendor decoders only from authoritative field definitions and physical
  samples; never generalize Samsung offsets.
- Add parallel reads only after controller/backplane load and thermal behavior
  are characterized; version 2.0.0 runs selected devices sequentially.
- Add signed release metadata if CNDriveTrust is distributed beyond the current
  controlled runner.
- Add write-path qualification only as a separately authorized destructive
  profile with explicit media-destruction controls.
