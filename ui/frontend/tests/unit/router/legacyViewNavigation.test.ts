import assert from "node:assert/strict";
import { afterEach, test } from "vitest";
import type { AppView } from "../../../src/types/ui";
import {
  addLegacyHashChangeListener,
  currentLegacyHash,
  currentLegacyView,
  hashForView,
  isLegacyHashForView,
  legacyHashFromRouteQuery,
  normalizeRouteQuery,
  registerLegacyViewRouter,
  routeHashFromLegacyHash,
  routeLocationForLegacyView,
  routeLocationForViewQuery,
  routePathForView,
  routeQueryFromLegacyHash,
  routeQueryString,
  syncCurrentLegacyHashForView,
  syncCurrentViewToLegacyHash,
  syncRouterToLegacyView,
  viewFromHash,
  writeCurrentViewRoute,
  writeLegacyHashForView,
  writeViewRoute,
  writeViewHash,
} from "../../../src/router/legacyViewNavigation";

const originalWindow = globalThis.window;

afterEach(() => {
  registerLegacyViewRouter(null);
  if (originalWindow === undefined)
    delete (globalThis as { window?: Window }).window;
  else globalThis.window = originalWindow;
});

function locationLike(hash = ""): Pick<Location, "hash"> {
  return { hash };
}

function eventWindowLike(hash = "") {
  const listeners = new Map<string, EventListener[]>();
  return {
    location: locationLike(hash),
    addEventListener(type: string, listener: EventListener) {
      listeners.set(type, [...(listeners.get(type) || []), listener]);
    },
    removeEventListener(type: string, listener: EventListener) {
      listeners.set(
        type,
        (listeners.get(type) || []).filter((item) => item !== listener),
      );
    },
    listeners(type: string) {
      return listeners.get(type) || [];
    },
  };
}

test("maps legacy app views to router paths", () => {
  assert.equal(routePathForView("lobby"), "/");
  assert.equal(routePathForView("match"), "/match");
  assert.equal(routePathForView("logs"), "/logs");
  assert.equal(routePathForView("benchmark"), "/benchmark");
  assert.equal(routePathForView("evolution"), "/evolution");
  assert.equal(routePathForView("tasks"), "/tasks");
  assert.equal(routePathForView("settings"), "/settings");
});

test("maps app views to legacy hashes and parses legacy hash routes", () => {
  assert.equal(hashForView("lobby"), "");
  assert.equal(hashForView("match"), "match");
  assert.equal(hashForView("logs"), "logs");
  assert.equal(hashForView("benchmark"), "benchmark");
  assert.equal(hashForView("evolution"), "evolution");
  assert.equal(hashForView("tasks"), "tasks");
  assert.equal(hashForView("settings"), "settings");

  assert.equal(
    routeHashFromLegacyHash("#evolution?run_id=run-1"),
    "#evolution",
  );
  assert.equal(
    isLegacyHashForView("evolution", "#evolution?run_id=run-1"),
    true,
  );
  assert.equal(
    isLegacyHashForView("benchmark", "#evolution?run_id=run-1"),
    false,
  );
  assert.equal(isLegacyHashForView("lobby", ""), true);
  assert.equal(viewFromHash(""), "lobby");
  assert.equal(viewFromHash("#logs?game_id=game-7"), "logs");
  assert.equal(viewFromHash("#benchmark?batch_id=bench-1"), "benchmark");
  assert.equal(viewFromHash("#tasks?task_id=task-1"), "tasks");
  assert.equal(viewFromHash("#settings"), "settings");
  assert.equal(viewFromHash("#evidence?game_id=game-2"), "lobby");
});

test("extracts router query from legacy hash deep links", () => {
  assert.deepEqual(
    routeQueryFromLegacyHash("#logs?game_id=game-7&workspace=archive"),
    {
      game_id: "game-7",
      workspace: "archive",
    },
  );
  assert.deepEqual(
    routeQueryFromLegacyHash("#benchmark?batch_id=a&batch_id=b"),
    {
      batch_id: ["a", "b"],
    },
  );
  assert.deepEqual(routeQueryFromLegacyHash("#match"), {});
});

test("normalizes route query and builds stable legacy query strings", () => {
  assert.deepEqual(
    normalizeRouteQuery({
      workspace: "archive",
      game_id: "game/7",
      empty: "",
      skip: null,
      batch_id: ["bench-a", undefined, "bench-b"],
    }),
    {
      batch_id: ["bench-a", "bench-b"],
      game_id: "game/7",
      workspace: "archive",
    },
  );
  assert.equal(
    routeQueryString({
      workspace: "archive",
      game_id: "game/7",
      batch_id: ["bench-a", "bench-b"],
    }),
    "batch_id=bench-a&batch_id=bench-b&game_id=game%2F7&workspace=archive",
  );
});

