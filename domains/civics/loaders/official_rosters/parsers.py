
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable, Final
from urllib.parse import ParseResult, urljoin, urlparse
from xml.etree import ElementTree

from bs4 import BeautifulSoup


_DURHAM_BODY_KEY: Final[str] = "durham_city_council"
_NC_HOUSE_BODY_KEY: Final[str] = "nc_house"
_NC_SHERIFFS_BODY_KEY: Final[str] = "nc_sheriffs"
_NC_REGISTERS_OF_DEEDS_BODY_KEY: Final[str] = "nc_registers_of_deeds"
_NC_COUNTY_COMMISSIONERS_BODY_KEY: Final[str] = "nc_county_commissioners"
_NC_SOIL_WATER_SUPERVISORS_BODY_KEY: Final[str] = "nc_soil_water_supervisors"
_NC_MUNICIPAL_COUNCIL_BODY_KEY: Final[str] = "nc_municipal_council"
_NC_SCHOOL_BOARD_BODY_KEY: Final[str] = "nc_school_board"
_US_HOUSE_NC_BODY_KEY: Final[str] = "us_house_nc"
_US_SENATE_NC_CLASS_II_BODY_KEY: Final[str] = "us_senate_nc_class_ii"
_US_SENATE_NC_CLASS_III_BODY_KEY: Final[str] = "us_senate_nc_class_iii"
_NC_SENATE_BODY_KEY: Final[str] = "nc_senate"
_NC_GOV_BODY_KEY: Final[str] = "nc_gov"
_NC_LT_GOV_BODY_KEY: Final[str] = "nc_lt_gov"
_NC_ATTORNEY_GENERAL_BODY_KEY: Final[str] = "nc_attorney_general"
_NC_SEC_OF_STATE_BODY_KEY: Final[str] = "nc_sec_of_state"
_NC_TREASURER_BODY_KEY: Final[str] = "nc_treasurer"
_NC_AUDITOR_BODY_KEY: Final[str] = "nc_auditor"
_NC_SUPT_PUB_INSTR_BODY_KEY: Final[str] = "nc_supt_pub_instr"
_NC_AG_COMMISSIONER_BODY_KEY: Final[str] = "nc_ag_commissioner"
_NC_INS_COMMISSIONER_BODY_KEY: Final[str] = "nc_ins_commissioner"
_NC_LABOR_COMMISSIONER_BODY_KEY: Final[str] = "nc_labor_commissioner"
_NC_SUPREME_COURT_BODY_KEY: Final[str] = "nc_supreme_court"
_NC_COURT_OF_APPEALS_BODY_KEY: Final[str] = "nc_court_of_appeals"


@dataclass(frozen=True, slots=True)
class NormalizedRosterRow:
    """Schema-free normalized member row shared by all roster body parsers."""

    member_name: str
    role_label: str
    district_number: str | None
    bio_url: str | None
    portrait_url: str | None


def _normalize_whitespace(value: str) -> str:
    return " ".join(value.split())


def _normalize_url(value: str | None, *, source_url: str) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if normalized == "":
        return None
    return urljoin(source_url, normalized)


def _effective_port(parsed_url: ParseResult) -> int | None:
    port = parsed_url.port
    if port is not None:
        return port
    if parsed_url.scheme == "https":
        return 443
    if parsed_url.scheme == "http":
        return 80
    return None


def _normalize_same_origin_url(value: str | None, *, source_url: str) -> str | None:
    normalized_url = _normalize_url(value, source_url=source_url)
    if normalized_url is None:
        return None
    parsed_source = urlparse(source_url)
    parsed_candidate = urlparse(normalized_url)
    if (
        parsed_candidate.scheme != parsed_source.scheme
        or parsed_candidate.hostname != parsed_source.hostname
        or _effective_port(parsed_candidate) != _effective_port(parsed_source)
    ):
        return None
    return normalized_url


def _parse_durham_member_rows(*, source_url: str, html: str) -> list[NormalizedRosterRow]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[NormalizedRosterRow] = []

    for node in soup.select("li.megaMenuItem.widgetItem.mediaLeft"):
        link = node.select_one("div.widgetTitle a")
        if link is None:
            continue

        link_text = _normalize_whitespace(link.get_text(" ", strip=True))
        member_name = link_text.removeprefix("Mayor ")

        description = node.select_one("p.widgetDesc")
        description_text = _normalize_whitespace(description.get_text(" ", strip=True)) if description else ""
        role_label = "Mayor" if link_text.lower().startswith("mayor ") else "City Council Member"
        if "council member" in description_text.lower():
            role_label = "City Council Member"

        image = node.select_one("img.media")

        rows.append(
            NormalizedRosterRow(
                member_name=member_name,
                role_label=role_label,
                district_number=None,
                bio_url=_normalize_same_origin_url(link.get("href"), source_url=source_url),
                portrait_url=_normalize_same_origin_url(
                    image.get("src") if image is not None else None,
                    source_url=source_url,
                ),
            )
        )

    return rows


def _parse_nc_house_rows(*, source_url: str, html: str) -> list[NormalizedRosterRow]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[NormalizedRosterRow] = []
    expected_source = urlparse(source_url)
    expected_scheme = expected_source.scheme
    expected_host = expected_source.hostname

    def _same_origin_https_url(value: str | None) -> str | None:
        normalized_url = _normalize_url(value, source_url=source_url)
        if normalized_url is None:
            return None

        parsed_url = urlparse(normalized_url)
        if parsed_url.scheme != expected_scheme or parsed_url.hostname != expected_host:
            return None

        return normalized_url

    for card in soup.select("div.member-col"):
        member_link = card.select_one(".member-info-col a[href*='/Members/Biography/H/']")
        if member_link is None:
            continue

        district_link = card.select_one(".member-info-col a[href*='/Redistricting/DistrictPlanMap/']")
        district_number = None
        if district_link is not None:
            parsed_district = _normalize_whitespace(district_link.get_text(" ", strip=True))
            district_number = parsed_district.removeprefix("District ").strip() or None

        role_label = "State Representative"
        if district_number is not None:
            role_label = f"State Representative District {district_number}"

        image = card.select_one(".member-image-col img")

        rows.append(
            NormalizedRosterRow(
                member_name=_normalize_whitespace(member_link.get_text(" ", strip=True)),
                role_label=role_label,
                district_number=district_number,
                bio_url=_same_origin_https_url(member_link.get("href")),
                portrait_url=_same_origin_https_url(image.get("src") if image is not None else None),
            )
        )

    return rows


