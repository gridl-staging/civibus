"""
Stub summary for MAR18_state_expansion_batch_2/civibus_dev/domains/campaign_finance/normalize/names.py.
"""

from dataclasses import dataclass

KNOWN_SUFFIXES = frozenset({"JR", "SR", "II", "III", "IV", "V", "MD", "PHD", "ESQ", "DDS", "DVM", "RN", "CPA"})
KNOWN_PREFIXES = frozenset({"MR", "MRS", "MS", "DR", "HON", "REV", "SGT", "CPL", "PFC"})


@dataclass(frozen=True)
class ParsedName:
    prefix: str | None = None
    first: str | None = None
    middle: str | None = None
    last: str | None = None
    suffix: str | None = None

    @property
    def canonical(self) -> str:
        parts: list[str] = []
        if self.first:
            parts.append(self.first)
        if self.middle:
            middle_clean = self.middle.strip()
            if middle_clean:
                parts.append(middle_clean[0])
        if self.last:
            parts.append(self.last)
        if self.suffix:
            parts.append(self.suffix)
        return " ".join(parts)


def parse_name(
    raw: str | None,
    *,
    surname_first: bool = False,
    first_last_only: bool = False,
) -> ParsedName:
    """Parse a campaign-finance person name into canonical name fields.

    ``first_last_only`` is the NC transaction resolver's natural-order two-field
    projection: default behavior, comma-bearing FEC parsing, affix stripping,
    and single-token handling remain unchanged, while natural multi-token names
    keep only the first and last core tokens. It cannot be combined with
    ``surname_first`` because the two modes declare conflicting token order.
    """
    if first_last_only and surname_first:
        raise ValueError("first_last_only cannot be combined with surname_first")

    cleaned_name = _clean_name_input(raw)
    if cleaned_name is None:
        return ParsedName()
    if "," in cleaned_name:
        return _parse_fec_format(cleaned_name)
    if surname_first:
        # The FEC caller knows its source ordering. Sniffing order here would create
        # a second, corpus-dependent identity rule that could disagree between loads.
        return _parse_surname_first_format(cleaned_name)
    return _parse_natural_format(cleaned_name, first_last_only=first_last_only)


def _clean_name_input(raw: str | None) -> str | None:
    if raw is None:
        return None
    stripped_raw = raw.strip()
    return stripped_raw or None


def _parse_fec_format(raw_name: str) -> ParsedName:
    last_segment, _, trailing_segment = raw_name.partition(",")
    normalized_last = _normalize_text(last_segment)
    # Only the first comma separates the surname from the given-name segment.
    # Any further commas (e.g. "FLEMING, CPA, PLLC" or "SMITH, JOHN, JR") are
    # token delimiters, not part of a token — treat them as whitespace so no
    # token retains a trailing comma artifact like "CPA," or "JOHN,".
    trailing_tokens = trailing_segment.replace(",", " ").split()
    prefix, core_tokens, suffix = _strip_known_affixes(_normalize_tokens(trailing_tokens))
    first, middle = _extract_first_and_middle(core_tokens)

    return ParsedName(
        prefix=prefix,
        first=first,
        middle=middle,
        last=normalized_last or None,
        suffix=suffix,
    )


def _parse_natural_format(raw_name: str, *, first_last_only: bool = False) -> ParsedName:
    prefix, core_tokens, suffix = _strip_known_affixes(_normalize_tokens(raw_name.split()))
    return _parsed_name_from_core_tokens(
        prefix,
        core_tokens,
        suffix,
        surname_first=False,
        first_last_only=first_last_only,
    )


def _parse_surname_first_format(raw_name: str) -> ParsedName:
    prefix, core_tokens, suffix = _strip_known_affixes(_normalize_tokens(raw_name.split()))
    return _parsed_name_from_core_tokens(
        prefix,
        core_tokens,
        suffix,
        surname_first=True,
        first_last_only=False,
    )


def _parsed_name_from_core_tokens(
    prefix: str | None,
    core_tokens: list[str],
    suffix: str | None,
    *,
    surname_first: bool,
    first_last_only: bool,
) -> ParsedName:
    if not core_tokens:
        return ParsedName(prefix=prefix, suffix=suffix)
    if len(core_tokens) == 1:
        single_name_token = core_tokens[0]
        if prefix or suffix:
            return ParsedName(prefix=prefix, first=single_name_token, suffix=suffix)
        return ParsedName(last=single_name_token)

    if surname_first:
        first = core_tokens[-1]
        last = _join_tokens(core_tokens[:-1])
        return ParsedName(prefix=prefix, first=first, last=last, suffix=suffix)

    first = core_tokens[0]
    last = core_tokens[-1]
    middle = None if first_last_only else _join_tokens(core_tokens[1:-1])
    return ParsedName(prefix=prefix, first=first, middle=middle, last=last, suffix=suffix)


def _normalize_tokens(tokens: list[str]) -> list[str]:
    normalized_tokens: list[str] = []
    for token in tokens:
        normalized_token = _normalize_text(token)
        if normalized_token:
            normalized_tokens.append(normalized_token)
    return normalized_tokens


def _normalize_text(value: str) -> str:
    return value.strip().upper()


def _pop_prefix_token(tokens: list[str]) -> tuple[str | None, list[str]]:
    if not tokens:
        return None, []

    normalized_prefix = _strip_periods(tokens[0])
    if normalized_prefix not in KNOWN_PREFIXES:
        return None, tokens
    return normalized_prefix, tokens[1:]


def _strip_periods(token: str) -> str:
    return token.replace(".", "")


def _pop_suffix_token(tokens: list[str]) -> tuple[str | None, list[str]]:
    if not tokens:
        return None, []

    normalized_suffix = _strip_periods(tokens[-1])
    if normalized_suffix not in KNOWN_SUFFIXES:
        return None, tokens
    return normalized_suffix, tokens[:-1]


def _strip_known_affixes(tokens: list[str]) -> tuple[str | None, list[str], str | None]:
    prefix, tokens_without_prefix = _pop_prefix_token(tokens)
    suffix, core_tokens = _pop_suffix_token(tokens_without_prefix)
    return prefix, core_tokens, suffix


def _extract_first_and_middle(tokens: list[str]) -> tuple[str | None, str | None]:
    if not tokens:
        return None, None
    if len(tokens) == 1:
        return tokens[0], None
    return tokens[0], _join_tokens(tokens[1:])


def _join_tokens(tokens: list[str]) -> str | None:
    if not tokens:
        return None
    return " ".join(tokens)
