declare module 'playwright/test' {
  export const expect: any;
  export const test: any;
  export const devices: Record<string, any>;
  export function defineConfig(config: any): any;
}
