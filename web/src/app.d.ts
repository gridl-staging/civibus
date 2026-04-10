import type { ApiClient } from '$lib/server/api/client';

declare global {
  namespace App {
    interface Error {
      detail?: unknown;
    }

    interface Locals {
      api: ApiClient;
    }
  }
}

export {};
