export function formatCountLabel(
  count: number,
  singularLabel: string,
  pluralLabel = `${singularLabel}s`
): string {
  return `${count} ${count === 1 ? singularLabel : pluralLabel}`;
}
