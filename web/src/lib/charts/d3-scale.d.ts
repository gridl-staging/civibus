declare module "d3-scale" {
  export type ScaleBand<Domain extends { toString(): string } = string> = {
    (value: Domain): number | undefined;
    domain(): Domain[];
    domain(domain: Iterable<Domain>): ScaleBand<Domain>;
    range(): number[];
    range(range: Iterable<number>): ScaleBand<Domain>;
    copy(): ScaleBand<Domain>;
    bandwidth(): number;
    padding(value: number): ScaleBand<Domain>;
  };

  export function scaleBand<Domain extends { toString(): string } = string>(): ScaleBand<Domain>;
}
