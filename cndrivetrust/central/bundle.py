"""Immutable run-bundle creation and validation."""

from __future__ import annotations

import hashlib
import gzip
import os
import re
import tarfile
import tempfile
from pathlib import Path


SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def create_bundle(run_dir: Path, spool_dir: Path) -> tuple[Path, str]:
    run_dir = run_dir.resolve(strict=True)
    if not run_dir.is_dir() or run_dir.is_symlink():
        raise ValueError("run directory must be a real directory")
    if not (run_dir / "manifest.json").is_file() or not (run_dir / "checksums.sha256").is_file():
        raise ValueError("run is not finalized: manifest/checksums missing")
    run_id = run_dir.name
    if not SAFE.fullmatch(run_id):
        raise ValueError("unsafe run id")
    spool_dir.mkdir(parents=True, exist_ok=True)
    final = spool_dir / f"{run_id}.tar.gz"
    fd, temporary_name = tempfile.mkstemp(prefix=f".{run_id}.", suffix=".tar.gz", dir=spool_dir)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with temporary.open("wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                for path in sorted(run_dir.rglob("*"), key=lambda item: item.relative_to(run_dir).as_posix()):
                    if path.is_symlink():
                        raise ValueError("symlinks are not accepted in evidence bundles")
                    info = archive.gettarinfo(str(path), arcname=path.relative_to(run_dir).as_posix())
                    info.uid = info.gid = 0; info.uname = info.gname = "root"
                    with path.open("rb") if path.is_file() else _null_context() as stream:
                        archive.addfile(info, stream if path.is_file() else None)
        digest = sha256_file(temporary)
        if final.exists():
            if sha256_file(final) != digest:
                raise ValueError("spooled RUN_ID already has different content")
            temporary.unlink()
        else:
            temporary.replace(final)
        return final, digest
    finally:
        temporary.unlink(missing_ok=True)


class _null_context:
    def __enter__(self): return None
    def __exit__(self, *args): return False


def safe_extract(archive_path: Path, destination: Path) -> None:
    destination = destination.resolve()
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        if not members:
            raise ValueError("empty bundle")
        for member in members:
            if member.issym() or member.islnk() or member.isdev():
                raise ValueError("links/devices are not accepted")
            target = (destination / member.name).resolve()
            if destination != target and destination not in target.parents:
                raise ValueError("bundle path escaped destination")
        archive.extractall(destination, members=members, filter="data")


def validate_checksums(run_dir: Path) -> int:
    checksum_file = run_dir / "checksums.sha256"
    if not checksum_file.is_file():
        raise ValueError("checksums.sha256 missing")
    checked = 0
    for raw in checksum_file.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        match = re.fullmatch(r"([0-9a-fA-F]{64})\s+\*?(.+)", raw)
        if not match:
            raise ValueError("malformed checksum line")
        relative = Path(match.group(2))
        target = (run_dir / relative).resolve()
        if run_dir.resolve() not in target.parents or not target.is_file():
            raise ValueError("checksum target invalid")
        if sha256_file(target) != match.group(1).lower():
            raise ValueError(f"checksum mismatch: {relative.as_posix()}")
        checked += 1
    if checked == 0:
        raise ValueError("checksum manifest is empty")
    return checked
