# Technology stack

- Ubuntu runtime: Ubuntu 24.04.3 LTS; Python 3.12.3; Bash; systemd.
- Windows Central: Windows, Python 3.12, PowerShell startup/task scripts.
- Python dependencies: standard library only (`sqlite3`, `ssl`, `http.client`,
  `tarfile`, `hashlib`, `json`, `pathlib`, `subprocess`). No virtualenv.
- Evidence tools: `nvme-cli`, `smartmontools`, `util-linux/lsblk`, `udevadm`,
  `pciutils/lspci`, `dmidecode`, `jq`, `sha256sum`, `cifs-utils`, `sg3_utils`,
  and `hdparm`, when installed and applicable.
- Reporting: JSON, HTML, TXT/Markdown, raw evidence, manifest and SHA-256.
- Runtime: `/opt/cngpu-drive-evidence`; releases `/opt/cngpustress/release`;
  rollback `/opt/cngpustress/backups`; results `/var/lib/harddrive-test-results`;
  queue/spool `/var/lib/cndrivetrust-central`.
- Service: `cngpu-countdown-menu.service`; launcher
  `/usr/local/bin/cngpu-production-countdown-menu`.
- Central: HTTPS port 8090, separate `C:\CNDriveTrust\Central` namespace,
  SQLite index, protected bearer token, persistent retry.
- Current Windows persistence: per-user HKCU startup after login. SYSTEM
  Scheduled Task installation is supplied but requires an elevated shell.
- Safety: boot disk fail-closed; erase execution disabled; CNDriveAI not
  installed and has no mutation/deployment authority.