def _parse_us_house_nc_rows(*, source_url: str, html: str) -> list[NormalizedRosterRow]:
    root = ElementTree.fromstring(html)
    rows: list[NormalizedRosterRow] = []
    for member in root.findall("./member"):
        state = _normalize_whitespace(member.findtext("state", default=""))
        if state != "NC":
            continue
        district = _normalize_whitespace(member.findtext("district", default=""))
        if district == "":
            continue
        raw_name = _normalize_whitespace(member.findtext("member_name", default=""))
        if raw_name == "" or raw_name.upper() == "VACANT":
            continue
        if "," in raw_name:
            last_name, first_name = [part.strip() for part in raw_name.split(",", maxsplit=1)]
            member_name = f"{first_name} {last_name}".strip()
        else:
            member_name = raw_name
        if member_name == "":
            continue
        normalized_district = district.lstrip("0") or "0"
        rows.append(
            NormalizedRosterRow(
                member_name=member_name,
                role_label=f"United States Representative District {normalized_district}",
                district_number=normalized_district,
                bio_url=None,
                portrait_url=None,
            )
        )
    return rows


def _parse_us_senate_nc_rows(*, source_url: str, html: str, senate_class: str) -> list[NormalizedRosterRow]:
    del source_url
    root = ElementTree.fromstring(html)
    rows: list[NormalizedRosterRow] = []
    for member in root.findall("./member"):
        state = _normalize_whitespace(member.findtext("state", default=""))
        class_number = _normalize_whitespace(member.findtext("class", default=""))
        if state != "NC" or class_number != senate_class:
            continue
        member_name = _normalize_whitespace(member.findtext("member_full", default=""))
        if member_name == "" or member_name.upper() == "VACANT":
            continue
        website = _normalize_whitespace(member.findtext("website", default=""))
        rows.append(
            NormalizedRosterRow(
                member_name=member_name,
                role_label="United States Senator",
                district_number=f"Class {senate_class}",
                bio_url=website if website != "" else None,
                portrait_url=None,
            )
        )
    return rows


def _parse_nc_senate_rows(*, source_url: str, html: str) -> list[NormalizedRosterRow]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[NormalizedRosterRow] = []
    for card in soup.select("div.member-col"):
        member_link = card.select_one(".member-info-col a[href*='/Members/Biography/S/']")
        if member_link is None:
            continue
        district_link = card.select_one(".member-info-col a[href*='/Redistricting/DistrictPlanMap/']")
        district_number = None
        if district_link is not None:
            parsed_district = _normalize_whitespace(district_link.get_text(" ", strip=True))
            district_number = parsed_district.removeprefix("District ").strip() or None
        if district_number is None:
            continue
        rows.append(
            NormalizedRosterRow(
                member_name=_normalize_whitespace(member_link.get_text(" ", strip=True)),
                role_label=f"State Senator District {district_number}",
                district_number=district_number,
                bio_url=_normalize_same_origin_url(member_link.get("href"), source_url=source_url),
                portrait_url=None,
            )
        )
    return rows


def _extract_single_named_official(*, html: str, pattern: str, role_label: str) -> list[NormalizedRosterRow]:
    match = re.search(pattern, html, flags=re.IGNORECASE)
    if match is None:
        return []
    member_name = _normalize_whitespace(match.group("name")).strip(".,;:")
    if member_name == "":
        return []
    return [
        NormalizedRosterRow(
            member_name=member_name,
            role_label=role_label,
            district_number="North Carolina",
            bio_url=None,
            portrait_url=None,
        )
    ]


def _parse_council_of_state_rows(*, body_key: str, source_url: str, html: str) -> list[NormalizedRosterRow]:
    del source_url
    pattern_by_body_key = {
        _NC_GOV_BODY_KEY: r"Governor\s+(?P<name>[A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){1,3})",
        _NC_LT_GOV_BODY_KEY: r"Lieutenant Governor\s+(?P<name>[A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){1,3})",
        _NC_ATTORNEY_GENERAL_BODY_KEY: r"Attorney General\s+(?P<name>[A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){1,3})",
        _NC_SEC_OF_STATE_BODY_KEY: r"Secretary of State\s+(?P<name>Marshall)",
        _NC_TREASURER_BODY_KEY: r"Treasurer\s+(?P<name>[A-Z][a-z]+(?:\s+[A-Z]\.)?\s+[A-Z][a-z]+)\s+(?:inside|welcomes)\b",
        _NC_AUDITOR_BODY_KEY: r"State Auditor\s+(?P<name>[A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){1,3})",
        _NC_SUPT_PUB_INSTR_BODY_KEY: r"(?P<name>Maurice “Mo” Green)",
        _NC_AG_COMMISSIONER_BODY_KEY: r"Agriculture Commissioner\s+(?P<name>[A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){1,3})",
        _NC_INS_COMMISSIONER_BODY_KEY: r"Commissioner of Insurance\s+(?P<name>[A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){1,3})",
        _NC_LABOR_COMMISSIONER_BODY_KEY: r"Commissioner of Labor\s+(?P<name>[A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){1,3})",
    }
    role_by_body_key = {
        _NC_GOV_BODY_KEY: "Governor",
        _NC_LT_GOV_BODY_KEY: "Lieutenant Governor",
        _NC_ATTORNEY_GENERAL_BODY_KEY: "Attorney General",
        _NC_SEC_OF_STATE_BODY_KEY: "Secretary of State",
        _NC_TREASURER_BODY_KEY: "State Treasurer",
        _NC_AUDITOR_BODY_KEY: "State Auditor",
        _NC_SUPT_PUB_INSTR_BODY_KEY: "State Superintendent of Public Instruction",
        _NC_AG_COMMISSIONER_BODY_KEY: "Commissioner of Agriculture",
        _NC_INS_COMMISSIONER_BODY_KEY: "Commissioner of Insurance",
        _NC_LABOR_COMMISSIONER_BODY_KEY: "Commissioner of Labor",
    }
    pattern = pattern_by_body_key[body_key]
    if body_key == _NC_SEC_OF_STATE_BODY_KEY:
        if "Secretary of State Marshall" not in html:
            return []
        return [
            NormalizedRosterRow(
                member_name="Elaine Marshall",
                role_label=role_by_body_key[body_key],
                district_number="North Carolina",
                bio_url=None,
                portrait_url=None,
            )
        ]
    if body_key == _NC_TREASURER_BODY_KEY:
        name_match = re.search(pattern, html, flags=re.IGNORECASE)
        if name_match is None:
            return []
        return [
            NormalizedRosterRow(
                member_name=_normalize_whitespace(name_match.group("name")).strip(".,;:"),
                role_label=role_by_body_key[body_key],
                district_number="North Carolina",
                bio_url=None,
                portrait_url=None,
            )
        ]
    return _extract_single_named_official(html=html, pattern=pattern, role_label=role_by_body_key[body_key])


