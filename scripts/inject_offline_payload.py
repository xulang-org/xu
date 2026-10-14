#!/usr/bin/env python3
"""Inject full release archive payload into xu-setup executable to form a true self-contained offline installer."""
import sys
from pathlib import Path

def create_offline_installer(base_exe: Path, payload_archive: Path, output_file: Path):
    if not base_exe.is_file():
        raise FileNotFoundError(f"Base executable not found: {base_exe}")
    if not payload_archive.is_file():
        raise FileNotFoundError(f"Payload archive not found: {payload_archive}")

    exe_data = base_exe.read_bytes()
    payload_data = payload_archive.read_bytes()
    payload_len = len(payload_data)

    # Trailer format: 16 bytes ASCII decimal length + 8 bytes magic "XUPACK01" = 24 bytes
    trailer = f"{payload_len:016d}".encode("ascii") + b"XUPACK01"

    total_data = exe_data + payload_data + trailer
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_bytes(total_data)
    output_file.chmod(0o755)
    print(f"[OK] Created offline installer: {output_file} (size: {len(total_data) / (1024*1024):.2f} MB)")

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: inject_offline_payload.py <base_exe> <payload_archive> <output_file>")
        sys.exit(1)
    create_offline_installer(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
