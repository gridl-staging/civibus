/**
 * View-model builders for the search page and result cards.
 */
import {
  SEARCH_ENTITY_TYPES,
  SEARCH_PAGE_SIZE,
  SEARCH_QUERY_MIN_LENGTH,
  buildSearchPagePath,
  isSearchEntityType,
  toSearchResultHref,
  type SearchApiResult,
  type SearchEntityType
} from './contract';
import { formatCountLabel } from '$lib/count-label';
import { formatPersonDisplayName } from '$lib/display-name';
import { FEC_CANDIDATE_OFFICE_OPTIONS } from '$lib/campaign-finance-detail/filter-options';
import { buildPaginationContext } from '$lib/campaign-finance-detail/list-presentation';

export type SearchResultCardData = SearchApiResult;

export type SearchResultCard = {
  entityType: SearchEntityType;
  entityId: string;
  name: string;
  routeLabel: string;
  href: string;
  contextLine: string;
};

export type SearchEntityTypeOption = {
  value: SearchEntityType;
  label: string;
};

export type SearchStatusMessageInput = {
  query: string;
  resultCount: number;
  validationMessage?: string;
  isSubmitting?: boolean;
  /**
   * True when the result set spans pages (another page exists or this is not
   * the first). The count then describes this page, not the whole set, and the
   * wording must not claim otherwise.
   */
  isPaged?: boolean;
};

/** Pagination controls for the results region; null when everything fits one page. */
export type SearchPaginationPresentation = {
  label: string;
  previousHref: string | null;
  nextHref: string | null;
};

export type SearchRouteMetadata = {
  title: string;
  description: string;
};

export type SearchPagePresentationInput = {
  query: string;
  entityType: string;
  results: SearchResultCardData[];
  /** Zero-based position of this page within the result set (URL `offset`). */
  offset?: number;
  /** True when the page server's LIMIT+1 probe found a further page. */
  hasNext?: boolean;
  validationMessage?: string;
  form?: SearchPageFormState | null;
  isSubmitting?: boolean;
};

export type SearchPagePresentation = {
  metadata: SearchRouteMetadata;
  resultCards: SearchResultCard[];
  pagination: SearchPaginationPresentation | null;
  showResultsSkeleton: boolean;
  queryValue: string;
  selectedEntityType: SearchEntityType | '';
  inlineValidationMessage: string;
  submitButtonLabel: string;
  queryPlaceholder: string;
  entityTypeOptions: SearchEntityTypeOption[];
  guidanceBlock: string;
  browseLinks: SearchBrowseLink[];
  statusMessage: string;
};

export type SearchPageFormState = {
  query: string;
  entityType: string;
  validationMessage: string;
};

export type SearchBrowseLink = {
  label: string;
  href: string;
};

export const SEARCH_ENTITY_ROUTE_LABELS: Record<SearchEntityType, string> = {
  person: 'Person',
  org: 'Organization',
  committee: 'Committee',
  candidate: 'Candidate',
  office: 'Office',
  contest: 'Contest'
};

const SEARCH_ENTITY_PLURAL_LABELS: Record<SearchEntityType, string> = {
  person: 'people',
  org: 'organizations',
  committee: 'committees',
  candidate: 'candidates',
  office: 'offices',
  contest: 'contests'
};

function buildEntityListString(conjunction: 'and' | 'or'): string {
  const labels = SEARCH_ENTITY_TYPES.map((t) => SEARCH_ENTITY_PLURAL_LABELS[t]);
  if (labels.length <= 1) return labels[0] ?? '';
  return `${labels.slice(0, -1).join(', ')}, ${conjunction} ${labels[labels.length - 1]}`;
}

const ENTITY_LIST_AND = buildEntityListString('and');
const ENTITY_LIST_OR = buildEntityListString('or');

const DEFAULT_SEARCH_ROUTE_DESCRIPTION =
  `Search ${ENTITY_LIST_AND} across campaign-finance and civic records.`;
const SEARCH_GUIDANCE_BLOCK_TEMPLATE =
  `Search supports ${ENTITY_LIST_AND}. Enter at least ${SEARCH_QUERY_MIN_LENGTH} characters.`;
const DEFAULT_SEARCH_QUERY_PLACEHOLDER =
  `Search ${ENTITY_LIST_OR}`;

function getSelectedEntityType(entityType: string): SearchEntityType | '' {
  return isSearchEntityType(entityType) ? entityType : '';
}

function getGuidanceBlock(query: string): string {
  if (query !== '') {
    return '';
  }

  return SEARCH_GUIDANCE_BLOCK_TEMPLATE;
}

function buildSearchBrowseLinks(): SearchBrowseLink[] {
  return SEARCH_ENTITY_TYPES.map((entityType) => ({
    label: SEARCH_ENTITY_ROUTE_LABELS[entityType],
    href: buildSearchPagePath({ entityType })
  }));
}

