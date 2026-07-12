/**
 * View-model builders for the search page and result cards.
 */
import {
  SEARCH_ENTITY_TYPES,
  SEARCH_QUERY_MIN_LENGTH,
  buildSearchPagePath,
  isSearchEntityType,
  toSearchResultHref,
  type SearchApiResult,
  type SearchEntityType
} from './contract';
import { formatCountLabel } from '$lib/count-label';

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
};

export type SearchRouteMetadata = {
  title: string;
  description: string;
};

export type SearchPagePresentationInput = {
  query: string;
  entityType: string;
  results: SearchResultCardData[];
  validationMessage?: string;
  form?: SearchPageFormState | null;
  isSubmitting?: boolean;
};

export type SearchPagePresentation = {
  metadata: SearchRouteMetadata;
  resultCards: SearchResultCard[];
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
  isSubmitting = false
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

  return `${formatCountLabel(resultCount, 'result')} found.`;
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

function buildContextLine(result: SearchResultCardData): string {
  if (result.entity_type === 'person') {
    return buildPersonContextLine(result);
  }

  return buildGenericContextLine(result);
}

export function buildSearchResultCards(results: SearchResultCardData[]): SearchResultCard[] {
  return results.map((result) => ({
    entityType: result.entity_type,
    entityId: result.entity_id,
    name: result.name,
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

  return {
    metadata: buildSearchMetadata({ query: queryValue, resultCount }),
    resultCards,
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
      isSubmitting
    })
  };
}