test("syncs a legacy view navigation into vue-router", () => {
  const calls: unknown[] = [];
  registerLegacyViewRouter({
    replace(to: unknown) {
      calls.push(to);
      return Promise.resolve();
    },
  });

  syncRouterToLegacyView("logs", "#logs?game_id=game-7&workspace=archive");

  assert.deepEqual(calls, [
    {
      path: "/logs",
      query: { game_id: "game-7", workspace: "archive" },
      hash: "#logs?game_id=game-7&workspace=archive",
    },
  ]);
});

test("builds route locations for legacy view navigation", () => {
  assert.deepEqual(routeLocationForLegacyView("lobby"), {
    path: "/",
    query: {},
    hash: "",
  });
  assert.deepEqual(
    routeLocationForLegacyView(
      "logs",
      "#logs?game_id=game-7&workspace=archive",
    ),
    {
      path: "/logs",
      query: { game_id: "game-7", workspace: "archive" },
      hash: "#logs?game_id=game-7&workspace=archive",
    },
  );
});

test("builds route locations from router query without manual hashes", () => {
  assert.equal(
    legacyHashFromRouteQuery("logs", {
      game_id: "game-7",
      workspace: "archive",
    }),
    "#logs?game_id=game-7&workspace=archive",
  );
  assert.deepEqual(
    routeLocationForViewQuery("logs", {
      workspace: "archive",
      game_id: "game-7",
    }),
    {
      path: "/logs",
      query: { game_id: "game-7", workspace: "archive" },
      hash: "#logs?game_id=game-7&workspace=archive",
    },
  );
  assert.deepEqual(routeLocationForViewQuery("lobby", { game_id: "game-7" }), {
    path: "/",
    query: { game_id: "game-7" },
    hash: "",
  });
});

test("writeViewHash keeps legacy hash behavior and mirrors the router path", () => {
  const calls: unknown[] = [];
  globalThis.window = { location: locationLike() } as Window &
    typeof globalThis;
  registerLegacyViewRouter({
    replace(to: unknown) {
      calls.push(to);
      return Promise.resolve();
    },
  });

  writeViewHash("match");

  assert.deepEqual(calls, [{ path: "/match", query: {}, hash: "#match" }]);
});

test("writeViewHash mirrors lobby navigation into the root router path", () => {
  const calls: unknown[] = [];
  globalThis.window = { location: locationLike("#logs") } as Window &
    typeof globalThis;
  registerLegacyViewRouter({
    replace(to: unknown) {
      calls.push(to);
      return Promise.resolve();
    },
  });

  writeViewHash("lobby");

  assert.deepEqual(calls, [{ path: "/", query: {}, hash: "" }]);
});

test("writeViewHash falls back to legacy hashes when no router is registered", () => {
  globalThis.window = { location: locationLike() } as Window &
    typeof globalThis;

  writeViewHash("match");
  assert.equal(window.location.hash, "#match");

  writeViewHash("lobby");
  assert.equal(window.location.hash, "");
});

test("writeViewHash falls back to legacy hashes when router navigation fails", async () => {
  globalThis.window = { location: locationLike() } as Window &
    typeof globalThis;
  registerLegacyViewRouter({
    replace() {
      return Promise.reject(new Error("router offline"));
    },
  });

  writeViewHash("logs");
  await Promise.resolve();
  await Promise.resolve();

  assert.equal(window.location.hash, "#logs");
});

test("writes explicit legacy hashes through the registered router", () => {
  const calls: unknown[] = [];
  globalThis.window = { location: locationLike() } as Window &
    typeof globalThis;
  registerLegacyViewRouter({
    replace(to: unknown) {
      calls.push(to);
      return Promise.resolve();
    },
  });

  writeLegacyHashForView("logs", "#logs?game_id=game-7&workspace=archive");

  assert.deepEqual(calls, [
    {
      path: "/logs",
      query: { game_id: "game-7", workspace: "archive" },
      hash: "#logs?game_id=game-7&workspace=archive",
    },
  ]);
});