function buildSearchEntityTypeOptions(): SearchEntityTypeOption[] {
  return SEARCH_ENTITY_TYPES.map((entityType) => ({
    value: entityType,
    label: SEARCH_ENTITY_ROUTE_LABELS[entityType]
  }));
}

export function buildSearchMetadata({ query, resultCount }: SearchStatusMessageInput): SearchRouteMetadata {
  const normalizedQuery = query.trim();

  if (normalizedQuery === '') {
    return {
      title: 'Search | Civibus',
      description: DEFAULT_SEARCH_ROUTE_DESCRIPTION
    };
  }

  const resultLabel = formatCountLabel(resultCount, 'result');

  return {
    title: `${normalizedQuery} (${resultLabel}) | Search | Civibus`,
    description: `${resultLabel} for "${normalizedQuery}" across Civibus records.`
  };
}

export function getSearchStatusMessage({
  query,
  resultCount,
  validationMessage = '',
  isSubmitting = false,
  isPaged = false
}: SearchStatusMessageInput): string {
  if (isSubmitting) {
    return 'Searching...';
  }

  if (validationMessage.trim() !== '') {
    return 'Search could not run. Fix validation issues and try again.';
  }

  if (query === '') {
    return `Enter at least ${SEARCH_QUERY_MIN_LENGTH} characters to search.`;
  }

  if (resultCount === 0) {
    return 'No matching records found.';
  }

  // "found" states a complete count; a paged set held rows back, so its count
  // only describes the visible page and must say so.
  return isPaged
    ? `${formatCountLabel(resultCount, 'result')} shown.`
    : `${formatCountLabel(resultCount, 'result')} found.`;
}

const PARTY_LABELS: Record<string, string> = {
  DEM: 'Democrat',
  REP: 'Republican',
  LIB: 'Libertarian',
  GRE: 'Green',
  IND: 'Independent'
};

const COMMITTEE_TYPE_LABELS: Record<string, string> = {
  pac: 'PAC',
  super_pac: 'Super PAC',
  party: 'Party Committee',
  candidate: 'Candidate Committee',
  carey: 'Hybrid PAC'
};

function expandPartyLabel(code: string): string {
  const normalizedCode = code.trim().toUpperCase();
  return PARTY_LABELS[normalizedCode] ?? code;
}

function expandCommitteeTypeLabel(code: string): string {
  const normalizedCode = code.trim().toLowerCase();
  return COMMITTEE_TYPE_LABELS[normalizedCode] ?? code;
}

function formatCurrency(amount: number): string {
  return amount.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
}

function parseContextCurrencyAmount(value: number | string | null | undefined): number | null {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : null;
  }

  const normalizedValue = normalizeContextValue(value);
  if (normalizedValue == null) {
    return null;
  }

  const parsedValue = Number(normalizedValue);
  return Number.isFinite(parsedValue) ? parsedValue : null;
}

function normalizeContextValue(value: string | null | undefined): string | null {
  if (value == null) {
    return null;
  }

  const trimmedValue = value.trim();
  return trimmedValue === '' ? null : trimmedValue;
}

/**
 */
function joinContextSegments(segments: Array<string | null>): string {
  return segments.filter((segment): segment is string => segment != null).join(' · ');
}

function buildPersonContextLine(result: SearchResultCardData): string {
  const party = normalizeContextValue(result.party);
  return joinContextSegments([
    normalizeContextValue(result.office_name),
    normalizeContextValue(result.state),
    party == null ? null : expandPartyLabel(party)
  ]);
}

function buildGenericContextLine(result: SearchResultCardData): string {
  const contextSegments: string[] = [];

  const party = normalizeContextValue(result.party);
  if (party != null) {
    contextSegments.push(expandPartyLabel(party));
  }

  const officeName = normalizeContextValue(result.office_name);
  if (officeName != null) {
    contextSegments.push(officeName);
  }

  const committeeType = normalizeContextValue(result.committee_type);
  if (committeeType != null) {
    contextSegments.push(expandCommitteeTypeLabel(committeeType));
  }

  const totalRaised = parseContextCurrencyAmount(result.total_raised);
  if (totalRaised != null) {
    contextSegments.push(formatCurrency(totalRaised));
  }

  const state = normalizeContextValue(result.state);
  if (state != null) {
    contextSegments.push(state);
  }

  return contextSegments.join(' · ');
}

// Candidate rows carry the raw FEC office code (H/S/P) from cf.candidate
// (civibus-x9d). The /candidates filter dropdown already owns the code→label
// mapping, so the card reuses those labels rather than growing a second owner —
// the same pattern this module already applies to party codes. Values outside
// the closed FEC set pass through verbatim, mirroring expandPartyLabel.
const FEC_OFFICE_LABEL_BY_CODE: ReadonlyMap<string, string> = new Map(
  FEC_CANDIDATE_OFFICE_OPTIONS.map((option) => [option.code, option.label])
);