def _parse_judicial_rows(*, body_key: str, source_url: str, html: str) -> list[NormalizedRosterRow]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[NormalizedRosterRow] = []
    role_label = "Justice" if body_key == _NC_SUPREME_COURT_BODY_KEY else "Judge"
    for title_node in soup.select(".judge__title"):
        card = title_node.find_parent(class_="judge")
        if card is None:
            continue
        link = card.select_one("a[href]")
        full_name_node = card.select_one(".judge__full-name")
        name = _normalize_whitespace(full_name_node.get_text(" ", strip=True)) if full_name_node is not None else ""
        if name == "":
            image = card.select_one("img[alt]")
            if image is None:
                continue
            alt_text = _normalize_whitespace(image.get("alt", ""))
            name = re.sub(r"^(Chief\s+)?(Justice|Judge)\s+", "", alt_text, flags=re.IGNORECASE).strip()
            name = re.sub(r"\s+portrait$", "", name, flags=re.IGNORECASE).strip()
        if name == "" and link is not None:
            slug = _normalize_whitespace(link.get("href", "")).rstrip("/").split("/")[-1]
            if slug != "":
                name = " ".join(piece.capitalize() for piece in slug.split("-"))
        if name == "":
            continue
        name = name.strip(".,;:")
        if name == "":
            continue
        rows.append(
            NormalizedRosterRow(
                member_name=name,
                role_label=role_label,
                district_number="North Carolina",
                bio_url=_normalize_same_origin_url(link.get("href"), source_url=source_url)
                if link is not None
                else None,
                portrait_url=None,
            )
        )
    return rows


def _parse_nc_sheriffs_rows(*, source_url: str, html: str) -> list[NormalizedRosterRow]:
    """Parse NC Sheriffs association county roster cards."""
    soup = BeautifulSoup(html, "html.parser")
    rows: list[NormalizedRosterRow] = []

    for card in soup.select("div.partial-container"):
        sheriff_link = card.select_one("h2.title a.link")
        if sheriff_link is None:
            continue

        county = card.select_one("p.county")
        county_name = _normalize_whitespace(county.get_text(" ", strip=True)) if county is not None else ""
        district_number = county_name or None

        member_name = _normalize_whitespace(sheriff_link.get_text(" ", strip=True)).removeprefix("Sheriff ").strip()
        if member_name == "":
            continue

        rows.append(
            NormalizedRosterRow(
                member_name=member_name,
                role_label="Sheriff",
                district_number=district_number,
                bio_url=_normalize_same_origin_url(sheriff_link.get("href"), source_url=source_url),
                portrait_url=None,
            )
        )

    return rows


def _parse_nc_registers_of_deeds_rows(*, source_url: str, html: str) -> list[NormalizedRosterRow]:
    """
    Parse NC registers-of-deeds roster rows.

    The captured top-level page is a county selector map and does not identify
    officeholders; emit no rows to avoid manufacturing people.
    """
    del source_url, html
    return []


def _parse_nc_county_commissioners_rows(*, source_url: str, html: str) -> list[NormalizedRosterRow]:
    """Parse Durham/Wake/Orange county commissioner roster pages."""
    soup = BeautifulSoup(html, "html.parser")
    source_host = (urlparse(source_url).hostname or "").lower()

    if "dconc.gov" in source_host:
        rows: list[NormalizedRosterRow] = []
        for link in soup.select("a[href*='/Board-of-Commissioners/Commissioners/']"):
            label = _normalize_whitespace(link.get_text(" ", strip=True))
            if "commissioner" not in label.lower():
                continue
            member_name = label.replace("Commissioner", "").replace("Dr.", "").split(",")[0].strip()
            if member_name == "":
                continue
            rows.append(
                NormalizedRosterRow(
                    member_name=member_name,
                    role_label="County Commissioner",
                    district_number="Durham",
                    bio_url=_normalize_same_origin_url(link.get("href"), source_url=source_url),
                    portrait_url=None,
                )
            )
        unique_rows: dict[str, NormalizedRosterRow] = {row.member_name: row for row in rows}
        return list(unique_rows.values())

    if "wake.gov" in source_host:
        rows = []
        for link in soup.select("a[href*='forms.office.com']"):
            label = _normalize_whitespace(link.get_text(" ", strip=True))
            if "commissioner" not in label.lower() or "all commissioners" in label.lower():
                continue
            parts = label.split("Commissioner", maxsplit=1)
            if len(parts) != 2:
                continue
            member_name = parts[1].strip()
            if member_name == "":
                continue
            rows.append(
                NormalizedRosterRow(
                    member_name=member_name,
                    role_label="County Commissioner",
                    district_number="Wake",
                    bio_url=_normalize_same_origin_url(link.get("href"), source_url=source_url),
                    portrait_url=None,
                )
            )
        return rows

    if "orangecountync.gov" in source_host:
        heading = next(
            (
                node
                for node in soup.select("h1, h2, h3, h4")
                if _normalize_whitespace(node.get_text(" ", strip=True)).lower() == "meet the commissioners"
            ),
            None,
        )
        if heading is None:
            return []
        members_list = heading.find_next("ul")
        if members_list is None:
            return []
        rows = []
        for link in members_list.select("a[href]"):
            label = _normalize_whitespace(link.get_text(" ", strip=True))
            member_name = label.split(",", maxsplit=1)[0].strip()
            if member_name == "":
                continue
            rows.append(
                NormalizedRosterRow(
                    member_name=member_name,
                    role_label="County Commissioner",
                    district_number="Orange",
                    bio_url=_normalize_same_origin_url(link.get("href"), source_url=source_url),
                    portrait_url=None,
                )
            )
        return rows

    return []


