#!/usr/bin/env python3
"""
RFL_DB.dat System-ID Converter + Mii Plaza Sorter
=================================================

Purpose
-------
Safely convert the System ID of every populated Mii in a Wii RFL_DB.dat
database to match a target Wii, and optionally reorder the Miis in the
100-slot Mii Plaza.

The script:
  * asks for an input RFL_DB.dat
  * asks for the target Wii MAC address
  * if the MAC is unknown, asks for the 4-byte Mii System/Console ID instead
  * shows the current Mii Plaza order
  * optionally lets the user assign every Mii a new position
  * changes ONLY each populated Mii's 4-byte System ID
  * moves complete 0x4A-byte Mii records when sorting
  * recalculates the RFL_DB.dat CRC
  * writes generated files beside the Python script; the original is never modified

No third-party Python packages are required.

Notes
-----
Wii Mii record structure:
    Mii ID:    record + 0x18, 4 bytes
    System ID: record + 0x1C, 4 bytes
    Record:    0x4A bytes

The Mii System ID is derived from a Wii MAC address:
    byte 0 = Checksum8(first 3 MAC bytes)
    bytes 1-3 = last 3 MAC bytes

For Nintendo OUI 00:17:AB, the checksum byte is C2.
For other OUIs, the high bit of the checksum byte is cleared.

Examples:
    MAC 00:17:AB:0A:84:BB -> System ID C20A84BB
    MAC 00:22:D7:00:9A:BC -> System ID 79009ABC

Always keep a backup of important Wii NAND files.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional


# ---------------------------------------------------------------------------
# Script paths
# ---------------------------------------------------------------------------

# All generated files live beside this Python script, regardless of where
# the selected input RFL_DB.dat came from.
SCRIPT_DIR = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# RFL_DB.dat layout used by the Wii Mii Plaza
# ---------------------------------------------------------------------------

RFL_SIGNATURE = b"RNOD"

MII_PLAZA_BASE = 0x0004
MII_RECORD_SIZE = 0x004A
MII_PLAZA_SLOT_COUNT = 100

MII_NAME_OFFSET = 0x02
MII_NAME_LENGTH_BYTES = 20

MII_ID_OFFSET = 0x18
SYSTEM_ID_OFFSET = 0x1C
CREATOR_NAME_OFFSET = 0x36
CREATOR_NAME_LENGTH_BYTES = 20

# Verified against real Wii/Dolphin RFL_DB.dat files.
RFL_CRC_OFFSET = 0x1F1DE


# ---------------------------------------------------------------------------
# Small UI helpers
# ---------------------------------------------------------------------------

class Color:
    ENABLED = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None

    BOLD = "\033[1m"
    CYAN = "\033[36m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    @classmethod
    def wrap(cls, text: str, code: str) -> str:
        if not cls.ENABLED:
            return text
        return f"{code}{text}{cls.RESET}"


def heading(text: str) -> None:
    print()
    print(Color.wrap("=" * 78, Color.CYAN))
    print(Color.wrap(text, Color.BOLD + Color.CYAN))
    print(Color.wrap("=" * 78, Color.CYAN))


def info(text: str) -> None:
    print(f"{Color.wrap('[i]', Color.CYAN)} {text}")


def ok(text: str) -> None:
    print(f"{Color.wrap('[+]', Color.GREEN)} {text}")


def warn(text: str) -> None:
    print(f"{Color.wrap('[!]', Color.YELLOW)} {text}")


def error(text: str) -> None:
    print(f"{Color.wrap('[X]', Color.RED)} {text}")


def yes_no(prompt: str, default: bool = False) -> bool:
    suffix = " [Y/n]: " if default else " [y/N]: "
    while True:
        answer = input(prompt + suffix).strip().lower()
        if not answer:
            return default
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("Please enter y or n.")


# ---------------------------------------------------------------------------
# Mii records
# ---------------------------------------------------------------------------

@dataclass
class MiiRecord:
    original_slot: int
    name: str
    creator_name: str
    mii_id: bytes
    system_id: bytes
    raw: bytes

    @property
    def mii_id_hex(self) -> str:
        return self.mii_id.hex().upper()

    @property
    def system_id_hex(self) -> str:
        return self.system_id.hex().upper()


def decode_utf16be(raw: bytes) -> str:
    return raw.decode("utf-16-be", errors="replace").split("\x00", 1)[0]


def read_mii_records(data: bytes) -> List[MiiRecord]:
    records: List[MiiRecord] = []

    for slot in range(MII_PLAZA_SLOT_COUNT):
        start = MII_PLAZA_BASE + slot * MII_RECORD_SIZE
        raw = data[start:start + MII_RECORD_SIZE]

        if len(raw) != MII_RECORD_SIZE:
            raise ValueError(f"File ended inside Mii Plaza slot {slot}.")

        # An empty Plaza slot is zero-filled.
        if not any(raw):
            continue

        name = decode_utf16be(
            raw[MII_NAME_OFFSET:MII_NAME_OFFSET + MII_NAME_LENGTH_BYTES]
        )
        creator_name = decode_utf16be(
            raw[
                CREATOR_NAME_OFFSET:
                CREATOR_NAME_OFFSET + CREATOR_NAME_LENGTH_BYTES
            ]
        )

        records.append(
            MiiRecord(
                original_slot=slot,
                name=name,
                creator_name=creator_name,
                mii_id=bytes(raw[MII_ID_OFFSET:MII_ID_OFFSET + 4]),
                system_id=bytes(raw[SYSTEM_ID_OFFSET:SYSTEM_ID_OFFSET + 4]),
                raw=bytes(raw),
            )
        )

    return records


def display_miis(records: List[MiiRecord], title: str) -> None:
    heading(title)

    if not records:
        print("No populated Mii Plaza slots found.")
        return

    print(
        f"{'Pos':>3}  {'Name':<18}  {'Mii ID':<8}  "
        f"{'System ID':<8}  {'Creator':<18}"
    )
    print("-" * 78)

    for position, mii in enumerate(records):
        creator = mii.creator_name if mii.creator_name else "-"
        print(
            f"{position:>3}  "
            f"{mii.name[:18]:<18}  "
            f"{mii.mii_id_hex:<8}  "
            f"{mii.system_id_hex:<8}  "
            f"{creator[:18]:<18}"
        )

    print()
    print(
        Color.wrap(
            "Note: 'Pos' above is the displayed populated-Mii order. "
            "Original physical Plaza slots are listed below:",
            Color.DIM,
        )
    )
    print(
        "  "
        + ", ".join(
            f"{mii.name or '<unnamed>'}={mii.original_slot}"
            for mii in records
        )
    )


# ---------------------------------------------------------------------------
# MAC / System-ID conversion
# ---------------------------------------------------------------------------

def parse_mac(text: str) -> bytes:
    compact = re.sub(r"[^0-9A-Fa-f]", "", text)

    if len(compact) != 12:
        raise ValueError(
            "MAC address must contain exactly 12 hexadecimal digits "
            "(example: 00:22:D7:00:9A:BC)."
        )

    try:
        mac = bytes.fromhex(compact)
    except ValueError as exc:
        raise ValueError("Invalid hexadecimal MAC address.") from exc

    if len(mac) != 6:
        raise ValueError("MAC address must be exactly 6 bytes.")

    return mac


def mac_to_system_id(mac: bytes) -> bytes:
    """
    Convert a 6-byte Wii MAC to the 4-byte Mii System ID.

    Matches known real-world examples:
      00:17:AB:0A:84:BB -> C20A84BB
      00:22:D7:00:9A:BC -> 79009ABC
    """
    if len(mac) != 6:
        raise ValueError("MAC must contain 6 bytes.")

    checksum = (mac[0] + mac[1] + mac[2]) & 0xFF

    # Nintendo's original 00:17:AB OUI produces C2 and retains bit 7.
    # Other Wii OUIs use the same checksum with the high bit cleared.
    if mac[:3] != bytes.fromhex("0017AB"):
        checksum &= 0x7F

    return bytes([checksum]) + mac[3:6]


def parse_system_id(text: str) -> bytes:
    compact = re.sub(r"[^0-9A-Fa-f]", "", text)

    if len(compact) != 8:
        raise ValueError(
            "System/Console ID must contain exactly 8 hexadecimal digits "
            "(example: 79009ABC)."
        )

    try:
        value = bytes.fromhex(compact)
    except ValueError as exc:
        raise ValueError("Invalid hexadecimal System/Console ID.") from exc

    return value


def ask_target_system_id() -> bytes:
    heading("Target Wii identity")

    print(
        "Enter the target Wii's MAC address. "
        "Press Enter if the MAC address is unknown."
    )

    while True:
        mac_text = input("Target MAC address: ").strip()

        if not mac_text:
            break

        try:
            mac = parse_mac(mac_text)
            system_id = mac_to_system_id(mac)

            print()
            info(
                "MAC normalized to: "
                + ":".join(f"{byte:02X}" for byte in mac)
            )
            info(f"Calculated Mii System ID: {system_id.hex().upper()}")

            if yes_no("Use this System ID?", default=True):
                return system_id

        except ValueError as exc:
            error(str(exc))

    print()
    print(
        "MAC address unknown. Enter the target Wii's 4-byte "
        "Mii System ID / Console ID instead."
    )

    while True:
        system_text = input("Target System/Console ID: ").strip()

        try:
            system_id = parse_system_id(system_text)
            info(f"Target Mii System ID: {system_id.hex().upper()}")

            if yes_no("Use this System ID?", default=True):
                return system_id

        except ValueError as exc:
            error(str(exc))


# ---------------------------------------------------------------------------
# RFL checksum
# ---------------------------------------------------------------------------

def crc16_ccitt(data: bytes) -> int:
    """
    CRC-16/CCITT:
      polynomial = 0x1021
      initial value = 0x0000
    """
    crc = 0

    for byte in data:
        crc ^= byte << 8

        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF

    return crc


def validate_database(data: bytes) -> tuple[int, int]:
    if len(data) < RFL_CRC_OFFSET + 2:
        raise ValueError(
            f"File is too small ({len(data)} bytes) to be a supported "
            "RFL_DB.dat."
        )

    if data[:4] != RFL_SIGNATURE:
        raise ValueError(
            "Invalid RFL_DB.dat signature. Expected 'RNOD' at offset 0."
        )

    stored_crc = int.from_bytes(
        data[RFL_CRC_OFFSET:RFL_CRC_OFFSET + 2],
        "big",
    )
    calculated_crc = crc16_ccitt(data[:RFL_CRC_OFFSET])

    return stored_crc, calculated_crc


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------

def ask_sort_order(records: List[MiiRecord]) -> List[MiiRecord]:
    """
    Ask for one unique destination position for every populated Mii.

    The resulting positions are 0 through N-1. This intentionally compacts
    populated Plaza Miis into the first N slots.
    """
    if len(records) <= 1:
        return list(records)

    display_miis(records, "Current Mii Plaza order")

    if not yes_no("Do you want to change the Mii order?", default=False):
        return list(records)

    heading("Assign new Mii positions")

    print(
        f"There are {len(records)} populated Miis.\n"
        f"Assign each Mii exactly one position from 0 through "
        f"{len(records) - 1}.\n"
        "A position cannot be used twice."
    )
    print()

    available = set(range(len(records)))
    assigned: dict[int, MiiRecord] = {}

    for index, mii in enumerate(records):
        while True:
            remaining = ", ".join(str(x) for x in sorted(available))
            print(
                f"Mii {index + 1}/{len(records)}: "
                f"{mii.name!r}  "
                f"(Mii ID {mii.mii_id_hex}, current order {index})"
            )
            print(f"Available positions: {remaining}")

            answer = input(
                f"New position for {mii.name!r}: "
            ).strip()

            try:
                position = int(answer)
            except ValueError:
                error("Enter a numeric position.")
                print()
                continue

            if position not in range(len(records)):
                error(
                    f"Position must be between 0 and {len(records) - 1}."
                )
                print()
                continue

            if position not in available:
                error(f"Position {position} has already been assigned.")
                print()
                continue

            assigned[position] = mii
            available.remove(position)
            print()
            break

    sorted_records = [assigned[pos] for pos in range(len(records))]

    display_miis(sorted_records, "Requested new Mii order")

    if yes_no("Use this Mii order?", default=True):
        return sorted_records

    warn("Re-entering Mii order.")
    return ask_sort_order(records)


# ---------------------------------------------------------------------------
# Patching
# ---------------------------------------------------------------------------

def patch_database(
    original: bytes,
    target_system_id: bytes,
    sorted_records: List[MiiRecord],
    reorder: bool,
) -> tuple[bytes, int, int, int]:
    """
    Patch populated Mii System IDs and optionally rewrite the first N Plaza
    slots in the requested order.

    Only the Mii Plaza area and the database CRC are changed.
    """
    out = bytearray(original)

    # Snapshot records before changing any slot.
    records_to_write: List[bytes] = []

    for mii in sorted_records:
        record = bytearray(mii.raw)
        record[SYSTEM_ID_OFFSET:SYSTEM_ID_OFFSET + 4] = target_system_id
        records_to_write.append(bytes(record))

    changed_system_ids = sum(
        1 for mii in sorted_records if mii.system_id != target_system_id
    )

    if reorder:
        # Clear only the 100 Mii Plaza record slots.
        plaza_end = MII_PLAZA_BASE + MII_PLAZA_SLOT_COUNT * MII_RECORD_SIZE
        out[MII_PLAZA_BASE:plaza_end] = b"\x00" * (
            MII_PLAZA_SLOT_COUNT * MII_RECORD_SIZE
        )

        # Write complete records into positions 0..N-1.
        for position, record in enumerate(records_to_write):
            start = MII_PLAZA_BASE + position * MII_RECORD_SIZE
            out[start:start + MII_RECORD_SIZE] = record
    else:
        # Keep physical Plaza slots exactly where they are; only patch System ID.
        for mii, record in zip(sorted_records, records_to_write):
            start = MII_PLAZA_BASE + mii.original_slot * MII_RECORD_SIZE
            out[start:start + MII_RECORD_SIZE] = record

    old_crc = int.from_bytes(
        original[RFL_CRC_OFFSET:RFL_CRC_OFFSET + 2],
        "big",
    )

    new_crc = crc16_ccitt(out[:RFL_CRC_OFFSET])
    out[RFL_CRC_OFFSET:RFL_CRC_OFFSET + 2] = new_crc.to_bytes(2, "big")

    return bytes(out), changed_system_ids, old_crc, new_crc


# ---------------------------------------------------------------------------
# Input/output
# ---------------------------------------------------------------------------

def ask_input_file() -> Path:
    heading("Input RFL_DB.dat")

    while True:
        raw = input("Path to input RFL_DB.dat: ").strip().strip('"').strip("'")

        path = Path(raw).expanduser()

        if not path.is_file():
            error(f"File not found: {path}")
            continue

        return path.resolve()


def make_output_path(input_path: Path) -> Path:
    """
    Always place generated output in the same directory as this script.
    The input file may come from anywhere.
    """
    default = SCRIPT_DIR / "RFL_DB_patched.dat"

    print()
    raw = input(
        f"Output filename [Enter for {default.name}]: "
    ).strip().strip('"').strip("'")

    if not raw:
        output = default
    else:
        # Only use the supplied basename. This intentionally prevents an
        # entered path from redirecting output outside the script folder.
        output = SCRIPT_DIR / Path(raw).name

    output = output.resolve()

    if output == input_path.resolve():
        raise ValueError(
            "Output path resolves to the input file. "
            "The script will not overwrite the original."
        )

    if output.exists():
        if not yes_no(f"{output.name} already exists. Overwrite it?", default=False):
            raise RuntimeError("Output cancelled by user.")

    return output


def make_backup(input_path: Path) -> Path:
    """
    Always place untouched input backups beneath the script directory.
    """
    backup_dir = SCRIPT_DIR / "rfl_db_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"RFL_DB_{timestamp}.dat"

    shutil.copy2(input_path, backup_path)
    return backup_path



# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    heading("RFL_DB.dat System-ID Converter + Mii Sorter")

    print(
        "This tool changes populated Mii System IDs to match a target Wii "
        "and can optionally reorder the Miis in the 100-slot Mii Plaza.\n"
        "The original input file is never modified."
    )
    info(f"Generated files will be written to: {SCRIPT_DIR}")

    try:
        input_path = ask_input_file()
        original = input_path.read_bytes()

        heading("Validating database")

        stored_crc, calculated_crc = validate_database(original)

        info(f"File: {input_path}")
        info(f"Size: {len(original)} bytes")
        info(f"Stored CRC:     {stored_crc:04X}")
        info(f"Calculated CRC: {calculated_crc:04X}")

        if stored_crc != calculated_crc:
            warn(
                "The input database CRC does NOT match. "
                "The script can still repair it when writing the output."
            )

            if not yes_no(
                "Continue with this database anyway?",
                default=False,
            ):
                return 1
        else:
            ok("Input database CRC is valid.")

        records = read_mii_records(original)

        if not records:
            raise ValueError("No populated Mii Plaza records were found.")

        display_miis(records, "Mii Plaza contents")

        target_system_id = ask_target_system_id()

        # Ask sorter and determine whether actual record order changed.
        sorted_records = ask_sort_order(records)

        reorder = [
            m.mii_id for m in sorted_records
        ] != [
            m.mii_id for m in records
        ]

        heading("Patch summary")

        info(f"Target System ID: {target_system_id.hex().upper()}")
        info(f"Populated Miis: {len(records)}")
        info(
            "Mii order: "
            + ("will be changed" if reorder else "will remain unchanged")
        )

        print()
        print("System-ID changes:")
        for mii in records:
            old = mii.system_id_hex
            new = target_system_id.hex().upper()
            marker = "CHANGE" if mii.system_id != target_system_id else "same"
            print(
                f"  {mii.name[:20]:<20} "
                f"{old} -> {new}  [{marker}]"
            )

        if reorder:
            print()
            print("New order:")
            for position, mii in enumerate(sorted_records):
                print(f"  {position:>3}: {mii.name}")

        if not yes_no("Create the patched RFL_DB.dat?", default=True):
            warn("Cancelled. Nothing was written.")
            return 1

        output_path = make_output_path(input_path)

        # Create an untouched backup before writing output.
        backup_path = make_backup(input_path)

        patched, changed_ids, old_crc, new_crc = patch_database(
            original=original,
            target_system_id=target_system_id,
            sorted_records=sorted_records,
            reorder=reorder,
        )

        output_path.write_bytes(patched)

        # Validate the final file.
        final_stored_crc, final_calculated_crc = validate_database(patched)

        if final_stored_crc != final_calculated_crc:
            raise RuntimeError(
                "Internal validation failed: output CRC does not match."
            )

        final_records = read_mii_records(patched)

        # Confirm every populated output Mii has target System ID.
        for mii in final_records:
            if mii.system_id != target_system_id:
                raise RuntimeError(
                    f"Internal validation failed: {mii.name!r} has "
                    f"System ID {mii.system_id_hex} instead of "
                    f"{target_system_id.hex().upper()}."
                )

        heading("Completed")

        ok(f"Patched file: {output_path}")
        ok(f"Original backup: {backup_path}")

        print()
        print(f"System IDs changed: {changed_ids}")
        print(f"CRC: {old_crc:04X} -> {new_crc:04X}")
        print(f"Final CRC verified: {final_stored_crc:04X}")
        print(
            "SHA-256: "
            + hashlib.sha256(patched).hexdigest()
        )

        print()
        print("Final Mii order:")
        for position, mii in enumerate(final_records):
            print(
                f"  {position:>3}: {mii.name:<20} "
                f"ID={mii.mii_id_hex} "
                f"SID={mii.system_id_hex}"
            )

        print()
        ok("The original input RFL_DB.dat was not modified.")

        return 0

    except KeyboardInterrupt:
        print()
        warn("Cancelled by user.")
        return 130

    except Exception as exc:
        print()
        error(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
