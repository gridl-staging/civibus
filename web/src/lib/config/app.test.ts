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
      { label: 'Candidates', href: '/candidates' },
      { label: 'Committees', href: '/committees' },
      { label: 'Congress', href: '/congress' },
      { label: 'Developers', href: '/developers' },
      { label: 'Methodology', href: '/methodology' }
    ]);
    expect(APP_SHELL.shellNavigation).not.toContainEqual({ label: 'Compare', href: '/compare' });
    expect(APP_SHELL.shellNavigation).not.toContainEqual({ label: 'Donor Lookup', href: '/donors' });
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
        'Federal Schedule A scope, donor grouping, coverage, and freshness methodology for Civibus money views.'
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

  it('carries the federal-first methodology disclosure contract in shared config', () => {
    const methodologyText = JSON.stringify(APP_SHELL.methodology);
    const requiredDisclosures = [
      'Methodology',
      '/coverage',
      '/data-sources',
      '2022-01-01',
      "transaction_type LIKE '1%'",
      "contributor_entity_type = 'IND'",
      'no memo rows',
      'no terminated amendments',
      'no superseded source records',
      'current-officeholder committee slice',
      'floors',
      'not full-universe FEC Schedule A totals'
    ];

    const missingDisclosures = requiredDisclosures.filter(
      (disclosure) => !methodologyText.includes(disclosure)
    );
    const missingCycles = [2022, 2024, 2026].filter(
      (cycle) => !new RegExp(`(^|[^\\d-])${cycle}($|[^\\d-])`).test(methodologyText)
    );

    expect({ missingDisclosures, missingCycles }).toEqual({
      missingDisclosures: [],
      missingCycles: []
    });
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
