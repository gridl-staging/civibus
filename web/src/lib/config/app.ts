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
    { label: "Candidates", href: "/candidates" },
    { label: "Committees", href: "/committees" },
    { label: "Methodology", href: "/methodology" }
  ],
  staticRoutes: {
    home: {
      title: "Civibus | Public-records intelligence for journalists",
      description:
        "Investigate campaign-finance, civic office, and property records with source-linked evidence in Civibus search."
    },
    methodology: {
      title: "Methodology | Civibus",
      description:
        "Coverage scope, confidence labels, and source guidance for campaign-finance, civic office, and property records."
    }
  },
  reportingLink: REPORTING_LINK,
  footer: {
    links: [{ label: "Methodology", href: "/methodology" }, REPORTING_LINK]
  },
  landing: {
    eyebrow: "Public-records intelligence for journalists",
    heading: "Trace people, organizations, committees, and offices across jurisdictions.",
    body:
      "Civibus is a universal public-records intelligence platform with shared search and source-linked evidence.",
    coverageHeading: "Coverage at a glance",
    coverageSummary:
      "Coverage spans federal and state campaign-finance records, civic offices, and a property pilot. See methodology for current operational scope by jurisdiction.",
    actions: [
      {
        label: "Browse candidates",
        href: "/candidates",
        description: "Review candidate records and filings by jurisdiction."
      },
      {
        label: "Browse committees",
        href: "/committees",
        description: "Inspect committee registrations and campaign-finance activity."
      },
      {
        label: "Understand coverage",
        href: "/methodology",
        description:
          "Read data freshness policy, entity resolution methods, and source-linking standards."
      }
    ],
    cta: {
      label: "Start with search",
      href: "/search",
      description:
        "Use the shared entity search to start from a person, organization, office, or address."
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
          "Every surfaced record is tied to provenance metadata and source links so users can trace claims back to official filings or source systems. Civibus prioritizes verifiable evidence over inferred narrative summaries."
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
