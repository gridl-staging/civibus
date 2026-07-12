
from __future__ import annotations

from dataclasses import dataclass

from core.types.python.models import DataSource
from domains.civics.loaders.official_rosters.source_registry import (
    RosterSourceMetadata,
    list_nc_roster_source_metadata,
)


@dataclass(frozen=True, slots=True)
class RosterSourceTemplate:

    registry_source_id: str
    name: str
    source_url: str
    body_key: str
    data_source_jurisdiction: str = "state/NC"
    refresh_job_key: str | None = None
    refresh_jurisdiction: str | None = None

    @property
    def notes_payload(self) -> dict[str, object]:
        return {
            "roster_source": True,
            "registry_source_id": self.registry_source_id,
            "body_key": self.body_key,
        }

    def as_data_source(self) -> DataSource:
        return DataSource(
            domain="civics",
            jurisdiction=self.data_source_jurisdiction,
            name=self.name,
            source_url=self.source_url,
            source_format="html",
            notes=self.notes_json,
        )

    @property
    def notes_json(self) -> str:
        import json

        return json.dumps(self.notes_payload, sort_keys=True)


_NC_DURHAM_CITY_COUNCIL_ROSTER = RosterSourceTemplate(
    registry_source_id="nc_durham_city_council_roster",
    name="Durham City Council Official Roster",
    source_url="https://www.durhamnc.gov/1396/City-Council-Members",
    body_key="durham_city_council",
)

_NC_GENERAL_ASSEMBLY_HOUSE_ROSTER = RosterSourceTemplate(
    registry_source_id="nc_general_assembly_house_roster",
    name="North Carolina House Official Roster",
    source_url="https://www.ncleg.gov/Members/MemberList/H",
    body_key="nc_house",
)

_US_HOUSE_NC_ROSTER = RosterSourceTemplate(
    registry_source_id="us_house_nc",
    name="US House Officeholder Directory (NC)",
    source_url="https://clerk.house.gov/xml/lists/MemberData.xml",
    body_key="us_house_nc",
    data_source_jurisdiction="federal/officeholder/house",
    refresh_job_key="civic-rosters-us-house-nc",
    refresh_jurisdiction="federal/officeholder/house",
)

_US_SENATE_NC_CLASS_II_ROSTER = RosterSourceTemplate(
    registry_source_id="us_senate_nc_class_ii",
    name="US Senate Officeholder Directory (NC Class II)",
    source_url="https://www.senate.gov/general/contact_information/senators_cfm.xml",
    body_key="us_senate_nc_class_ii",
    data_source_jurisdiction="federal/officeholder/senate",
    refresh_job_key="civic-rosters-us-senate-nc-ii",
    refresh_jurisdiction="federal/officeholder/senate",
)

_US_SENATE_NC_CLASS_III_ROSTER = RosterSourceTemplate(
    registry_source_id="us_senate_nc_class_iii",
    name="US Senate Officeholder Directory (NC Class III)",
    source_url="https://www.senate.gov/general/contact_information/senators_cfm.xml",
    body_key="us_senate_nc_class_iii",
    data_source_jurisdiction="federal/officeholder/senate",
    refresh_job_key="civic-rosters-us-senate-nc-iii",
    refresh_jurisdiction="federal/officeholder/senate",
)

_NC_SENATE_ROSTER = RosterSourceTemplate(
    registry_source_id="nc_senate",
    name="NC State Senate Roster",
    source_url="https://www.ncleg.gov/Members/MemberList/S",
    body_key="nc_senate",
    data_source_jurisdiction="states/NC",
    refresh_job_key="civic-rosters-nc-senate",
    refresh_jurisdiction="states/NC",
)

_NC_GOVERNOR_ROSTER = RosterSourceTemplate(
    registry_source_id="nc_gov",
    name="NC Governor Roster",
    source_url="https://governor.nc.gov/",
    body_key="nc_gov",
    data_source_jurisdiction="states/NC",
    refresh_job_key="civic-rosters-council-of-state-gov",
    refresh_jurisdiction="states/NC",
)

_NC_LT_GOVERNOR_ROSTER = RosterSourceTemplate(
    registry_source_id="nc_lt_gov",
    name="NC Lieutenant Governor Roster",
    source_url="https://ltgov.nc.gov/",
    body_key="nc_lt_gov",
    data_source_jurisdiction="states/NC",
    refresh_job_key="civic-rosters-council-of-state-lt-gov",
    refresh_jurisdiction="states/NC",
)

