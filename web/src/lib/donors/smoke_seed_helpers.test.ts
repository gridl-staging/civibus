import { EventEmitter } from "node:events";
import { beforeEach, describe, expect, it, vi } from "vitest";

const spawnMock = vi.hoisted(() => vi.fn());

vi.mock("node:child_process", () => ({
  spawn: spawnMock
}));

import { runSmokeSeedCommand } from "../../../tests/smoke/smoke_seed_helpers";

function mockChildProcess(exitCode: number, stdout = "", stderr = ""): EventEmitter & {
  stdout: EventEmitter;
  stderr: EventEmitter;
} {
  const child = new EventEmitter() as EventEmitter & {
    stdout: EventEmitter;
    stderr: EventEmitter;
  };
  child.stdout = new EventEmitter();
  child.stderr = new EventEmitter();

  queueMicrotask(() => {
    if (stdout !== "") {
      child.stdout.emit("data", Buffer.from(stdout));
    }
    if (stderr !== "") {
      child.stderr.emit("data", Buffer.from(stderr));
    }
    child.emit("close", exitCode);
  });

  return child;
}

describe("runSmokeSeedCommand", () => {
  beforeEach(() => {
    spawnMock.mockReset();
    process.env.POSTGRES_PASSWORD = "test-password";
  });

  it("runs seed commands with the live smoke database password environment", async () => {
    spawnMock.mockReturnValue(mockChildProcess(0));

    await runSmokeSeedCommand("uv", ["run", "python"]);

    expect(spawnMock).toHaveBeenCalledWith("uv", ["run", "python"], {
      env: expect.objectContaining({
        PGPASSWORD: "test-password",
        POSTGRES_PASSWORD: "test-password"
      }),
      stdio: ["ignore", "pipe", "pipe"]
    });
  });

  it("rejects with command stderr when the seed command exits non-zero", async () => {
    spawnMock.mockReturnValue(mockChildProcess(2, "ignored stdout", "fixture failed"));

    await expect(runSmokeSeedCommand("uv", ["run", "python"])).rejects.toThrow(
      "Smoke seed command failed with exit code 2: fixture failed"
    );
  });
});
