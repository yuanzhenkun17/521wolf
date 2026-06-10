import type { LocationQueryRaw, Router } from "vue-router";
import type { AppView } from "../types/ui";
import { appViewFromLegacyHash, appViewHash, appViewPath } from "./appViews";

type LegacyViewRouter = Pick<Router, "replace"> & Partial<Pick<Router, "push">>;
type ViewRouteNavigationMode = "push" | "replace";
type LegacyCurrentViewRef = { value: AppView };

let activeRouter: LegacyViewRouter | null = null;

export interface LegacyViewRouteLocation {
  path: string;
  query: LocationQueryRaw;
  hash: string;
}

export function registerLegacyViewRouter(
  router: LegacyViewRouter | null,
): void {
  activeRouter = router;
}

export function routePathForView(view: AppView): string {
  return appViewPath(view);
}

export function routeQueryFromLegacyHash(hash = ""): LocationQueryRaw {
  const queryString = String(hash || "").split("?")[1] || "";
  const params = new URLSearchParams(queryString);
  const query: LocationQueryRaw = {};

  params.forEach((value, key) => {
    const existing = query[key];
    if (existing === undefined) {
      query[key] = value;
    } else if (Array.isArray(existing)) {
      existing.push(value);
    } else {
      query[key] = [existing, value];
    }
  });

  return query;
}

function routeQueryValueTexts(value: unknown): string[] {
  if (Array.isArray(value)) return value.flatMap(routeQueryValueTexts);
  if (value == null) return [];
  const text = String(value).trim();
  return text ? [text] : [];
}

export function normalizeRouteQuery(
  query: LocationQueryRaw = {},
): LocationQueryRaw {
  const normalized: LocationQueryRaw = {};
  Object.keys(query)
    .sort()
    .forEach((key) => {
      const values = routeQueryValueTexts(query[key]);
      if (!values.length) return;
      normalized[key] = values.length === 1 ? values[0] : values;
    });
  return normalized;
}

export function routeQueryString(query: LocationQueryRaw = {}): string {
  const params = new URLSearchParams();
  const normalized = normalizeRouteQuery(query);
  Object.keys(normalized).forEach((key) => {
    routeQueryValueTexts(normalized[key]).forEach((value) =>
      params.append(key, value),
    );
  });
  return params.toString();
}

export function viewFromHash(
  hash = globalThis.window?.location?.hash || "",
): AppView {
  return appViewFromLegacyHash(hash);
}

export function hashForView(view: AppView = "lobby"): string {
  return appViewHash(view);
}

export function currentLegacyHash(): string {
  return typeof window === "undefined"
    ? ""
    : String(window.location.hash || "");
}

export function currentLegacyView(fallback: AppView = "lobby"): AppView {
  if (typeof window === "undefined") return fallback;
  return viewFromHash(currentLegacyHash());
}

export function addLegacyHashChangeListener(
  handler: (event: HashChangeEvent) => void,
): () => void {
  if (typeof window === "undefined") return () => {};
  window.addEventListener("hashchange", handler);
  return () => window.removeEventListener("hashchange", handler);
}

export function routeHashFromLegacyHash(hash = ""): string {
  return String(hash || "").split("?")[0];
}

export function isLegacyHashForView(
  view: AppView,
  hash = currentLegacyHash(),
): boolean {
  const viewHash = hashForView(view);
  const routeHash = routeHashFromLegacyHash(hash);
  return viewHash ? routeHash === `#${viewHash}` : !routeHash;
}

export function routeLocationForLegacyView(
  view: AppView,
  hash = "",
): LegacyViewRouteLocation {
  const legacyHash = String(hash || "");
  return {
    path: routePathForView(view),
    query: routeQueryFromLegacyHash(legacyHash),
    hash: legacyHash,
  };
}

export function legacyHashFromRouteQuery(
  view: AppView,
  query: LocationQueryRaw = {},
): string {
  const hash = hashForView(view);
  if (!hash) return "";
  const queryString = routeQueryString(query);
  return queryString ? `#${hash}?${queryString}` : `#${hash}`;
}

export function routeLocationForViewQuery(
  view: AppView,
  query: LocationQueryRaw = {},
): LegacyViewRouteLocation {
  const normalizedQuery = normalizeRouteQuery(query);
  return {
    path: routePathForView(view),
    query: normalizedQuery,
    hash: legacyHashFromRouteQuery(view, normalizedQuery),
  };
}

export function syncRouterToLegacyView(view: AppView, hash = ""): void {
  if (!activeRouter) return;
  void activeRouter
    .replace(routeLocationForLegacyView(view, hash))
    .catch(() => {});
}

function writeWindowLegacyHash(hash = ""): void {
  if (typeof window === "undefined") return;
  window.location.hash = String(hash || "");
}

export function writeLegacyHashForView(view: AppView, hash = ""): void {
  const legacyHash = String(hash || "");
  if (!activeRouter) {
    writeWindowLegacyHash(legacyHash);
    return;
  }
  void activeRouter
    .replace(routeLocationForLegacyView(view, legacyHash))
    .catch(() => writeWindowLegacyHash(legacyHash));
}

export function writeViewRoute(
  view: AppView = "lobby",
  query: LocationQueryRaw = {},
  options: { mode?: ViewRouteNavigationMode } = {},
): void {
  const location = routeLocationForViewQuery(view, query);
  if (!activeRouter) {
    writeWindowLegacyHash(location.hash);
    return;
  }
  const navigate =
    options.mode === "push" && activeRouter.push
      ? activeRouter.push.bind(activeRouter)
      : activeRouter.replace.bind(activeRouter);
  void navigate(location).catch(() => writeWindowLegacyHash(location.hash));
}

export function writeCurrentViewRoute(
  currentView: LegacyCurrentViewRef,
  view: AppView = "lobby",
  query: LocationQueryRaw = {},
  options: { mode?: ViewRouteNavigationMode } = {},
): void {
  currentView.value = view;
  writeViewRoute(view, query, options);
}

export function syncCurrentLegacyHashForView(view: AppView): boolean {
  const hash = currentLegacyHash();
  if (!isLegacyHashForView(view, hash)) return false;
  syncRouterToLegacyView(view, hash);
  return true;
}

export function syncCurrentViewToLegacyHash(
  currentView: LegacyCurrentViewRef,
  view: AppView,
): boolean {
  currentView.value = view;
  return syncCurrentLegacyHashForView(view);
}

export function writeViewHash(view: AppView = "lobby"): void {
  if (typeof window === "undefined") return;
  const hash = hashForView(view);
  const nextHash = hash ? `#${hash}` : "";
  writeLegacyHashForView(view, nextHash);
}