_NC_ATTORNEY_GENERAL_ROSTER = RosterSourceTemplate(
    registry_source_id="nc_attorney_general",
    name="NC Attorney General Roster",
    source_url="https://ncdoj.gov/",
    body_key="nc_attorney_general",
    data_source_jurisdiction="states/NC",
    refresh_job_key="civic-rosters-council-of-state-ag",
    refresh_jurisdiction="states/NC",
)

_NC_SECRETARY_OF_STATE_ROSTER = RosterSourceTemplate(
    registry_source_id="nc_sec_of_state",
    name="NC Secretary of State Roster",
    source_url="https://www.sosnc.gov/",
    body_key="nc_sec_of_state",
    data_source_jurisdiction="states/NC",
    refresh_job_key="civic-rosters-council-of-state-sos",
    refresh_jurisdiction="states/NC",
)

_NC_TREASURER_ROSTER = RosterSourceTemplate(
    registry_source_id="nc_treasurer",
    name="NC Treasurer Roster",
    source_url="https://www.nctreasurer.gov/",
    body_key="nc_treasurer",
    data_source_jurisdiction="states/NC",
    refresh_job_key="civic-rosters-council-of-state-treasurer",
    refresh_jurisdiction="states/NC",
)

_NC_AUDITOR_ROSTER = RosterSourceTemplate(
    registry_source_id="nc_auditor",
    name="NC Auditor Roster",
    source_url="https://www.auditor.nc.gov/",
    body_key="nc_auditor",
    data_source_jurisdiction="states/NC",
    refresh_job_key="civic-rosters-council-of-state-auditor",
    refresh_jurisdiction="states/NC",
)

_NC_SUPERINTENDENT_ROSTER = RosterSourceTemplate(
    registry_source_id="nc_supt_pub_instr",
    name="NC Superintendent of Public Instruction Roster",
    source_url="https://www.dpi.nc.gov/about-dpi/state-superintendent-public-instruction",
    body_key="nc_supt_pub_instr",
    data_source_jurisdiction="states/NC",
    refresh_job_key="civic-rosters-council-of-state-supt",
    refresh_jurisdiction="states/NC",
)

_NC_AGRICULTURE_COMMISSIONER_ROSTER = RosterSourceTemplate(
    registry_source_id="nc_ag_commissioner",
    name="NC Commissioner of Agriculture Roster",
    source_url="https://www.ncagr.gov/",
    body_key="nc_ag_commissioner",
    data_source_jurisdiction="states/NC",
    refresh_job_key="civic-rosters-council-of-state-ag-comm",
    refresh_jurisdiction="states/NC",
)

_NC_INSURANCE_COMMISSIONER_ROSTER = RosterSourceTemplate(
    registry_source_id="nc_ins_commissioner",
    name="NC Commissioner of Insurance Roster",
    source_url="https://www.ncdoi.gov/",
    body_key="nc_ins_commissioner",
    data_source_jurisdiction="states/NC",
    refresh_job_key="civic-rosters-council-of-state-ins-comm",
    refresh_jurisdiction="states/NC",
)

_NC_LABOR_COMMISSIONER_ROSTER = RosterSourceTemplate(
    registry_source_id="nc_labor_commissioner",
    name="NC Commissioner of Labor Roster",
    source_url="https://www.labor.nc.gov/",
    body_key="nc_labor_commissioner",
    data_source_jurisdiction="states/NC",
    refresh_job_key="civic-rosters-council-of-state-labor-comm",
    refresh_jurisdiction="states/NC",
)

_NC_SUPREME_COURT_ROSTER = RosterSourceTemplate(
    registry_source_id="nc_supreme_court",
    name="NC Supreme Court Roster",
    source_url="https://www.nccourts.gov/courts/supreme-court/meet-the-justices",
    body_key="nc_supreme_court",
    data_source_jurisdiction="states/NC",
    refresh_job_key="civic-rosters-nc-supreme",
    refresh_jurisdiction="states/NC",
)

_NC_COURT_OF_APPEALS_ROSTER = RosterSourceTemplate(
    registry_source_id="nc_court_of_appeals",
    name="NC Court of Appeals Roster",
    source_url="https://www.nccourts.gov/courts/court-of-appeals/biographies-of-the-judges",
    body_key="nc_court_of_appeals",
    data_source_jurisdiction="states/NC",
    refresh_job_key="civic-rosters-nc-appeals",
    refresh_jurisdiction="states/NC",
)

