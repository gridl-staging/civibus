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

const BRANDING = {
  name: "Civibus",
  appTitle: "Civibus",
  stageLabel: "Public Beta",
  tagline: "Universal public-records intelligence"
} as const;

const REPORTING_LINK = {
  label: "Report a data issue",
  href: "mailto:team@civibus.org?subject=Civibus%20data%20issue"
} as const;

export const APP_SHELL = {
  branding: BRANDING,
  shellNavigation: [
    { label: "Home", href: "/" },
    { label: "Search", href: "/search" },
    { label: "Candidates", href: "/candidates" },
    { label: "Committees", href: "/committees" },
    { label: "Congress", href: "/congress" },
    { label: "Developers", href: "/developers" },
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
        "Federal Schedule A scope, donor grouping, coverage, and freshness methodology for Civibus money views."
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
    },
    about: {
      title: `About | ${BRANDING.name}`,
      description:
        `Learn what ${BRANDING.name} is, what federal-first v1 covers, and the source-linked boundaries for its public-records presentation.`
    },
    contact: {
      title: `Contact | ${BRANDING.name}`,
      description:
        `Report a ${BRANDING.name} data issue through the shared reporting link without a contact form or page-local submission flow.`
    },
    privacy: {
      title: `Privacy | ${BRANDING.name}`,
      description:
        `Review the privacy-relevant behavior ${BRANDING.name} can substantiate from frontend integration scans and API logging tests.`
    }
  },
  reportingLink: REPORTING_LINK,
  footer: {
    links: [
      { label: "Methodology", href: "/methodology" },
      { label: "Public API", href: "/developers" },
      REPORTING_LINK
    ],
    trustPageLinks: [
      { label: "About", href: "/about" },
      { label: "Contact", href: "/contact" },
      { label: "Privacy", href: "/privacy" }
    ]
  },
  trustPages: {
    about: {
      heading: "About",
      sections: [
        {
          heading: "Identity",
          paragraphs: [
            `${BRANDING.name} is a public-records intelligence platform that makes fragmented government records searchable and connects records across sources.`
          ]
        },
        {
          heading: "Federal-first v1",
          paragraphs: [
            "The launch scope is 543 elected federal seats: 435 House seats, 100 Senate seats, 6 non-voting delegate seats, the President, and the Vice President.",
            "Profiles pair federal officeholder records with FEC money summaries and Schedule E independent expenditures for and against officials."
          ]
        },
        {
          heading: "Presentation boundaries",
          paragraphs: [
            "Displayed data is nonpartisan, source-linked, and presented without editorial commentary."
          ]
        },
        {
          heading: "Parked work",
          paragraphs: [
            "Parked state, city, post-v1 race and challenger expansion, and non-campaign-finance domains remain future work until explicitly scheduled after v1."
          ]
        }
      ]
    },
    contact: {
      heading: "Contact",
      paragraphs: [
        `Use ${REPORTING_LINK.label.toLowerCase()} to report a data issue through the existing shared contact path.`
      ],
      action: REPORTING_LINK
    },
    privacy: {
      heading: "Privacy",
      sections: [
        {
          heading: "Evidence boundary",
          paragraphs: [
            "This page describes tested application behavior from scanned frontend paths and api/test_logging.py."
          ]
        },
        {
          heading: "Application analytics",
          paragraphs: [
            "The scanned frontend paths contain no analytics or telemetry integration."
          ]
        },
        {
          heading: "API request logging",
          paragraphs: [
            "Structured API request logs tested in api/test_logging.py include method, path, status, request ID, and duration.",
            "The recorded path omits query-string values."
          ]
        },
        {
          heading: "Error handling",
          paragraphs: [
            "Unhandled API errors tested in api/test_logging.py return Internal Server Error as generic 500 response bodies.",
            "Structured log records omit exception messages, tracebacks, stack traces, and exc_info."
          ]
        }
      ]
    }
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
      "This static screen is rendered from APP_SHELL.methodology in web/src/lib/config/app.ts and summarizes the federal-first money-view methodology.",
    sections: [
      {
        testId: "methodology-schedule-a-scope",
        heading: "Schedule A scope",
        paragraphs: [
          "Loaded itemized individual contribution rows cover cycles 2022, 2024, and 2026 with transaction_date >= 2022-01-01, transaction_type LIKE '1%', contributor_entity_type = 'IND', no memo rows, no terminated amendments, and no superseded source records.",
          "Loaded Schedule A values are floors for the loaded current-officeholder committee slice, not full-universe FEC Schedule A totals."
        ],
        links: []
      },
      {
        testId: "methodology-donor-grouping",
        heading: "Donor grouping",
        paragraphs: [
          "Donor search groups by contributor_name, contributor_employer, contributor_occupation, contributor_city, contributor_state, and normalized_zip5, and collapses to one canonical donor identity only when the backend resolves exactly one canonical donor identity. Public official top-contributor rows remain unresolved raw identities grouped only by contributor_name_raw, contributor_city, and contributor_state."
        ],
        links: []
      },
      {
        testId: "methodology-coverage",
        heading: "Coverage",
        paragraphs: [
          "Detailed coverage and source inventories live on /coverage and /data-sources; this page links users there instead of duplicating those tables.",
          "The public employer-industry benchmark currently has 837 classified and 13,487 unknown employer-industry values, an API-derived 5.8% classified benchmark."
        ],
        links: [
          { label: "Coverage", href: "/coverage" },
          { label: "Data sources", href: "/data-sources" }
        ]
      },
      {
        testId: "methodology-freshness",
        heading: "Freshness",
        paragraphs: [
          "Federal refreshes are scheduled weekly.",
          "FEC bulk freshness health is bounded at 7d. Donor-rollup health is bounded at 7d6h. Donor-search serving freshness is bounded at 8d."
        ],
        links: []
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
