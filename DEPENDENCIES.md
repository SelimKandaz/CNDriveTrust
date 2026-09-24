# Dependencies

CNDriveTrust has no third-party Python dependency. Python's standard library
implements reports, queueing, TLS transport, receiver, archives, hashing, and
tests. Hardware utilities are subprocesses; absence remains explicit as
`UNSUPPORTED`/`UNAVAILABLE`, never healthy evidence.

The supported base is Ubuntu 24.04 LTS with Python 3.12. Operational tools are
Bash, systemd, coreutils, util-linux and OpenSSH. Device collectors use nvme-cli,
smartmontools, udev, pciutils, dmidecode, jq, sg3-utils and hdparm. CIFS is
optional because v2.3.0 Central uses authenticated HTTPS.