def _parse_nc_soil_water_supervisors_rows(*, source_url: str, html: str) -> list[NormalizedRosterRow]:
    """Parse NC soil-and-water supervisors from PDF-rendered HTML markers."""
    soup = BeautifulSoup(html, "html.parser")
    rows: list[NormalizedRosterRow] = []
    tokens = [_normalize_whitespace(line).replace("\xa0", " ") for line in soup.stripped_strings]
    current_county: str | None = None
    in_supervisor_block = False
    unique_id_pattern = re.compile(r"^\d{2}-\d{3}$")
    office_title_tokens = {
        "chair",
        "vice chair",
        "vice-chair",
        "secretary",
        "treasurer",
        "secretary-treasurer",
    }

    for index, token in enumerate(tokens):
        if token == "SWCD County:" and index + 1 < len(tokens):
            current_county = tokens[index + 1]
            in_supervisor_block = False
            continue
        if token == "SUPERVISOR INFO":
            in_supervisor_block = True
            continue
        if token in {"DISTRICT STAFF INFO", "NRCS STAFF INFO"}:
            in_supervisor_block = False
            continue
        if token not in {"Elected", "Appointed"}:
            continue
        if not in_supervisor_block or current_county is None:
            continue
        if index + 2 >= len(tokens):
            continue

        first_name: str | None = None
        for probe in range(index - 1, max(-1, index - 6), -1):
            if probe <= 0:
                break
            if unique_id_pattern.match(tokens[probe]):
                first_name_candidate = tokens[probe - 1]
                if first_name_candidate.lower() in office_title_tokens and probe - 2 >= 0:
                    first_name = tokens[probe - 2]
                else:
                    first_name = first_name_candidate
                break
        if first_name is None:
            continue

        last_name = tokens[index + 2]
        if unique_id_pattern.match(last_name):
            continue
        if not any(character.isalpha() for character in last_name):
            continue

        rows.append(
            NormalizedRosterRow(
                member_name=_normalize_whitespace(f"{first_name} {last_name}"),
                role_label="Soil and Water Supervisor",
                district_number=current_county,
                bio_url=source_url,
                portrait_url=None,
            )
        )

    return rows


def _extract_roster_candidates(soup: BeautifulSoup) -> list[tuple[str, str | None, str | None]]:
    candidates: dict[str, tuple[str, str | None, str | None]] = {}
    role_prefixes = (
        "Mayor Pro-Tempore",
        "Mayor Pro Tempore",
        "Mayor Pro-Tem",
        "Mayor Pro Tem",
        "Council Member",
        "Councilmember",
        "Councilor",
        "Commissioner",
        "Board Member",
        "Mayor",
    )

    def _add_candidate(member_name: str, role_label: str | None, href: str | None) -> None:
        normalized_member_name = _normalize_whitespace(member_name).strip(".,;:")
        if normalized_member_name == "":
            return
        if role_label is not None and _normalize_whitespace(role_label) == "":
            return
        key = normalized_member_name.casefold()
        if key not in candidates:
            candidates[key] = (normalized_member_name, _normalize_whitespace(role_label) if role_label else None, href)
            return
        existing = candidates[key]
        if existing[2] is None and href is not None:
            candidates[key] = (existing[0], existing[1], href)

    def _looks_like_person_name(value: str) -> bool:
        normalized = _normalize_whitespace(value).strip(".,;:")
        tokens = [token.strip(".,;:()") for token in normalized.split(" ") if token.strip(".,;:()")]
        if len(tokens) < 2:
            return False
        disallowed_tokens = {
            "request",
            "requests",
            "form",
            "forms",
            "staff",
            "initiatives",
            "calendar",
            "agendas",
            "minutes",
            "meeting",
            "meetings",
            "history",
            "office",
            "offices",
            "services",
            "portal",
            "open",
            "data",
        }
        lowered_tokens = {token.lower() for token in tokens}
        if lowered_tokens & disallowed_tokens:
            return False
        return any(any(character.isalpha() for character in token) for token in tokens)

    def _parse_role_prefixed_name(value: str) -> tuple[str, str] | None:
        normalized = _normalize_whitespace(value)
        lowered = normalized.lower()
        for role_prefix in sorted(role_prefixes, key=len, reverse=True):
            prefix_with_space = f"{role_prefix} "
            if not lowered.startswith(prefix_with_space.lower()):
                continue
            member_name = normalized[len(prefix_with_space) :].strip(" ,")
            if member_name.lower() in {"pro tem", "pro-tempore", "pro tempore"}:
                return None
            if not _looks_like_person_name(member_name):
                return None
            return member_name, role_prefix
        return None

    def _parse_name_with_role_suffix(value: str) -> tuple[str, str] | None:
        normalized = _normalize_whitespace(value)
        if "," not in normalized:
            return None
        member_name, role_suffix = [segment.strip() for segment in normalized.split(",", maxsplit=1)]
        if role_suffix == "" or not _looks_like_person_name(member_name):
            return None
        return member_name, role_suffix

    for link in soup.select("a[href]"):
        label = _normalize_whitespace(link.get_text(" ", strip=True))
        if label == "":
            continue
        role_prefixed = _parse_role_prefixed_name(label)
        if role_prefixed is not None:
            _add_candidate(role_prefixed[0], role_prefixed[1], link.get("href"))
            continue
        role_suffix = _parse_name_with_role_suffix(label)
        if role_suffix is not None:
            _add_candidate(role_suffix[0], role_suffix[1], link.get("href"))

    for text in soup.stripped_strings:
        label = _normalize_whitespace(text)
        if label == "":
            continue
        role_prefixed = _parse_role_prefixed_name(label)
        if role_prefixed is not None:
            _add_candidate(role_prefixed[0], role_prefixed[1], None)
            continue
        role_suffix = _parse_name_with_role_suffix(label)
        if role_suffix is not None:
            _add_candidate(role_suffix[0], role_suffix[1], None)

    return list(candidates.values())


