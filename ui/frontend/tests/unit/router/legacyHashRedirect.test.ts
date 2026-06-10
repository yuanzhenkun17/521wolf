import assert from "node:assert/strict";
import { afterEach, test } from "vitest";
import { appViewFromRouteSource } from "../../../src/router/appViews";
import {
  appViewFromRoute,
  installLegacyHashBridge,
  legacyHashForView,
  syncInitialRouteToLegacyHash,
} from "../../../src/router/legacyHashRedirect";

type LocationLike = Pick<Location, "pathname" | "search" | "hash">;

const originalWindow = globalThis.window;

afterEach(() => {
  if (originalWindow === undefined)
    delete (globalThis as { window?: Window }).window;
  else globalThis.window = originalWindow;
});

function locationLike(pathname: string, search = "", hash = ""): LocationLike {
  return { pathname, search, hash };
}

test("maps new router paths to the matching app view", () => {
  assert.equal(appViewFromRoute({ path: "/" }), "lobby");
  assert.equal(appViewFromRoute({ path: "/match" }), "match");
  assert.equal(appViewFromRoute({ path: "/logs" }), "logs");
  assert.equal(appViewFromRoute({ path: "/benchmark" }), "benchmark");
  assert.equal(appViewFromRoute({ path: "/evolution" }), "evolution");
  assert.equal(appViewFromRoute({ path: "/tasks" }), "tasks");
});

test("falls back to lobby for unknown routes", () => {
  assert.equal(appViewFromRoute({ path: "/evidence" }), "lobby");
  assert.equal(appViewFromRoute({ path: "/missing" }), "lobby");
});

test("resolves active app views from router source before runtime state", () => {
  assert.equal(
    appViewFromRouteSource({ name: "lobby", path: "/", hash: "" }),
    "lobby",
  );
  assert.equal(
    appViewFromRouteSource({
      name: "lobby",
      path: "/",
      hash: "#logs?game_id=game-7",
    }),
    "logs",
  );
  assert.equal(
    appViewFromRouteSource({
      name: "benchmark",
      path: "/benchmark",
      hash: "#logs?game_id=game-7",
    }),
    "benchmark",
  );
  assert.equal(
    appViewFromRouteSource({
      name: "tasks",
      path: "/tasks",
      hash: "#benchmark?batch_id=bench-7",
    }),
    "tasks",
  );
  assert.equal(
    appViewFromRouteSource({ name: "missing", path: "/missing", hash: "" }),
    "",
  );
  assert.equal(
    appViewFromRouteSource({
      name: "missing",
      path: "/missing",
      hash: "#evolution?run_id=run-1",
    }),
    "evolution",
  );
  assert.equal(appViewFromRouteSource(null), "");
  assert.equal(appViewFromRouteSource({}), "");
});

test("builds legacy hashes and preserves query parameters", () => {
  assert.equal(legacyHashForView("lobby"), "");
  assert.equal(legacyHashForView("match"), "#match");
  assert.equal(
    legacyHashForView("logs", "?game_id=game-7&workspace=benchmark"),
    "#logs?game_id=game-7&workspace=benchmark",
  );
  assert.equal(
    legacyHashForView("benchmark", "batch_id=bench-9"),
    "#benchmark?batch_id=bench-9",
  );
  assert.equal(
    legacyHashForView("evolution", "?run_id=run-3&proposal_id=proposal-b"),
    "#evolution?run_id=run-3&proposal_id=proposal-b",
  );
  assert.equal(
    legacyHashForView("tasks", "task_id=task-9"),
    "#tasks?task_id=task-9",
  );
});

test("syncs an initial new route to its legacy hash without dropping query", () => {
  const location = locationLike("/logs", "?game_id=game-7&workspace=benchmark");

  syncInitialRouteToLegacyHash(location as Location);

  assert.equal(location.hash, "#logs?game_id=game-7&workspace=benchmark");
});

test("sync handles trailing slashes and skips lobby because it has no legacy hash", () => {
  const matchLocation = locationLike("/match///", "?mode=play");
  const lobbyLocation = locationLike("/", "?mode=watch");

  syncInitialRouteToLegacyHash(matchLocation as Location);
  syncInitialRouteToLegacyHash(lobbyLocation as Location);

  assert.equal(matchLocation.hash, "#match?mode=play");
  assert.equal(lobbyLocation.hash, "");
});

