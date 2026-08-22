import { spawn } from "node:child_process";

export type SmokeSeedCleanupCallback = () => Promise<void>;

function requiredPostgresPassword(): string {
  const password = process.env.POSTGRES_PASSWORD;
  if (typeof password !== "string" || password === "") {
    throw new Error("POSTGRES_PASSWORD must be set for live smoke seeding");
  }
  return password;
}

function assertUuid(value: string, label: string): string {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)) {
    throw new Error(`${label} must be a UUID for live smoke seeding`);
  }
  return value;
}

export function sqlLiteral(value: string): string {
  return `'${value.replaceAll("'", "''")}'`;
}

export function cypherString(value: string): string {
  return value.replaceAll("\\", "\\\\").replaceAll('"', '\\"');
}

export function sqlUuid(value: string, label: string): string {
  return `${sqlLiteral(assertUuid(value, label))}::uuid`;
}

export function moneyLiteral(value: string): string {
  const normalized = value.replace(/[$,\s]/g, "");
  if (!/^-?\d+(?:\.\d+)?$/.test(normalized)) {
    throw new Error(`Smoke money value must be numeric, received: ${value}`);
  }
  return normalized;
}

export function jsonbLiteral(value: Record<string, unknown>): string {
  return `${sqlLiteral(JSON.stringify(value))}::jsonb`;
}

/**
 */
function buildPsqlArgs(): string[] {
  return [
    "-v",
    "ON_ERROR_STOP=1",
    "-X",
    "-q",
    "-h",
    process.env.POSTGRES_HOST ?? "127.0.0.1",
    "-p",
    process.env.POSTGRES_PORT ?? "5433",
    "-U",
    process.env.POSTGRES_USER ?? "civibus",
    "-d",
    process.env.POSTGRES_DB ?? "civibus",
    "-f",
    "-"
  ];
}

/**
 */
export async function runSmokeSeedSql(sql: string): Promise<void> {
  const postgresPassword = requiredPostgresPassword();
  await new Promise<void>((resolve, reject) => {
    const child = spawn("psql", buildPsqlArgs(), {
      env: {
        ...process.env,
        PGPASSWORD: postgresPassword
      },
      stdio: ["pipe", "pipe", "pipe"]
    });
    const stderrChunks: Buffer[] = [];

    child.stderr.on("data", (chunk: Buffer) => {
      stderrChunks.push(chunk);
    });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) {
        resolve();
        return;
      }
      const stderr = Buffer.concat(stderrChunks).toString("utf8").trim();
      reject(new Error(`Smoke seed SQL failed with exit code ${code}: ${stderr}`));
    });

    child.stdin.end(sql);
  });
}

/**
 */
export async function runSmokeSeedCommand(command: string, args: string[]): Promise<void> {
  const postgresPassword = requiredPostgresPassword();
  await new Promise<void>((resolve, reject) => {
    const child = spawn(command, args, {
      env: {
        ...process.env,
        PGPASSWORD: postgresPassword,
        POSTGRES_PASSWORD: postgresPassword
      },
      stdio: ["ignore", "pipe", "pipe"]
    });
    const stdoutChunks: Buffer[] = [];
    const stderrChunks: Buffer[] = [];

    child.stdout.on("data", (chunk: Buffer) => {
      stdoutChunks.push(chunk);
    });
    child.stderr.on("data", (chunk: Buffer) => {
      stderrChunks.push(chunk);
    });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) {
        resolve();
        return;
      }
      const stdout = Buffer.concat(stdoutChunks).toString("utf8").trim();
      const stderr = Buffer.concat(stderrChunks).toString("utf8").trim();
      reject(new Error(`Smoke seed command failed with exit code ${code}: ${stderr || stdout}`));
    });
  });
}
