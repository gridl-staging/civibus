import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { join, relative } from 'node:path';
import { APP_SHELL, MAP_LAYERS, buildMapLayerVisibilityDefaults } from './app';

const ANALYTICS_INTEGRATION_PATTERN =
  /@segment\/analytics|analytics-next|@vercel\/analytics|posthog-js|mixpanel-browser|google-analytics|googletagmanager|plausible\.io|matomo|\bgtag\s*\(/i;

function frontendProductionSources(directory: string): Array<{ path: string; source: string }> {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return frontendProductionSources(path);
    if (!entry.isFile() || entry.name.includes('.test.')) return [];
    return [{ path: relative(process.cwd(), path), source: readFileSync(path, 'utf8') }];
  });
}

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

  it('defines an exact rendered footer contract for currently available routes', () => {
    const shellWithFooter = APP_SHELL as unknown as {
      footer?: {
        links?: Array<{
          label: string;
          href: string;
        }>;
      };
    };

    expect(shellWithFooter.footer).toBeDefined();
    expect(shellWithFooter.footer?.links).toEqual([
      { label: 'Methodology', href: '/methodology' },
      { label: 'Public API', href: '/developers' },
      APP_SHELL.reportingLink
    ]);
  });

  it('owns trust-route footer links as a distinct shared footer group', () => {
    const shellWithFooter = APP_SHELL as unknown as {
      footer?: {
        links?: Array<{
          label: string;
          href: string;
        }>;
        trustPageLinks?: Array<{
          label: string;
          href: string;
        }>;
      };
    };
    const primaryFooterHrefs = shellWithFooter.footer?.links?.map((link) => link.href) ?? [];
    const trustPageHrefs = shellWithFooter.footer?.trustPageLinks?.map((link) => link.href) ?? [];

    expect(shellWithFooter.footer?.trustPageLinks).toEqual([
      { label: 'About', href: '/about' },
      { label: 'Contact', href: '/contact' },
      { label: 'Privacy', href: '/privacy' }
    ]);
    expect(primaryFooterHrefs.filter((href) => trustPageHrefs.includes(href))).toEqual([]);
    expect(APP_SHELL.shellNavigation.map((link) => link.href)).not.toContain('/about');
    expect(APP_SHELL.shellNavigation.map((link) => link.href)).not.toContain('/contact');
    expect(APP_SHELL.shellNavigation.map((link) => link.href)).not.toContain('/privacy');
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
    expect(APP_SHELL.staticRoutes.about).toEqual({
      title: 'About | Civibus',
      description:
        'Learn what Civibus is, what federal-first v1 covers, and the source-linked boundaries for its public-records presentation.'
    });
    expect(APP_SHELL.staticRoutes.contact).toEqual({
      title: 'Contact | Civibus',
      description:
        'Report a Civibus data issue through the shared reporting link without a contact form or page-local submission flow.'
    });
    expect(APP_SHELL.staticRoutes.privacy).toEqual({
      title: 'Privacy | Civibus',
      description:
        'Review the privacy-relevant behavior Civibus can substantiate from frontend integration scans and API logging tests.'
    });
  });

  it('limits static-route metadata ownership to static pages only', () => {
    expect(Object.keys(APP_SHELL.staticRoutes).sort()).toEqual([
      'about',
      'calendar',
      'contact',
      'coverage',
      'dataSources',
      'developers',
      'home',
      'methodology',
      'privacy'
    ]);
  });

  it('groups About page copy under shared trust-page config', () => {
    const aboutText = JSON.stringify(APP_SHELL.trustPages.about);
    const requiredMarkers = [
      'Civibus',
      'public-records intelligence platform',
      'fragmented government records searchable',
      '543 elected federal seats',
      '435 House seats',
      '100 Senate seats',
      '6 non-voting delegate seats',
      'President',
      'Vice President',
      'FEC money summaries',
      'Schedule E independent expenditures',
      'nonpartisan',
      'source-linked',
      'without editorial commentary',
      'state',
      'city',
      'post-v1 race and challenger expansion',
      'non-campaign-finance domains',
      'future work'
    ];

    const missingMarkers = requiredMarkers.filter((marker) => !aboutText.includes(marker));

    expect(APP_SHELL.trustPages.about.heading).toBe('About');
    expect(missingMarkers).toEqual([]);
    expect(aboutText).not.toMatch(/\b(inc\.?|llc|legal entity)\b/i);
  });

  it('keeps Contact copy on the shared reporting action only', () => {
    const contactPage = APP_SHELL.trustPages.contact as typeof APP_SHELL.trustPages.contact & {
      actions?: unknown;
    };
    const contactText = JSON.stringify(contactPage);

    expect(contactPage.action).toBe(APP_SHELL.reportingLink);
    expect(contactPage.actions).toBeUndefined();
    expect(contactText).toContain('report a data issue');
    expect(contactText).toContain(APP_SHELL.reportingLink.label);
    expect(contactText).not.toMatch(/\b(contact form|form field|submission|success state|mailbox)\b/i);
  });

  it('bounds Privacy copy to scanned frontend and API logging evidence', () => {
    const privacyText = JSON.stringify(APP_SHELL.trustPages.privacy);
    const requiredEvidence = [
      'scanned frontend paths',
      'no analytics or telemetry integration',
      'api/test_logging.py',
      'method',
      'path',
      'status',
      'request ID',
      'duration',
      'query-string values',
      'Internal Server Error',
      'generic 500 response bodies',
      'exception messages',
      'tracebacks',
      'stack traces',
      'exc_info'
    ];
    const missingEvidence = requiredEvidence.filter((evidence) => !privacyText.includes(evidence));

    expect(missingEvidence).toEqual([]);
    expect(privacyText).not.toMatch(
      /\b(retention|storage|security guarantee|secure infrastructure|legal entity|company|corporation)\b/i
    );
  });

  it('blocks stale no-analytics copy when a frontend integration is introduced', () => {
    const packageManifest = readFileSync(join(process.cwd(), 'package.json'), 'utf8');
    const integrationHits = [
      { path: 'package.json', source: packageManifest },
      ...frontendProductionSources(join(process.cwd(), 'src'))
    ]
      .filter(({ source }) => ANALYTICS_INTEGRATION_PATTERN.test(source))
      .map(({ path }) => path);
    const privacyText = JSON.stringify(APP_SHELL.trustPages.privacy);

    expect({ integrationHits, claimsNoIntegration: privacyText.includes('no analytics or telemetry integration') })
      .toEqual({ integrationHits: [], claimsNoIntegration: true });
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

  it('shows a selected congressional-district layer without changing the unselected default', () => {
    expect(buildMapLayerVisibilityDefaults('state')).toEqual({
      nc_statewide_boundary: true,
      nc_county_boundaries: true,
      nc_congressional_districts: false
    });
    expect(buildMapLayerVisibilityDefaults('state', 'congressional_district')).toEqual({
      nc_statewide_boundary: true,
      nc_county_boundaries: true,
      nc_congressional_districts: true
    });
  });
});
