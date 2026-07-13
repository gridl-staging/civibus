export const MAP_PAGE_LEVELS = ["state", "county"] as const;

export type MapPageLevel = (typeof MAP_PAGE_LEVELS)[number];

export const CIVIC_GEOMETRY_LEVELS = ["state", "county", "congressional_district"] as const;

export type CivicGeometryLevel = (typeof CIVIC_GEOMETRY_LEVELS)[number];

export const MAP_LAYER_IDS = [
  "nc_statewide_boundary",
  "nc_county_boundaries",
  "nc_congressional_districts"
] as const;

export type MapLayerId = (typeof MAP_LAYER_IDS)[number];

export type MapLayer = {
  id: MapLayerId;
  level: CivicGeometryLevel;
  divisionType: "statewide" | "county" | "congressional_district";
  alwaysOn: boolean;
  label: string;
  defaultVisible: boolean;
  applicableLevels: readonly MapPageLevel[];
};

export type MapLayerVisibility = Record<MapLayerId, boolean>;

export const MAP_LAYERS = [
  {
    id: "nc_statewide_boundary",
    level: "state",
    divisionType: "statewide",
    alwaysOn: true,
    label: "State boundary",
    defaultVisible: true,
    applicableLevels: ["state"]
  },
  {
    id: "nc_county_boundaries",
    level: "county",
    divisionType: "county",
    alwaysOn: false,
    label: "County boundaries",
    defaultVisible: true,
    applicableLevels: ["state", "county"]
  },
  {
    id: "nc_congressional_districts",
    level: "congressional_district",
    divisionType: "congressional_district",
    alwaysOn: false,
    label: "Congressional districts",
    defaultVisible: false,
    applicableLevels: ["state", "county"]
  }
] as const satisfies readonly MapLayer[];

export function getMapLayersForLevel(pageLevel: MapPageLevel): readonly MapLayer[] {
  return MAP_LAYERS.filter((layer) =>
    (layer.applicableLevels as readonly MapPageLevel[]).includes(pageLevel)
  );
}

export function buildMapLayerVisibilityDefaults(pageLevel: MapPageLevel): MapLayerVisibility {
  const defaults: MapLayerVisibility = {
    nc_statewide_boundary: false,
    nc_county_boundaries: false,
    nc_congressional_districts: false
  };

  for (const layer of getMapLayersForLevel(pageLevel)) {
    defaults[layer.id] = layer.alwaysOn || layer.defaultVisible;
  }

  return defaults;
}

const REPORTING_LINK = {
  label: "Report a data issue",
  href: "mailto:team@civibus.org?subject=Civibus%20data%20issue"
} as const;

export const APP_SHELL = {
  branding: {
    name: "Civibus",
    appTitle: "Civibus",
    stageLabel: "Public Beta",
    tagline: "Universal public-records intelligence"
  },
  shellNavigation: [
    { label: "Home", href: "/" },
    { label: "Search", href: "/search" },
    { label: "Donor Lookup", href: "/donors" },
    { label: "Congress", href: "/congress" },
    { label: "Methodology", href: "/methodology" }
  ],
  staticRoutes: {
    home: {
      title: "Civibus | Federal public-records intelligence",
      description:
        "Browse federal-first Civibus profiles for Congress and the White House with source-linked FEC money summaries and independent expenditures."
    },
    methodology: {
      title: "Methodology | Civibus",
      description:
        "Coverage scope, confidence labels, and source guidance for campaign-finance, civic office, and property records."
    },
    calendar: {
      title: "Election Calendar | Civibus",
      description:
        "Track upcoming elections with contest-level counts and linked civic coverage across supported jurisdictions."
    },
    coverage: {
      title: "Coverage Registry | Civibus",
      description:
        "Review runtime coverage registry rows grouped by domain and jurisdiction with latest pull timestamps."
    },
    dataSources: {
      title: "Data Sources | Civibus",
      description:
        "Inspect runtime data-source metadata, pull status, and source-record pointers from the backend registry."
    },
    developers: {
      title: "Public API | Civibus",
      description:
        "Static reference for developers and journalists migrating from OpenSecrets or ProPublica APIs to Civibus's nonpartisan, source-linked federal public-record endpoints."
    }
  },
  reportingLink: REPORTING_LINK,
  footer: {
    links: [
      { label: "Methodology", href: "/methodology" },
      { label: "Public API", href: "/developers" },
      REPORTING_LINK
    ]
  },
  landing: {
    eyebrow: "Federal-first public records",
    heading: "Follow money around Congress and the White House.",
    body:
      "Civibus v1 covers 543 elected federal seats: 435 House seats, 100 Senate seats, 6 non-voting delegate seats, the President, and the Vice President. Public directory profiles appear for current officeholders; documented vacancies reduce the live officeholder count until seats are filled.",
    coverageHeading: "Federal scope",
    coverageSummary:
      "Current launch scope is the 543 elected federal seats, with live profiles for current officeholders and documented vacancies excluded from the live official count until filled. State, city, property, candidate-list, and committee-list breadth is not advertised from the homepage.",
    mapUnsupportedLabel: "Coverage not yet available",
    actions: [
      {
        label: "Search",
        href: "/search",
        description: "Search source-linked federal people, offices, committees, and filings."
      },
      {
        label: "Methodology",
        href: "/methodology",
        description: "Read source, refresh, and coverage methods for the federal-first dataset."
      }
    ],
    cta: {
      label: "Browse Congress",
      href: "/congress",
      description: "Open the federal directory for members of Congress and delegates."
    }
  },
  methodology: {
    heading: "Methodology",
    coverageSummary:
      "Civibus combines campaign-finance, civic office, and property records in one search experience. Coverage varies by jurisdiction and is refreshed based on source cadence.",
    sections: [
      {
        heading: "Data freshness policy",
        body:
          "Production support requires data that can be refreshed at least weekly near elections, with daily updates preferred. Sources that only publish annual or quarterly exports are not treated as fully launch-ready without a supplementary path."
      },
      {
        heading: "Entity resolution methodology",
        body:
          "Entity resolution uses probabilistic matching with confidence tiers derived from model scores. High-confidence matches can be auto-merged while lower-confidence links remain reviewable so users can inspect uncertainty."
      },
      {
        heading: "Source-linking and evidence",
        body:
          "Every surfaced record is tied to provenance metadata and source links so users can trace claims back to official filings or source systems. Civibus prioritizes verifiable evidence over inferred narrative summaries. Person-page Top employers aggregate raw employer names from itemized individual contributions; they are not industry- or sector-coded."
      }
    ],
    confidenceHeading: "Entity resolution confidence labels",
    confidenceLabels: [
      {
        label: "match",
        description: "Confidence >= 0.95. Auto-merge threshold."
      },
      {
        label: "probable_match",
        description: "Confidence from 0.80 to <0.95. Likely same entity and review-worthy."
      },
      {
        label: "possible_match",
        description: "Confidence from 0.60 to <0.80. Candidate link with lower confidence."
      }
    ]
  }
} as const;