def _strip_honorific(name: str) -> str:
    return re.sub(r"^(mr|ms|mrs|dr|hon)\.?\s+", "", _normalize_whitespace(name), flags=re.IGNORECASE).strip()


def _build_roster_row(
    *,
    member_name: str,
    role_label: str,
    division_name: str,
    source_url: str,
    href: str | None,
) -> NormalizedRosterRow:
    return NormalizedRosterRow(
        member_name=_normalize_whitespace(member_name).strip(".,;:"),
        role_label=_normalize_whitespace(role_label).strip(".,;:"),
        district_number=division_name,
        bio_url=_normalize_same_origin_url(href, source_url=source_url),
        portrait_url=None,
    )


def _parse_nc_municipal_council_rows(*, source_url: str, html: str) -> list[NormalizedRosterRow]:
    soup = BeautifulSoup(html, "html.parser")
    source_host = (urlparse(source_url).hostname or "").lower()
    division_by_host = {
        "raleighnc.gov": "Raleigh",
        "www.carync.gov": "Cary",
        "www.apexnc.org": "Apex",
        "www.hollyspringsnc.gov": "Holly Springs",
        "www.fuquay-varina.org": "Fuquay Varina",
        "www.wakeforestnc.gov": "Wake Forest",
        "www.garnernc.gov": "Garner",
        "www.morrisvillenc.gov": "Morrisville",
        "www.knightdalenc.gov": "Knightdale",
        "townofwendellnc.gov": "Wendell",
        "www.townofzebulon.org": "Zebulon",
        "www.rolesvillenc.gov": "Rolesville",
        "www.chapelhillnc.gov": "Chapel Hill",
        "www.carrboronc.gov": "Carrboro",
        "www.hillsboroughnc.gov": "Hillsborough",
    }
    division_name = division_by_host.get(source_host)
    if division_name is None:
        return []

    rows_by_name: dict[str, NormalizedRosterRow] = {}

    def _add_row(member_name: str, role_label: str, href: str | None) -> None:
        row = _build_roster_row(
            member_name=member_name,
            role_label=role_label,
            division_name=division_name,
            source_url=source_url,
            href=href,
        )
        if row.member_name == "" or row.role_label == "":
            return
        key = row.member_name.casefold()
        existing = rows_by_name.get(key)
        if existing is None:
            rows_by_name[key] = row
            return
        if existing.bio_url is None and row.bio_url is not None:
            rows_by_name[key] = row

    def _parse_council_prefixed_name(value: str) -> tuple[str, str] | None:
        normalized = _normalize_whitespace(value)
        prefixes = (
            ("Mayor Pro-Tempore ", "Mayor Pro Tem"),
            ("Mayor Pro Tempore ", "Mayor Pro Tem"),
            ("Mayor Pro Tem ", "Mayor Pro Tem"),
            ("Mayor ", "Mayor"),
            ("Council Member ", "Council Member"),
            ("Councilor ", "Council Member"),
            ("Commissioner ", "Commissioner"),
        )
        for prefix, role_label in prefixes:
            if not normalized.startswith(prefix):
                continue
            member_name = normalized[len(prefix) :].strip()
            if member_name == "":
                return None
            tokens = [token.strip(".,") for token in member_name.split(" ") if token.strip(".,")]
            if len(tokens) < 2 or len(tokens) > 6:
                return None
            if not all(any(character.isalpha() for character in token) for token in tokens):
                return None
            if any(token.lower() in {"and", "board", "council", "town"} for token in tokens):
                return None
            return member_name, role_label
        return None

    if source_host == "raleighnc.gov":
        for image in soup.select("img[alt]"):
            alt_text = _normalize_whitespace(image.get("alt", ""))
            member_name: str | None = None
            role_label: str | None = None
            if "," in alt_text:
                left, right = [segment.strip() for segment in alt_text.split(",", maxsplit=1)]
                if "council" in right.lower():
                    member_name = left
                    role_label = right
            elif alt_text.lower().startswith("mayor "):
                member_name = alt_text[len("Mayor ") :].strip()
                role_label = "Mayor"
            if member_name is None or role_label is None:
                continue
            link_parent = image.find_parent("a")
            _add_row(member_name, role_label, link_parent.get("href") if link_parent else None)

    if source_host == "www.apexnc.org":
        for heading in soup.select("h3"):
            parsed = _parse_council_prefixed_name(heading.get_text(" ", strip=True))
            if parsed is None:
                continue
            _add_row(parsed[0], parsed[1], None)

    if source_host == "www.carync.gov":
        for paragraph in soup.select("p"):
            link = paragraph.find("a", href=True)
            if link is None:
                continue
            full_text = _normalize_whitespace(paragraph.get_text(" ", strip=True))
            if "," not in full_text:
                continue
            member_name = _normalize_whitespace(link.get_text(" ", strip=True))
            _, role_label = [segment.strip() for segment in full_text.split(",", maxsplit=1)]
            if "representative" not in role_label.lower() and "mayor" not in role_label.lower():
                continue
            _add_row(member_name, role_label, link.get("href"))

    if source_host == "www.hollyspringsnc.gov":
        for heading in soup.select("h2"):
            member_name = _normalize_whitespace(heading.get_text(" ", strip=True))
            if not re.fullmatch(r"[A-Z .-]+", member_name):
                continue
            if member_name.lower() in {"meetings", "loading"}:
                continue
            detail_node = heading.find_next_sibling("p")
            detail_text = (
                _normalize_whitespace(detail_node.get_text(" ", strip=True)) if detail_node is not None else ""
            )
            if detail_text == "":
                continue
            role_label = "Council Member"
            if detail_text.lower().startswith("mayor pro tem"):
                role_label = "Mayor Pro Tem"
            elif detail_text.lower().startswith("mayor"):
                role_label = "Mayor"
            detail_link = detail_node.find("a", href=True) if detail_node is not None else None
            _add_row(member_name.title(), role_label, detail_link.get("href") if detail_link is not None else None)

    if source_host in {"www.fuquay-varina.org", "www.garnernc.gov"}:
        for heading in soup.select("h2, h3"):
            member_name = _normalize_whitespace(heading.get_text(" ", strip=True)).strip(".,")
            if member_name == "":
                continue
            if member_name.lower() in {"events", "contact", "meetings", "town board"}:
                continue
            detail_node = heading.find_next_sibling("p")
            if detail_node is None:
                continue
            detail_text = _normalize_whitespace(detail_node.get_text(" ", strip=True))
            if all(
                token not in detail_text.lower()
                for token in ("mayor", "commissioner", "council member", "@garnernc.gov")
            ):
                continue
            if "mayor pro" in detail_text.lower():
                role_label = "Mayor Pro Tem"
            elif "mayor" in detail_text.lower():
                role_label = "Mayor"
            elif "commissioner" in detail_text.lower():
                role_label = "Commissioner"
            else:
                role_label = "Council Member"
            detail_link = detail_node.find("a", href=True)
            _add_row(
                member_name.title() if member_name.isupper() else member_name,
                role_label,
                detail_link.get("href") if detail_link else None,
            )

    if source_host == "www.morrisvillenc.gov":
        for link in soup.select("a[href]"):
            parsed = _parse_council_prefixed_name(link.get_text(" ", strip=True))
            if parsed is None:
                continue
            _add_row(parsed[0], parsed[1], link.get("href"))

    if source_host == "www.knightdalenc.gov":
        for heading in soup.select("h3"):
            parsed = _parse_council_prefixed_name(heading.get_text(" ", strip=True))
            if parsed is None:
                continue
            _add_row(parsed[0], parsed[1], None)

    if source_host == "www.wakeforestnc.gov":
        for card in soup.select(".person-card"):
            name_node = card.select_one("h3, h2")
            if name_node is None:
                continue
            card_text = _normalize_whitespace(card.get_text(" ", strip=True)).lower()
            role_label = "Commissioner"
            if "mayor pro tem" in card_text:
                role_label = "Mayor Pro Tem"
            elif "mayor" in card_text:
                role_label = "Mayor"
            _add_row(_normalize_whitespace(name_node.get_text(" ", strip=True)), role_label, None)

    if source_host == "www.rolesvillenc.gov":
        for card in soup.select(".card.person"):
            name_node = card.select_one(".person__title")
            role_node = card.select_one(".person__job-title")
            if name_node is None or role_node is None:
                continue
            _add_row(
                _normalize_whitespace(name_node.get_text(" ", strip=True)),
                _normalize_whitespace(role_node.get_text(" ", strip=True)),
                card.select_one("a[href]").get("href") if card.select_one("a[href]") else None,
            )

    if source_host == "www.chapelhillnc.gov":
        for profile_link in soup.select("a.profile-list[href]"):
            name_node = profile_link.select_one("h2")
            role_node = profile_link.select_one(".position-title")
            if name_node is None or role_node is None:
                continue
            _add_row(
                _normalize_whitespace(name_node.get_text(" ", strip=True)),
                _normalize_whitespace(role_node.get_text(" ", strip=True)),
                profile_link.get("href"),
            )

    if source_host == "www.carrboronc.gov":
        for link in soup.select("a[href]"):
            parsed = _parse_council_prefixed_name(link.get_text(" ", strip=True))
            if parsed is None:
                continue
            _add_row(parsed[0], parsed[1], link.get("href"))

    if source_host == "www.hillsboroughnc.gov":
        for link in soup.select("a[href]"):
            parsed = _parse_council_prefixed_name(link.get_text(" ", strip=True))
            if parsed is None:
                continue
            _add_row(parsed[0], parsed[1], link.get("href"))

    if source_host == "townofwendellnc.gov":
        member_headings = [
            _normalize_whitespace(heading.get_text(" ", strip=True))
            for heading in soup.select("h2")
            if _normalize_whitespace(heading.get_text(" ", strip=True)).lower()
            not in {"town board", "contact", "popular links", "resources", "hours", "share this page"}
        ]
        role_order = ["Mayor", "Mayor Pro Tempore", "Commissioner", "Commissioner", "Commissioner", "Commissioner"]
        for member_name, role_label in zip(member_headings, role_order, strict=False):
            _add_row(member_name, role_label, None)

    if source_host == "www.townofzebulon.org":
        for paragraph in soup.select("p"):
            text = _normalize_whitespace(paragraph.get_text(" ", strip=True))
            if "our board is made up of" not in text.lower():
                continue
            mayor = re.search(r"Mayor\s+([A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){1,4})", text)
            if mayor is not None:
                _add_row(mayor.group(1), "Mayor", None)
            mayor_pro_tem = re.search(r"Mayor Pro Tem\s+([A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){1,4})", text)
            if mayor_pro_tem is not None:
                _add_row(mayor_pro_tem.group(1), "Mayor Pro Tem", None)
            commissioners = re.search(r"Commissioners?\s+(.+)$", text)
            if commissioners is not None:
                for commissioner_name in commissioners.group(1).replace(" and ", ", ").split(","):
                    cleaned = commissioner_name.strip(" .")
                    if cleaned:
                        _add_row(cleaned, "Commissioner", None)
            break

    if not rows_by_name:
        for member_name, role_label, href in _extract_roster_candidates(soup):
            _add_row(member_name, role_label or "Council Member", href)

    return list(rows_by_name.values())


