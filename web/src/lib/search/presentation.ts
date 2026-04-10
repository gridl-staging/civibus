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
};

export type SearchEntityTypeOption = {
  value: SearchEntityType;
  label: string;
};

export type SearchStatusMessageInput = {
  query: string;
  resultCount: number;
};

export type SearchRouteMetadata = {
  title: string;
  description: string;
};

export type SearchPagePresentationInput = {
  query: string;
  entityType: string;
  results: SearchResultCardData[];
};

export type SearchPagePresentation = {
  metadata: SearchRouteMetadata;
  resultCards: SearchResultCard[];
  selectedEntityType: SearchEntityType | '';
  queryPlaceholder: string;
  entityTypeOptions: SearchEntityTypeOption[];
  guidanceBlock: string;
  browseLinks: SearchBrowseLink[];
  statusMessage: string;
};

export type SearchBrowseLink = {
  label: string;
  href: string;
};

const DEFAULT_SEARCH_ROUTE_DESCRIPTION =
  'Search people, organizations, committees, candidates, and offices across campaign-finance and civic records.';
const SEARCH_GUIDANCE_BLOCK_TEMPLATE =
  `Search supports people, organizations, committees, candidates, and offices. Enter at least ${SEARCH_QUERY_MIN_LENGTH} characters.`;
const DEFAULT_SEARCH_QUERY_PLACEHOLDER =
  'Search people, organizations, committees, candidates, or offices';
const SEARCH_ENTITY_ROUTE_LABELS: Record<SearchEntityType, string> = {
  person: 'Person',
  org: 'Organization',
  committee: 'Committee',
  candidate: 'Candidate',
  office: 'Office'
};

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

export function getSearchStatusMessage({ query, resultCount }: SearchStatusMessageInput): string {
  if (query === '') {
    return `Enter at least ${SEARCH_QUERY_MIN_LENGTH} characters to search.`;
  }

  if (resultCount === 0) {
    return 'No matching records found.';
  }

  return `${formatCountLabel(resultCount, 'result')} found.`;
}

export function buildSearchResultCards(results: SearchResultCardData[]): SearchResultCard[] {
  return results.map((result) => ({
    entityType: result.entity_type,
    entityId: result.entity_id,
    name: result.name,
    routeLabel: SEARCH_ENTITY_ROUTE_LABELS[result.entity_type],
    href: toSearchResultHref(result)
  }));
}

export function buildSearchPagePresentation({
  query,
  entityType,
  results
}: SearchPagePresentationInput): SearchPagePresentation {
  const resultCards = buildSearchResultCards(results);
  const resultCount = resultCards.length;

  return {
    metadata: buildSearchMetadata({ query, resultCount }),
    resultCards,
    selectedEntityType: getSelectedEntityType(entityType),
    queryPlaceholder: DEFAULT_SEARCH_QUERY_PLACEHOLDER,
    entityTypeOptions: buildSearchEntityTypeOptions(),
    guidanceBlock: getGuidanceBlock(query),
    browseLinks: buildSearchBrowseLinks(),
    statusMessage: getSearchStatusMessage({ query, resultCount })
  };
}