test("syncs explicit router paths over stale or invalid legacy hashes", () => {
  const staleHashLocation = locationLike(
    "/benchmark",
    "?batch_id=bench-7",
    "#logs?game_id=game-2",
  );
  const invalidHashLocation = locationLike(
    "/evolution",
    "?run_id=run-3",
    "#evidence?game_id=game-1",
  );
  const taskLocation = locationLike(
    "/tasks",
    "?task_id=task-7",
    "#benchmark?batch_id=bench-1",
  );

  syncInitialRouteToLegacyHash(staleHashLocation as Location);
  syncInitialRouteToLegacyHash(invalidHashLocation as Location);
  syncInitialRouteToLegacyHash(taskLocation as Location);

  assert.equal(staleHashLocation.hash, "#benchmark?batch_id=bench-7");
  assert.equal(invalidHashLocation.hash, "#evolution?run_id=run-3");
  assert.equal(taskLocation.hash, "#tasks?task_id=task-7");
});

test("keeps matching legacy hash deep links when the router query is empty", () => {
  const location = locationLike(
    "/logs",
    "",
    "#logs?game_id=legacy-game&workspace=archive",
  );

  syncInitialRouteToLegacyHash(location as Location);

  assert.equal(location.hash, "#logs?game_id=legacy-game&workspace=archive");
});

test("syncs route query over matching legacy hash query on explicit router paths", () => {
  const location = locationLike(
    "/logs",
    "?game_id=route-game&workspace=review",
    "#logs?game_id=hash-game&workspace=archive",
  );

  syncInitialRouteToLegacyHash(location as Location);

  assert.equal(location.hash, "#logs?game_id=route-game&workspace=review");
});

test("does not redirect unknown initial paths", () => {
  const location = locationLike("/evidence", "?game_id=game-2");

  syncInitialRouteToLegacyHash(location as Location);

  assert.equal(location.hash, "");
});

test("router bridge writes legacy hashes after navigation while preserving query", () => {
  let afterEachCallback:
    | ((to: { path: string; query?: Record<string, unknown> }) => void)
    | null = null;
  const router = {
    afterEach(
      callback: (to: { path: string; query?: Record<string, unknown> }) => void,
    ) {
      afterEachCallback = callback;
    },
  };
  globalThis.window = {
    location: locationLike("/match", "?mode=play"),
  } as Window & typeof globalThis;

  installLegacyHashBridge(
    router as Parameters<typeof installLegacyHashBridge>[0],
  );
  afterEachCallback?.({ path: "/match", query: { mode: "play" } });

  assert.equal(window.location.hash, "#match?mode=play");
});

test("router bridge syncs explicit routes over stale hashes and preserves legacy fallback routes", () => {
  const callbacks: Array<
    (to: { path: string; query?: Record<string, unknown> }) => void
  > = [];
  const router = {
    afterEach(
      callback: (to: { path: string; query?: Record<string, unknown> }) => void,
    ) {
      callbacks.push(callback);
    },
  };
  globalThis.window = {
    location: locationLike(
      "/benchmark",
      "?batch_id=bench-7",
      "#logs?game_id=game-2",
    ),
  } as Window & typeof globalThis;

  installLegacyHashBridge(
    router as Parameters<typeof installLegacyHashBridge>[0],
  );
  callbacks[0]({ path: "/benchmark", query: { batch_id: "bench-7" } });
  assert.equal(window.location.hash, "#benchmark?batch_id=bench-7");

  window.location.search = "";
  window.location.hash = "#logs?game_id=legacy-game&workspace=archive";
  callbacks[0]({ path: "/logs", query: {} });
  assert.equal(
    window.location.hash,
    "#logs?game_id=legacy-game&workspace=archive",
  );

  window.location.hash = "#logs?game_id=legacy-game";
  callbacks[0]({ path: "/evidence" });
  assert.equal(window.location.hash, "#logs?game_id=legacy-game");
});

test("router bridge prefers router query over stale window search", () => {
  const callbacks: Array<
    (to: { path: string; query?: Record<string, unknown> }) => void
  > = [];
  const router = {
    afterEach(
      callback: (to: { path: string; query?: Record<string, unknown> }) => void,
    ) {
      callbacks.push(callback);
    },
  };
  globalThis.window = {
    location: locationLike("/logs", "?game_id=stale-game", ""),
  } as Window & typeof globalThis;

  installLegacyHashBridge(
    router as Parameters<typeof installLegacyHashBridge>[0],
  );
  callbacks[0]({
    path: "/logs",
    query: { game_id: "route-game", workspace: "review" },
  });

  assert.equal(
    window.location.hash,
    "#logs?game_id=route-game&workspace=review",
  );
});