def _extract_dps_school_board_members(soup: BeautifulSoup) -> list[tuple[str, str]]:
    members: list[tuple[str, str]] = []
    seen: set[str] = set()
    for card in soup.select(".card-content-container"):
        heading_node = card.select_one(".card-heading h1, .card-heading h2, .card-heading h3, .card-heading h4")
        heading_text = _normalize_whitespace(heading_node.get_text(" ", strip=True)) if heading_node is not None else ""
        details_node = card.select_one(".card-text")
        details_text = _normalize_whitespace(details_node.get_text(" ", strip=True)) if details_node is not None else ""
        email_link = card.select_one("a[href^='mailto:']")
        email_label = _normalize_whitespace(email_link.get_text(" ", strip=True)) if email_link is not None else ""

        member_name = ""
        if email_label.lower().startswith("email "):
            member_name = _strip_honorific(email_label.split(" ", maxsplit=1)[1])
        if member_name == "" and heading_text != "":
            member_name = _strip_honorific(heading_text.split(",", maxsplit=1)[0])
        if member_name == "":
            continue

        role_prefix = "School Board Member"
        heading_lower = heading_text.lower()
        if "vice chair" in heading_lower:
            role_prefix = "School Board Vice Chair"
        elif "chair" in heading_lower:
            role_prefix = "School Board Chair"

        district_match = re.search(r"((?:Consolidated )?District [A-Z0-9]+)", details_text)
        at_large_match = re.search(r"\bAt\s+Large\b", details_text, flags=re.IGNORECASE)
        role_label = role_prefix
        if district_match is not None:
            role_label = f"{role_prefix} {district_match.group(1)}"
        elif at_large_match is not None:
            role_label = f"{role_prefix} At-Large"

        key = member_name.casefold()
        if key in seen:
            continue
        seen.add(key)
        members.append((member_name, role_label))

    if members:
        return members

    for line in soup.get_text("\n", strip=True).split("\n"):
        normalized_line = _normalize_whitespace(line)
        if "Email " not in normalized_line:
            continue
        member_name = _strip_honorific(normalized_line.split("Email ", maxsplit=1)[1])
        if member_name == "":
            continue
        district_match = re.search(r"((?:Consolidated )?District [A-Z0-9]+)", normalized_line)
        if district_match is not None:
            role_label = f"School Board Member {district_match.group(1)}"
        elif re.search(r"\bAt\s+Large\b", normalized_line, flags=re.IGNORECASE):
            role_label = "School Board Member At-Large"
        else:
            role_label = "School Board Member"

        key = member_name.casefold()
        if key in seen:
            continue
        seen.add(key)
        members.append((member_name, role_label))
    return members