function expandCandidateOfficeLabel(code: string): string {
  return FEC_OFFICE_LABEL_BY_CODE.get(code.trim().toUpperCase()) ?? code;
}

function buildContextLine(result: SearchResultCardData): string {
  if (result.entity_type === 'person') {
    return buildPersonContextLine(result);
  }

  if (result.entity_type === 'candidate') {
    const officeName = normalizeContextValue(result.office_name);
    return buildGenericContextLine({
      ...result,
      office_name: officeName == null ? officeName : expandCandidateOfficeLabel(officeName)
    });
  }

  return buildGenericContextLine(result);
}

/**
 * The entity types whose `name` is a human's name.
 *
 * The person lane reads `core.person.canonical_name`, which is *usually*
 * already formatted but carries raw FEC strings for people the spine has not
 * resolved yet. The candidate lane reads `cf.candidate.name`, always the raw
 * FEC filing string — and only identity-SAFE rows, because the search lane
 * applies the same `_CANDIDATE_IDENTITY_IS_SAFE_EXPR` browse predicate the
 * candidate list uses, so formatting unconditionally here matches the
 * identity-gated owner's safe branch (`formatCandidatePublicName` in
 * campaign-finance-detail). Routing both through the shared owner means one
 * human reads the same way whichever lane surfaced them. Org, committee,
 * office and contest names are not personal names and must render verbatim.
 */
const PERSONAL_NAME_ENTITY_TYPES: ReadonlySet<SearchEntityType> = new Set(['person', 'candidate']);

function formatSearchResultName(result: SearchResultCardData): string {
  return PERSONAL_NAME_ENTITY_TYPES.has(result.entity_type)
    ? formatPersonDisplayName(result.name)
    : result.name;
}

export function buildSearchResultCards(results: SearchResultCardData[]): SearchResultCard[] {
  return results.map((result) => ({
    entityType: result.entity_type,
    entityId: result.entity_id,
    name: formatSearchResultName(result),
    routeLabel: SEARCH_ENTITY_ROUTE_LABELS[result.entity_type],
    href: toSearchResultHref(result),
    contextLine: buildContextLine(result)
  }));
}

export function buildSearchResultKey(result: SearchResultCard): string {
  return `${result.entityType}:${result.entityId}`;
}

export function buildSearchPagePresentation({
  query,
  entityType,
  results,
  offset = 0,
  hasNext = false,
  validationMessage,
  form = null,
  isSubmitting = false
}: SearchPagePresentationInput): SearchPagePresentation {
  const queryValue = form?.query ?? query;
  const selectedEntityTypeInput = form?.entityType ?? entityType;
  const inlineValidationMessage = form?.validationMessage ?? validationMessage ?? '';
  const showResultsSkeleton = isSubmitting;
  const resultCards =
    isSubmitting || inlineValidationMessage !== '' ? [] : buildSearchResultCards(results);
  const resultCount = resultCards.length;
  const isPaged = hasNext || offset > 0;

  // Reuses the /candidates pagination owner over the page server's LIMIT+1
  // outcome. Hrefs carry the LOADED query/type (not in-flight form state):
  // pagination pages the result set on screen, and a new submit starts back at
  // page one via the POST redirect, which never carries an offset. A page with
  // neither side (everything fit) renders no pagination at all, and pending or
  // invalid states suppress it alongside the result cards they describe.
  const paginationContext = buildPaginationContext(offset, SEARCH_PAGE_SIZE, hasNext, resultCount);
  const showPagination =
    !showResultsSkeleton &&
    inlineValidationMessage === '' &&
    (paginationContext.hasPrevious || paginationContext.hasNext);
  const pagination: SearchPaginationPresentation | null = showPagination
    ? {
        label: paginationContext.label,
        previousHref: paginationContext.hasPrevious
          ? buildSearchPagePath({
              q: query,
              entityType,
              offset: Math.max(offset - SEARCH_PAGE_SIZE, 0)
            })
          : null,
        nextHref: paginationContext.hasNext
          ? buildSearchPagePath({ q: query, entityType, offset: offset + SEARCH_PAGE_SIZE })
          : null
      }
    : null;

  return {
    metadata: buildSearchMetadata({ query: queryValue, resultCount }),
    resultCards,
    pagination,
    showResultsSkeleton,
    queryValue,
    selectedEntityType: getSelectedEntityType(selectedEntityTypeInput),
    inlineValidationMessage,
    submitButtonLabel: isSubmitting ? 'Searching...' : 'Search',
    queryPlaceholder: DEFAULT_SEARCH_QUERY_PLACEHOLDER,
    entityTypeOptions: buildSearchEntityTypeOptions(),
    guidanceBlock: getGuidanceBlock(queryValue),
    browseLinks: buildSearchBrowseLinks(),
    statusMessage: getSearchStatusMessage({
      query: queryValue,
      resultCount,
      validationMessage: inlineValidationMessage,
      isSubmitting,
      isPaged
    })
  };
}
