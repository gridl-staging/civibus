import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

const donorPageSource = readFileSync(resolve(__dirname, '+page.svelte'), 'utf8');

describe('/donors page Svelte contract', () => {
  it('keeps the typed search query in local form state during submit-time rerenders', () => {
    expect(donorPageSource).toContain('let queryInputValue = data.query');
    expect(donorPageSource).toContain('bind:value={queryInputValue}');
    expect(donorPageSource).not.toContain('value={data.query}');
  });

  it('resynchronizes local query state on URL-owned same-query pagination changes', () => {
    expect(donorPageSource).toContain('let renderedDonorStateKey = getDonorStateKey(data)');
    expect(donorPageSource).toContain("$: donorStateKey = getDonorStateKey(data)");
    expect(donorPageSource).toContain("Pick<PageData, 'query' | 'by' | 'limit' | 'offset'>");
  });

  it('guards API-provided source links before binding href attributes', () => {
    expect(donorPageSource).toContain('function safeExternalHref');
    expect(donorPageSource).toContain("url.protocol === 'https:' || url.protocol === 'http:'");
    expect(donorPageSource).toContain('{#if safeExternalHref(source.data_source_url)}');
    expect(donorPageSource).toContain("{#if safeExternalHref(source.record_url)}");
    expect(donorPageSource).not.toContain('<a href={source.data_source_url}>');
    expect(donorPageSource).not.toContain('<a href={source.record_url}>');
  });

  it('encodes recipient IDs before building person-route hrefs', () => {
    expect(donorPageSource).toContain('function personHref(personId: string): string');
    expect(donorPageSource).toContain('encodeURIComponent(personId)');
    expect(donorPageSource).toContain('href={personHref(recipient.person_id)}');
    expect(donorPageSource).not.toContain('href={`/person/${recipient.person_id}`}');
  });
});