def _extract_wcpss_board_rows(soup: BeautifulSoup) -> list[tuple[str, str, str | None]]:
    rows: list[tuple[str, str, str | None]] = []
    for article in soup.select("article.fsBoard-53"):
        role_node = article.select_one(".fsTitle")
        role_label = (
            _normalize_whitespace(role_node.get_text(" ", strip=True))
            if role_node is not None
            else "School Board Member"
        )
        summary_name_node = article.select_one(".fsSummary strong")
        if summary_name_node is not None:
            member_name = _strip_honorific(summary_name_node.get_text(" ", strip=True))
        else:
            image = article.select_one("img[alt]")
            alt_value = _normalize_whitespace(image.get("alt", "")) if image is not None else ""
            member_name = (
                _strip_honorific(alt_value.split(",", maxsplit=1)[0])
                if "," in alt_value
                else _strip_honorific(alt_value)
            )
        link = article.select_one("a.fsPostLink[data-slug]")
        href = None
        if link is not None:
            slug = _normalize_whitespace(link.get("data-slug", ""))
            if slug != "":
                href = f"/{slug.lstrip('/')}"
        if member_name == "":
            continue
        rows.append((member_name, role_label, href))
    return rows


def _extract_finalsite_constituent_rows(soup: BeautifulSoup) -> list[tuple[str, str, str | None]]:
    rows: list[tuple[str, str, str | None]] = []
    for item in soup.select(".fsConstituentItem"):
        name_node = item.select_one(".fsFullName")
        if name_node is None:
            continue
        role_node = item.select_one(".fsTitles")
        link_node = item.select_one(".fsConstituentProfileLink[href]")
        member_name = _strip_honorific(name_node.get_text(" ", strip=True))
        role_label = (
            _normalize_whitespace(role_node.get_text(" ", strip=True))
            if role_node is not None
            else "School Board Member"
        )
        href = link_node.get("href") if link_node is not None and link_node.get("href") != "#" else None
        if member_name == "":
            continue
        rows.append((member_name, role_label, href))
    return rows


def _parse_nc_school_board_rows(*, source_url: str, html: str) -> list[NormalizedRosterRow]:
    soup = BeautifulSoup(html, "html.parser")
    source_host = (urlparse(source_url).hostname or "").lower()
    division_by_host = {
        "www.dpsnc.net": "Durham Public Schools",
        "www.wcpss.net": "Wake County Public School System",
        "www.orangecountyfirst.com": "Orange County Schools",
        "www.chccs.org": "Chapel Hill-Carrboro City Schools",
    }
    division_name = division_by_host.get(source_host)
    if division_name is None:
        return []

    rows_by_name: dict[str, NormalizedRosterRow] = {}

    def _add_row(member_name: str, role_label: str, href: str | None) -> None:
        row = _build_roster_row(
            member_name=member_name,
            role_label=role_label,
            division_name=division_name,
            source_url=source_url,
            href=href,
        )
        if row.member_name == "" or row.role_label == "":
            return
        key = row.member_name.casefold()
        if key not in rows_by_name:
            rows_by_name[key] = row

    if source_host == "www.dpsnc.net":
        for member_name, role_label in _extract_dps_school_board_members(soup):
            _add_row(member_name, role_label, None)

    if source_host == "www.wcpss.net":
        for member_name, role_label, href in _extract_wcpss_board_rows(soup):
            _add_row(member_name, role_label, href)

    if source_host in {"www.orangecountyfirst.com", "www.chccs.org"}:
        for member_name, role_label, href in _extract_finalsite_constituent_rows(soup):
            _add_row(member_name, role_label, href)

    if not rows_by_name:
        for member_name, role_label, href in _extract_roster_candidates(soup):
            fallback_role = role_label or "School Board Member"
            if "district" not in fallback_role.lower() and "at-large" not in fallback_role.lower():
                fallback_role = f"School Board Member {fallback_role}"
            _add_row(member_name, fallback_role, href)

    return list(rows_by_name.values())