_NC_SUPERIOR_COURT_JUDGE_ROSTER = RosterSourceTemplate(
    registry_source_id="nc_superior_court_judge_roster",
    name="North Carolina Superior Court Judges Official Roster",
    source_url="https://www.nccourts.gov/judicial-directory?contains=judge&field_judicial_group_target_id=560&field_county_target_id=All&field_district_target_id=All",
    body_key="nc_superior_court_judge",
)

_NC_DISTRICT_COURT_JUDGE_ROSTER = RosterSourceTemplate(
    registry_source_id="nc_district_court_judge_roster",
    name="North Carolina District Court Judges Official Roster",
    source_url="https://www.nccourts.gov/judicial-directory?contains=judge&field_judicial_group_target_id=555&field_county_target_id=All&field_district_target_id=All",
    body_key="nc_district_court_judge",
)

_NC_CLERK_OF_SUPERIOR_COURT_ROSTER = RosterSourceTemplate(
    registry_source_id="nc_clerk_of_superior_court_roster",
    name="North Carolina Clerks of Superior Court Official Roster",
    source_url="https://www.nccourts.gov/judicial-directory?contains=clerk+of+superior+court&field_judicial_group_target_id=556&field_county_target_id=All&field_district_target_id=All",
    body_key="nc_clerk_of_superior_court",
)

_NC_DISTRICT_ATTORNEY_ROSTER = RosterSourceTemplate(
    registry_source_id="nc_district_attorney_roster",
    name="North Carolina District Attorneys Official Roster",
    source_url="https://www.nccourts.gov/judicial-directory/district-attorneys",
    body_key="nc_district_attorney",
)

_STATIC_ROSTER_SOURCE_TEMPLATES = (
    _NC_DURHAM_CITY_COUNCIL_ROSTER,
    _NC_GENERAL_ASSEMBLY_HOUSE_ROSTER,
    _US_HOUSE_NC_ROSTER,
    _US_SENATE_NC_CLASS_II_ROSTER,
    _US_SENATE_NC_CLASS_III_ROSTER,
    _NC_SENATE_ROSTER,
    _NC_GOVERNOR_ROSTER,
    _NC_LT_GOVERNOR_ROSTER,
    _NC_ATTORNEY_GENERAL_ROSTER,
    _NC_SECRETARY_OF_STATE_ROSTER,
    _NC_TREASURER_ROSTER,
    _NC_AUDITOR_ROSTER,
    _NC_SUPERINTENDENT_ROSTER,
    _NC_AGRICULTURE_COMMISSIONER_ROSTER,
    _NC_INSURANCE_COMMISSIONER_ROSTER,
    _NC_LABOR_COMMISSIONER_ROSTER,
    _NC_SUPREME_COURT_ROSTER,
    _NC_COURT_OF_APPEALS_ROSTER,
    _NC_SUPERIOR_COURT_JUDGE_ROSTER,
    _NC_DISTRICT_COURT_JUDGE_ROSTER,
    _NC_CLERK_OF_SUPERIOR_COURT_ROSTER,
    _NC_DISTRICT_ATTORNEY_ROSTER,
)


def _registry_backed_template(
    metadata: RosterSourceMetadata,
    *,
    existing_template: RosterSourceTemplate | None,
) -> RosterSourceTemplate:
    return RosterSourceTemplate(
        registry_source_id=metadata.source_id,
        name=metadata.name,
        source_url=metadata.source_url,
        body_key=metadata.body_key,
        data_source_jurisdiction=metadata.jurisdiction,
        refresh_job_key=None if existing_template is None else existing_template.refresh_job_key,
        refresh_jurisdiction=None if existing_template is None else existing_template.refresh_jurisdiction,
    )


def roster_source_templates() -> tuple[RosterSourceTemplate, ...]:
    templates_by_source_id = {template.registry_source_id: template for template in _STATIC_ROSTER_SOURCE_TEMPLATES}
    for metadata in list_nc_roster_source_metadata():
        existing_template = templates_by_source_id.get(metadata.source_id)
        templates_by_source_id[metadata.source_id] = _registry_backed_template(
            metadata,
            existing_template=existing_template,
        )
    return tuple(templates_by_source_id[source_id] for source_id in sorted(templates_by_source_id))


def civic_roster_refresh_templates() -> tuple[RosterSourceTemplate, ...]:
    return tuple(template for template in roster_source_templates() if template.refresh_job_key is not None)
