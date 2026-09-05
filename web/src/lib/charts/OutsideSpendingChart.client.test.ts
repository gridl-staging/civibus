// @vitest-environment jsdom
import "$lib/client_test_environment";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mount, unmount } from "svelte";
import OutsideSpendingChart from "./OutsideSpendingChart.svelte";
import type { OutsideSpendingRow } from "./types";

vi.hoisted(() => {
  class TestResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  }

  vi.stubGlobal("ResizeObserver", TestResizeObserver);
});

const baseFrame = {
  cycle: 2026,
  coverageThrough: "2026-06-30",
  sources: [{ label: "FEC filings", href: "https://www.fec.gov/data/" }],
  disclosureContext: "Example candidate (candidacy 1)"
};

let mountedComponents: Record<string, unknown>[] = [];

afterEach(async () => {
  for (const component of mountedComponents) {
    await unmount(component);
  }
  mountedComponents = [];
  document.body.innerHTML = "";
});

function mountOutsideSpendingChart(input: {
  rows: OutsideSpendingRow[];
  topSpenders: OutsideSpendingRow[];
}) {
  const target = document.createElement("div");
  document.body.append(target);
  const component = mount(OutsideSpendingChart, {
    target,
    props: {
      ...baseFrame,
      testId: "outside-spending-duplicate-spenders",
      rows: input.rows,
      topSpenders: input.topSpenders
    }
  });
  mountedComponents.push(component as Record<string, unknown>);
  return target;
}

describe("OutsideSpendingChart client keyed-row regressions", () => {
  it("mounts same-committee support and oppose top spender rows without duplicate-key errors", () => {
    const rows: OutsideSpendingRow[] = [
      {
        id: "support",
        label: "Support spending",
        stance: "support",
        amount: 400,
        transactionCount: 4
      },
      {
        id: "oppose",
        label: "Oppose spending",
        stance: "oppose",
        amount: 250,
        transactionCount: 2
      }
    ];

    const target = mountOutsideSpendingChart({
      rows,
      topSpenders: [
        {
          id: "same-committee",
          label: "Example PAC",
          stance: "support",
          amount: 400,
          transactionCount: 4
        },
        {
          id: "same-committee",
          label: "Example PAC",
          stance: "oppose",
          amount: 250,
          transactionCount: 2
        }
      ]
    });

    expect(target.textContent).toContain("Example PAC: $400.00");
    expect(target.textContent).toContain("Example PAC: $250.00");
  });
});
