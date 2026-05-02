const DEFAULT_SMOKE_API_PORT = 3999;

function parseSmokeApiPort(rawPort: string | undefined): number | null {
  if (rawPort === undefined) {
    return null;
  }

  const parsedPort = Number(rawPort);
  if (!Number.isInteger(parsedPort) || parsedPort <= 0 || parsedPort > 65535) {
    return null;
  }

  return parsedPort;
}

export function resolveSmokeApiPort(env: Record<string, string | undefined>): number {
  return parseSmokeApiPort(env.SMOKE_API_PORT) ?? DEFAULT_SMOKE_API_PORT;
}
