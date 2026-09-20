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