test("writes router query locations through the registered router", () => {
  const calls: unknown[] = [];
  globalThis.window = { location: locationLike() } as Window &
    typeof globalThis;
  registerLegacyViewRouter({
    replace(to: unknown) {
      calls.push(to);
      return Promise.resolve();
    },
  });

  writeViewRoute("logs", { game_id: "game-7", workspace: "archive" });

  assert.deepEqual(calls, [
    {
      path: "/logs",
      query: { game_id: "game-7", workspace: "archive" },
      hash: "#logs?game_id=game-7&workspace=archive",
    },
  ]);
});

test("writes current view state and router route through one helper", () => {
  const calls: unknown[] = [];
  const currentView: { value: AppView } = { value: "lobby" };
  globalThis.window = { location: locationLike() } as Window &
    typeof globalThis;
  registerLegacyViewRouter({
    replace(to: unknown) {
      calls.push(to);
      return Promise.resolve();
    },
  });

  writeCurrentViewRoute(currentView, "match");

  assert.equal(currentView.value, "match");
  assert.deepEqual(calls, [{ path: "/match", query: {}, hash: "#match" }]);
});

test("syncs current view state to a matching legacy hash without dropping query", () => {
  const calls: unknown[] = [];
  const currentView: { value: AppView } = { value: "lobby" };
  globalThis.window = {
    location: locationLike("#match?mode=play"),
  } as Window & typeof globalThis;
  registerLegacyViewRouter({
    replace(to: unknown) {
      calls.push(to);
      return Promise.resolve();
    },
  });

  assert.equal(syncCurrentViewToLegacyHash(currentView, "match"), true);

  assert.equal(currentView.value, "match");
  assert.deepEqual(calls, [
    { path: "/match", query: { mode: "play" }, hash: "#match?mode=play" },
  ]);
});

test("can push router query locations while retaining legacy hash fallback", () => {
  const calls: unknown[] = [];
  globalThis.window = { location: locationLike() } as Window &
    typeof globalThis;
  registerLegacyViewRouter({
    replace() {
      throw new Error("replace should not be used");
    },
    push(to: unknown) {
      calls.push(to);
      return Promise.resolve();
    },
  });

  writeViewRoute("benchmark", { batch_id: "bench-7" }, { mode: "push" });

  assert.deepEqual(calls, [
    {
      path: "/benchmark",
      query: { batch_id: "bench-7" },
      hash: "#benchmark?batch_id=bench-7",
    },
  ]);
});

test("writes explicit legacy hashes to the window without a router", () => {
  globalThis.window = { location: locationLike() } as Window &
    typeof globalThis;

  writeLegacyHashForView("logs", "#logs?game_id=game-7&workspace=archive");

  assert.equal(currentLegacyHash(), "#logs?game_id=game-7&workspace=archive");
});

test("reads the current legacy view with a server-side fallback", () => {
  if (originalWindow === undefined)
    delete (globalThis as { window?: Window }).window;
  else globalThis.window = undefined as unknown as Window & typeof globalThis;
  assert.equal(currentLegacyView("match"), "match");

  globalThis.window = {
    location: locationLike("#evolution?run_id=run-1"),
  } as Window & typeof globalThis;
  assert.equal(currentLegacyView(), "evolution");
});

test("registers legacy hashchange listeners and returns cleanup callbacks", () => {
  const target = eventWindowLike("#logs");
  globalThis.window = target as unknown as Window & typeof globalThis;
  const events: string[] = [];
  const remove = addLegacyHashChangeListener((event) => {
    events.push(event.newURL);
  });

  assert.equal(target.listeners("hashchange").length, 1);
  target.listeners("hashchange")[0]({
    newURL: "#logs?game_id=game-1",
  } as HashChangeEvent);
  assert.deepEqual(events, ["#logs?game_id=game-1"]);

  remove();

  assert.equal(target.listeners("hashchange").length, 0);
});

test("syncs the current legacy hash only when it matches the target view", () => {
  const calls: unknown[] = [];
  globalThis.window = {
    location: locationLike("#benchmark?batch_id=bench-7"),
  } as Window & typeof globalThis;
  registerLegacyViewRouter({
    replace(to: unknown) {
      calls.push(to);
      return Promise.resolve();
    },
  });

  assert.equal(syncCurrentLegacyHashForView("benchmark"), true);
  assert.equal(syncCurrentLegacyHashForView("evolution"), false);
  assert.deepEqual(calls, [
    {
      path: "/benchmark",
      query: { batch_id: "bench-7" },
      hash: "#benchmark?batch_id=bench-7",
    },
  ]);
});
