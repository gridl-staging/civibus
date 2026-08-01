import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vitest/config';

function smokeApiTarget(environment: NodeJS.ProcessEnv): string {
  const configuredBaseUrl = environment.CIVIBUS_API_BASE_URL?.trim();
  if (configuredBaseUrl) {
    return new URL(configuredBaseUrl).origin;
  }
  const smokeApiPort = environment.SMOKE_API_PORT?.trim() || '3999';
  return `http://127.0.0.1:${smokeApiPort}`;
}

export default defineConfig({
  plugins: [sveltekit()],
  preview: {
    proxy: {
      '/api': {
        target: smokeApiTarget(process.env),
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/v1(?=\/|\?|$)/, '/v1')
      }
    }
  },
  test: {
    projects: [
      {
        extends: true,
        test: {
          name: 'node',
          include: ['src/**/*.test.ts'],
          exclude: ['src/**/*.client.test.ts'],
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
          include: ['src/**/*.client.test.ts'],
          environment: 'jsdom',
          execArgv: ['--conditions=browser']
        }
      }
    ]
  }
});
