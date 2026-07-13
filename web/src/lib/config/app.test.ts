import { describe, expect, it } from 'vitest';
import { APP_SHELL, MAP_LAYERS } from './app';

describe('APP_SHELL shared static-route contract', () => {
  it('keeps shell branding and default app title in shared config', () => {
    expect(APP_SHELL.branding).toEqual({
      name: 'Civibus',
      appTitle: 'Civibus',
      stageLabel: 'Public Beta',
      tagline: 'Universal public-records intelligence'
    });
  });

  it('removes the old frontend-probe stage label from shell branding', () => {
    expect(APP_SHELL.branding.stageLabel).not.toBe('Frontend Probe');
  });

  it('defines a footer contract with methodology and reporting links', () => {
    const shellWithFooter = APP_SHELL as unknown as {
      footer?: {
        links?: Array<{
          label: string;
          href: string;
        }>;
      };
    };

    expect(shellWithFooter.footer).toBeDefined();
    expect(shellWithFooter.footer?.links).toEqual(
      expect.arrayContaining([
        { label: 'Methodology', href: '/methodology' },
        { label: 'Public API', href: '/developers' },
        APP_SHELL.reportingLink
      ])
    );
  });

  it('pins federal-first primary shell navigation to shared config', () => {
    expect(APP_SHELL.shellNavigation).toEqual([
      { label: 'Home', href: '/' },
      { label: 'Search', href: '/search' },
      { label: 'Donor Lookup', href: '/donors' },
      { label: 'Congress', href: '/congress' },
      { label: 'Methodology', href: '/methodology' }
    ]);
  });

  it('keeps federal landing action and coverage summary copy in shared config', () => {
    expect(APP_SHELL.landing.coverageSummary).toBe(
      'Current launch scope is the 543 elected federal seats, with live profiles for current officeholders and documented vacancies excluded from the live official count until filled. State, city, property, candidate-list, and committee-list breadth is not advertised from the homepage.'
    );
    expect(APP_SHELL.landing.actions).toEqual([
      {
        label: 'Search',
        href: '/search',
        description: 'Search source-linked federal people, offices, committees, and filings.'
      },
      {
        label: 'Methodology',
        href: '/methodology',
        description: 'Read source, refresh, and coverage methods for the federal-first dataset.'
      }
    ]);
  });

  it('keeps federal landing hero and CTA copy in shared config', () => {
    expect(APP_SHELL.landing.eyebrow).toBe('Federal-first public records');
    expect(APP_SHELL.landing.heading).toBe(
      'Follow money around Congress and the White House.'
    );
    expect(APP_SHELL.landing.body).toBe(
      'Civibus v1 covers 543 elected federal seats: 435 House seats, 100 Senate seats, 6 non-voting delegate seats, the President, and the Vice President. Public directory profiles appear for current officeholders; documented vacancies reduce the live officeholder count until seats are filled.'
    );
    expect(APP_SHELL.landing.coverageHeading).toBe('Federal scope');
    expect(APP_SHELL.landing.cta).toEqual({
      label: 'Browse Congress',
      href: '/congress',
      description: 'Open the federal directory for members of Congress and delegates.'
    });
  });

  it('defines static-route metadata copy in one shared config owner', () => {
    expect(APP_SHELL.staticRoutes.home).toEqual({
      title: 'Civibus | Federal public-records intelligence',
      description:
        'Browse federal-first Civibus profiles for Congress and the White House with source-linked FEC money summaries and independent expenditures.'
    });
    expect(APP_SHELL.staticRoutes.methodology).toEqual({
      title: 'Methodology | Civibus',
      description:
        'Coverage scope, confidence labels, and source guidance for campaign-finance, civic office, and property records.'
    });
    expect(APP_SHELL.staticRoutes.calendar).toEqual({
      title: 'Election Calendar | Civibus',
      description:
        'Track upcoming elections with contest-level counts and linked civic coverage across supported jurisdictions.'
    });
    expect(APP_SHELL.staticRoutes.coverage).toEqual({
      title: 'Coverage Registry | Civibus',
      description:
        'Review runtime coverage registry rows grouped by domain and jurisdiction with latest pull timestamps.'
    });
    expect(APP_SHELL.staticRoutes.dataSources).toEqual({
      title: 'Data Sources | Civibus',
      description:
        'Inspect runtime data-source metadata, pull status, and source-record pointers from the backend registry.'
    });
    expect(APP_SHELL.staticRoutes.developers).toEqual({
      title: 'Public API | Civibus',
      description:
        "Static reference for developers and journalists migrating from OpenSecrets or ProPublica APIs to Civibus's nonpartisan, source-linked federal public-record endpoints."
    });
  });

  it('limits static-route metadata ownership to static pages only', () => {
    expect(Object.keys(APP_SHELL.staticRoutes).sort()).toEqual([
      'calendar',
      'coverage',
      'dataSources',
      'developers',
      'home',
      'methodology'
    ]);
  });

  it('captures methodology confidence labels from classify_confidence tiers', () => {
    expect(APP_SHELL.methodology.confidenceLabels).toEqual([
      {
        label: 'match',
        description: 'Confidence >= 0.95. Auto-merge threshold.'
      },
      {
        label: 'probable_match',
        description: 'Confidence from 0.80 to <0.95. Likely same entity and review-worthy.'
      },
      {
        label: 'possible_match',
        description: 'Confidence from 0.60 to <0.80. Candidate link with lower confidence.'
      }
    ]);
  });

  it('keeps methodology sections in shared config', () => {
    expect(APP_SHELL.methodology.coverageSummary).toBe(
      'Civibus combines campaign-finance, civic office, and property records in one search experience. Coverage varies by jurisdiction and is refreshed based on source cadence.'
    );
    expect(APP_SHELL.methodology.sections).toEqual([
      {
        heading: 'Data freshness policy',
        body:
          'Production support requires data that can be refreshed at least weekly near elections, with daily updates preferred. Sources that only publish annual or quarterly exports are not treated as fully launch-ready without a supplementary path.'
      },
      {
        heading: 'Entity resolution methodology',
        body:
          'Entity resolution uses probabilistic matching with confidence tiers derived from model scores. High-confidence matches can be auto-merged while lower-confidence links remain reviewable so users can inspect uncertainty.'
      },
      {
        heading: 'Source-linking and evidence',
        body:
          'Every surfaced record is tied to provenance metadata and source links so users can trace claims back to official filings or source systems. Civibus prioritizes verifiable evidence over inferred narrative summaries. Person-page Top employers aggregate raw employer names from itemized individual contributions; they are not industry- or sector-coded.'
      }
    ]);
  });

  it('pins methodology headings to shared stage-2 copy', () => {
    expect(APP_SHELL.methodology.heading).toBe('Methodology');
    expect(APP_SHELL.methodology.confidenceHeading).toBe('Entity resolution confidence labels');
  });

  it('shares one reporting link for static pages', () => {
    expect(APP_SHELL.reportingLink).toEqual({
      label: 'Report a data issue',
      href: 'mailto:team@civibus.org?subject=Civibus%20data%20issue'
    });
  });
});

describe('MAP_LAYERS shared map-layer contract', () => {
  it('defines required map-layer fields in the shared config owner', () => {
    expect(MAP_LAYERS.length).toBeGreaterThan(0);

    for (const layer of MAP_LAYERS) {
      expect(layer).toEqual(
        expect.objectContaining({
          id: expect.any(String),
          level: expect.any(String),
          divisionType: expect.any(String),
          alwaysOn: expect.any(Boolean),
          label: expect.any(String),
          defaultVisible: expect.any(Boolean),
          applicableLevels: expect.arrayContaining([expect.any(String)])
        })
      );
    }
  });

  it('keeps NC congressional-district layer defaults for state and county drilldown', () => {
    const ncCongressionalLayer = MAP_LAYERS.find((layer) => layer.id === 'nc_congressional_districts');

    expect(ncCongressionalLayer).toBeDefined();
    expect(ncCongressionalLayer).toMatchObject({
      alwaysOn: false,
      defaultVisible: false
    });
    expect(ncCongressionalLayer?.applicableLevels).toEqual(
      expect.arrayContaining(['state', 'county'])
    );
  });
});
