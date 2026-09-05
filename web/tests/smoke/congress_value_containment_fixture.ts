import type { Locator } from "playwright";

/**
 * Arrange an extreme exact-value specimen without changing the shared Congress
 * fixture totals that own ordering and comparison-bar geometry.
 */
export async function replaceRenderedMoneyLabel(
  moneyLink: Locator,
  exactLabel: string
): Promise<void> {
  await moneyLink.evaluate((element, label) => {
    element.textContent = label;
  }, exactLabel);
}

export async function horizontalOverflow(locator: Locator): Promise<number> {
  return locator.evaluate((element) => {
    const rendered = element as HTMLElement;
    return rendered.scrollWidth - rendered.clientWidth;
  });
}

export async function renderedFragmentCount(locator: Locator): Promise<number> {
  return locator.evaluate((element) => element.getClientRects().length);
}
