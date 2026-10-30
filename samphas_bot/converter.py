
"""FFX version-marker converter.

Changes the four-byte version marker at offset 0x18.
Older version profiles are experimental.
This does not translate effects or preset internals.
"""

from pathlib import Path
import struct


MARKER_OFFSET = 0x18

VERSION_MARKERS = {
    "After Effects 2020 (experimental)": 91,
    "After Effects 2021 (experimental)": 92,
    "After Effects 2022 (experimental)": 93,
    "After Effects 2023 (experimental)": 94,
    "After Effects 2024 (experimental)": 95,
    "After Effects 2025": 96,
    "After Effects 2026": 97,
}

MARKER_TO_VERSION = {
    marker: version for version, marker in VERSION_MARKERS.items()
}


class ConversionError(Exception):
    pass


def inspect_ffx(path):
    data = Path(path).read_bytes()

    if len(data) < 0x1C or data[:4] != b"RIFX":
        raise ConversionError("This does not look like a supported FFX file.")

    marker = struct.unpack(">I", data[MARKER_OFFSET:MARKER_OFFSET + 4])[0]

    if marker not in MARKER_TO_VERSION:
        raise ConversionError(
            f"Unknown FFX marker {marker}. Conversion stopped for safety."
        )

    return {
        "size": len(data),
        "marker": marker,
        "version": MARKER_TO_VERSION[marker],
        "data": data,
    }


def ffx_is_experimental(version):
    return "(experimental)" in version


def convert_ffx(source, destination, target, direction):
    if target not in VERSION_MARKERS:
        raise ConversionError("Unsupported target version.")

    if direction not in ("upgrade", "downgrade"):
        raise ConversionError("Choose upgrade or downgrade.")

    info = inspect_ffx(source)
    source_marker = info["marker"]
    target_marker = VERSION_MARKERS[target]

    if source_marker == target_marker:
        raise ConversionError("The preset already has that version marker.")

    if direction == "upgrade" and target_marker < source_marker:
        raise ConversionError("That target is older. Choose downgrade instead.")

    if direction == "downgrade" and target_marker > source_marker:
        raise ConversionError("That target is newer. Choose upgrade instead.")

    patched = bytearray(info["data"])
    patched[MARKER_OFFSET:MARKER_OFFSET + 4] = struct.pack(
        ">I", target_marker
    )

    # Verify that only the version marker changed.
    check = bytearray(patched)
    check[MARKER_OFFSET:MARKER_OFFSET + 4] = info["data"][
        MARKER_OFFSET:MARKER_OFFSET + 4
    ]

    if bytes(check) != info["data"]:
        raise ConversionError("Output verification failed.")

    Path(destination).write_bytes(patched)

    experimental = (
        ffx_is_experimental(info["version"])
        or ffx_is_experimental(target)
    )

    return info["version"], target, experimental


def detect_ffx_version(path):
    return inspect_ffx(path)["version"]

# AEP project support retained for the Discord bot.

AEP_VALUES = {
    "After Effects CS6": 2752,
    "After Effects 2014": 2880,
    "After Effects 2015": 2944,
    "After Effects 2015.3": 3008,
    "After Effects 2017": 3072,
    "After Effects 2018": 3136,
    "After Effects 2019": 3200,
    "After Effects 2020": 3264,
    "After Effects 2021": 3328,
    "After Effects 2022": 3392,
    "After Effects 2023": 3456,
    "After Effects 2024": 3520,
    "After Effects 2025": 3584,
}

AEP_BY_VALUE = {value: name for name, value in AEP_VALUES.items()}


def _find_tdsn(data):
    start = 0
    while True:
        pos = data.find(b"tdsn", start)
        if pos < 0:
            break

        value_pos = pos + 8
        if value_pos + 2 <= len(data):
            value = struct.unpack(">H", data[value_pos:value_pos + 2])[0]
            if value in AEP_BY_VALUE:
                return value_pos, value

        start = pos + 4

    raise ConversionError("Could not find a recognized AEP version marker.")


def detect_aep_version(path):
    data = Path(path).read_bytes()

    if not data.startswith(b"RIFX"):
        raise ConversionError("This does not look like a RIFX AEP project.")

    _, value = _find_tdsn(data)
    return AEP_BY_VALUE[value]


def downgrade_aep(source, output, target):
    if target not in AEP_VALUES:
        raise ConversionError("Unsupported AEP target version.")

    data = bytearray(Path(source).read_bytes())
    pos, source_value = _find_tdsn(data)
    target_value = AEP_VALUES[target]

    if target_value >= source_value:
        raise ConversionError("AEP conversion only supports downgrading.")

    data[pos:pos + 2] = struct.pack(">H", target_value)
    Path(output).write_bytes(data)
