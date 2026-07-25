import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [sveltekit()],
  test: {
    projects: [
      {
        extends: true,
        test: {
          name: 'node',
          include: ['src/**/*.test.ts'],
          exclude: ['src/lib/detail-trust/TrustSection.client.test.ts'],
          environment: 'node'
        }
      },
      {
        extends: true,
        resolve: {
          conditions: ['browser']
        },
        ssr: {
          resolve: {
            conditions: ['browser']
          }
        },
        test: {
          name: 'client',
          include: ['src/lib/detail-trust/TrustSection.client.test.ts'],
          environment: 'jsdom',
          execArgv: ['--conditions=browser']
        }
      }
    ]
  }
});
