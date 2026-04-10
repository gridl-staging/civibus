"""FEC donor name parser: 'LAST, FIRST MIDDLE SUFFIX' format."""

_KNOWN_SUFFIXES = frozenset({"JR", "SR", "II", "III", "IV", "V", "MD", "PHD", "ESQ", "DDS", "DVM", "RN", "CPA"})


def parse_fec_name(raw_name: str | None) -> dict[str, str | None] | None:
    """Parse an FEC-format name into components.

    Returns {"first_name", "middle_name", "last_name", "suffix"} with None for
    missing parts, or None entirely if the input has no comma (not a person name),
    is empty, or is None.
    """
    if not raw_name or "," not in raw_name:
        return None

    last_name, _, rest = raw_name.partition(",")
    last_name = last_name.strip()
    tokens = rest.strip().split()

    if not tokens:
        return None

    first_name = tokens[0]
    middle_name = None
    suffix = None

    if len(tokens) == 2:
        # Could be "FIRST SUFFIX" or "FIRST MIDDLE"
        if tokens[1].upper() in _KNOWN_SUFFIXES:
            suffix = tokens[1].upper()
        else:
            middle_name = tokens[1]
    elif len(tokens) >= 3:
        # "FIRST MIDDLE SUFFIX" or "FIRST MIDDLE"
        if tokens[-1].upper() in _KNOWN_SUFFIXES:
            suffix = tokens[-1].upper()
            middle_name = " ".join(tokens[1:-1]) if len(tokens) > 2 else None
        else:
            middle_name = " ".join(tokens[1:])

    return {
        "first_name": first_name,
        "middle_name": middle_name,
        "last_name": last_name,
        "suffix": suffix,
    }