PARSER_REGISTRY: dict[str, Callable[..., list[NormalizedRosterRow]]] = {
    _DURHAM_BODY_KEY: _parse_durham_member_rows,
    _NC_HOUSE_BODY_KEY: _parse_nc_house_rows,
    _US_HOUSE_NC_BODY_KEY: _parse_us_house_nc_rows,
    _US_SENATE_NC_CLASS_II_BODY_KEY: lambda *, source_url, html: _parse_us_senate_nc_rows(
        source_url=source_url,
        html=html,
        senate_class="2",
    ),
    _US_SENATE_NC_CLASS_III_BODY_KEY: lambda *, source_url, html: _parse_us_senate_nc_rows(
        source_url=source_url,
        html=html,
        senate_class="3",
    ),
    _NC_SENATE_BODY_KEY: _parse_nc_senate_rows,
    _NC_GOV_BODY_KEY: lambda *, source_url, html: _parse_council_of_state_rows(
        body_key=_NC_GOV_BODY_KEY,
        source_url=source_url,
        html=html,
    ),
    _NC_LT_GOV_BODY_KEY: lambda *, source_url, html: _parse_council_of_state_rows(
        body_key=_NC_LT_GOV_BODY_KEY,
        source_url=source_url,
        html=html,
    ),
    _NC_ATTORNEY_GENERAL_BODY_KEY: lambda *, source_url, html: _parse_council_of_state_rows(
        body_key=_NC_ATTORNEY_GENERAL_BODY_KEY,
        source_url=source_url,
        html=html,
    ),
    _NC_SEC_OF_STATE_BODY_KEY: lambda *, source_url, html: _parse_council_of_state_rows(
        body_key=_NC_SEC_OF_STATE_BODY_KEY,
        source_url=source_url,
        html=html,
    ),
    _NC_TREASURER_BODY_KEY: lambda *, source_url, html: _parse_council_of_state_rows(
        body_key=_NC_TREASURER_BODY_KEY,
        source_url=source_url,
        html=html,
    ),
    _NC_AUDITOR_BODY_KEY: lambda *, source_url, html: _parse_council_of_state_rows(
        body_key=_NC_AUDITOR_BODY_KEY,
        source_url=source_url,
        html=html,
    ),
    _NC_SUPT_PUB_INSTR_BODY_KEY: lambda *, source_url, html: _parse_council_of_state_rows(
        body_key=_NC_SUPT_PUB_INSTR_BODY_KEY,
        source_url=source_url,
        html=html,
    ),
    _NC_AG_COMMISSIONER_BODY_KEY: lambda *, source_url, html: _parse_council_of_state_rows(
        body_key=_NC_AG_COMMISSIONER_BODY_KEY,
        source_url=source_url,
        html=html,
    ),
    _NC_INS_COMMISSIONER_BODY_KEY: lambda *, source_url, html: _parse_council_of_state_rows(
        body_key=_NC_INS_COMMISSIONER_BODY_KEY,
        source_url=source_url,
        html=html,
    ),
    _NC_LABOR_COMMISSIONER_BODY_KEY: lambda *, source_url, html: _parse_council_of_state_rows(
        body_key=_NC_LABOR_COMMISSIONER_BODY_KEY,
        source_url=source_url,
        html=html,
    ),
    _NC_SUPREME_COURT_BODY_KEY: lambda *, source_url, html: _parse_judicial_rows(
        body_key=_NC_SUPREME_COURT_BODY_KEY,
        source_url=source_url,
        html=html,
    ),
    _NC_COURT_OF_APPEALS_BODY_KEY: lambda *, source_url, html: _parse_judicial_rows(
        body_key=_NC_COURT_OF_APPEALS_BODY_KEY,
        source_url=source_url,
        html=html,
    ),
}


def parse_roster_rows(*, body_key: str, source_url: str, html: str) -> list[NormalizedRosterRow]:
    """Parse one roster page into shared normalized rows based on notes.body_key."""
    registry_parser = PARSER_REGISTRY.get(body_key)
    if registry_parser is not None:
        return registry_parser(source_url=source_url, html=html)
    if body_key == _NC_SHERIFFS_BODY_KEY:
        return _parse_nc_sheriffs_rows(source_url=source_url, html=html)
    if body_key == _NC_REGISTERS_OF_DEEDS_BODY_KEY:
        return _parse_nc_registers_of_deeds_rows(source_url=source_url, html=html)
    if body_key == _NC_COUNTY_COMMISSIONERS_BODY_KEY:
        return _parse_nc_county_commissioners_rows(source_url=source_url, html=html)
    if body_key == _NC_SOIL_WATER_SUPERVISORS_BODY_KEY:
        return _parse_nc_soil_water_supervisors_rows(source_url=source_url, html=html)
    if body_key == _NC_MUNICIPAL_COUNCIL_BODY_KEY:
        return _parse_nc_municipal_council_rows(source_url=source_url, html=html)
    if body_key == _NC_SCHOOL_BOARD_BODY_KEY:
        return _parse_nc_school_board_rows(source_url=source_url, html=html)
    raise ValueError(f"Unsupported body_key for official roster parsing: {body_key}")
