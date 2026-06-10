import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "vitest";

function readSource(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), "utf8");
}

function assertSourceContract(source, contracts) {
  for (const [label, pattern] of contracts) {
    assert.match(source, pattern, label);
  }
}

test("EvidencePage is removed as a first-class route and TopNav entry", () => {
  const app = readSource("../src/App.vue");
  const gameSession = readSource("../src/composables/gameSession.ts");
  const liveState = readSource("../src/composables/useLiveGameState.ts");
  const history = readSource("../src/composables/useGameHistory.ts");
  const topNav = readSource("../src/components/TopNav.vue");

  assert.doesNotMatch(app, /EvidencePage/);
  assert.doesNotMatch(app, /evidenceProps/);
  assert.doesNotMatch(app, /inEvidence/);
  assert.doesNotMatch(app, /openEvidencePage/);
  assert.doesNotMatch(topNav, /open-evidence/);
  assert.doesNotMatch(topNav, /key: 'evidence'/);
  assert.doesNotMatch(gameSession, /evidence:\s*'evidence'/);
  assert.doesNotMatch(liveState, /computedState\.inEvidence/);
  assert.doesNotMatch(history, /async function openEvidencePage/);
});

test("legacy #evidence links are not routed or recognized", () => {
  const gameSession = readSource("../src/composables/gameSession.ts");
  const history = readSource("../src/composables/useGameHistory.ts");
  const deepLinks = readSource("../src/router/workbenchDeepLinks.ts");

  assertSourceContract(deepLinks, [
    [
      "router helper builds logs route query with game id and workspace",
      /export function logsRouteQuery\([\s\S]*query\.game_id = id[\s\S]*query\.workspace = tab/,
    ],
    [
      "router helper derives logs hashes from route query",
      /export function logsHash\([\s\S]*queryStringFromQuery\(\s*logsRouteQuery\(\{ gameId, workspace \}\),\s*\[["']game_id["'], ["']workspace["']\],?\s*\)/,
    ],
    [
      "router helper parses logs workspace query aliases",
      /export function historyDeepLinkFromHash\([\s\S]*workspace: optionalHistoryWorkspaceTab\([\s\S]*query\.get\(["']workspace["']\)\s*\|\|\s*query\.get\(["']tab["']\)/,
    ],
  ]);
  assertSourceContract(history, [
    [
      "useGameHistory imports route-first logs deep link helpers",
      /import \{ historyDeepLinkFromHash, historyDeepLinkFromRoute, logsRouteQuery \} from '..\/router\/workbenchDeepLinks'/,
    ],
    [
      "useGameHistory reads the current hash through legacy navigation helpers",
      /import \{[\s\S]*currentLegacyHash[\s\S]*writeViewRoute[\s\S]*\} from '..\/router\/legacyViewNavigation'/,
    ],
    [
      "hash routing prefers route query before legacy hash fallback",
      /return routeSource[\s\S]*historyDeepLinkFromRoute\(routeSource\)[\s\S]*historyDeepLinkFromHash\(currentLegacyHash\(\)\)/,
    ],
    [
      "logs deep links are written through route query helpers",
      /writeViewRoute\('logs', logsRouteQuery\(options\)\)/,
    ],
    [
      "openLogPage stores the requested workspace",
      /state\.historyWorkspaceTab\.value = targetWorkspace/,
    ],
  ]);
  assert.doesNotMatch(gameSession, /#evidence/);
  assert.doesNotMatch(history, /#evidence/);
  assert.doesNotMatch(history, /route\.routeHash === '#evidence'/);
  assert.doesNotMatch(history, /workspace: route\.workspace \|\| 'archive'/);
  assert.doesNotMatch(history, /state\.currentView\.value = 'evidence'/);
  assert.doesNotMatch(history, /writeViewHash\('evidence'\)/);
  assert.doesNotMatch(
    history,
    /loadArchive\(activeGameId, \{ clearNotice: false \}\)/,
  );
  assert.doesNotMatch(
    history,
    /loadReview\(activeGameId, \{ clearNotice: false \}\)/,
  );
});

test("LogsPage owns archive and review workspaces for evidence details", () => {
  const app = readSource("../src/App.vue");
  const appRuntimeProps = readSource("../src/composables/appRuntimeProps.ts");
  const refs = readSource("../src/composables/gameStateShared.ts");
  const logs = readSource("../src/pages/LogsPage.vue");

  assertSourceContract(app, [
    [
      "App passes logs props through the runtime props helper",
      /v-bind="logsProps"/,
    ],
    [
      "LogsPage binds history workspace tab through v-model",
      /v-model:history-workspace-tab="historyWorkspaceTab"/,
    ],
  ]);
  assertSourceContract(appRuntimeProps, [
    [
      "logs runtime props still carry formatter props through an explicit view-model builder",
      /function buildLogsRuntimeProps\(runtime[\s\S]*historyPhaseName: readRuntimeValue\(runtime, 'historyPhaseName'\)[\s\S]*historyNormalizeText: readRuntimeValue\(runtime, 'historyNormalizeText'\)[\s\S]*formatJson: readRuntimeValue\(runtime, 'formatJson'\)/,
    ],
  ]);
  assert.doesNotMatch(appRuntimeProps, /logsPropKeys/);
  assert.doesNotMatch(appRuntimeProps, /matchPropKeys/);
  assert.doesNotMatch(appRuntimeProps, /'historyWorkspaceTab'/);
  assert.doesNotMatch(appRuntimeProps, /'selectedHistoryPage'/);
  assert.doesNotMatch(appRuntimeProps, /'historyLogs'/);
  assert.doesNotMatch(appRuntimeProps, /'loadArchive'/);
  assert.doesNotMatch(appRuntimeProps, /'loadReview'/);
  assertSourceContract(refs, [
    [
      "runtime stores the selected logs workspace",
      /historyWorkspaceTab:\s*ref\('phase'\)/,
    ],
  ]);
  assertSourceContract(logs, [
    [
      "LogsPage accepts external workspace selection",
      /historyWorkspaceTab:\s*\{\s*type:\s*String,\s*default:\s*'phase'\s*\}/,
    ],
    [
      "LogsPage emits workspace changes back to runtime",
      /'update:historyWorkspaceTab'/,
    ],
    [
      "external workspace tab loads matching assets lazily through history actions",
      /function setWorkspaceTab\(tab[\s\S]*next === 'review'[\s\S]*runHistoryAction\('loadReview'[\s\S]*next === 'archive'[\s\S]*runHistoryAction\('loadArchive'/,
    ],
    [
      "manual game selection resets back to phase details",
      /function selectHistoryGameFromList\(gameId\)[\s\S]*setWorkspaceTab\('phase'\)[\s\S]*emit\('select-history-game', gameId\)/,
    ],
    [
      "LogsPage still renders review and archive surfaces",
      /<ReviewReportPanel[\s\S]*<GameArchivePanel/,
    ],
  ]);
});

test("GameArchivePanel keeps the staggered two-color phase index", () => {
  const archivePanel = readSource("../src/components/history/GameArchivePanel.vue");

  assertSourceContract(archivePanel, [
    [
      "archive sections animate when routed between casefile tabs",
      /\.casefile-workbench-grid\[data-active-section="casefile-evidence"\] #casefile-evidence,[\s\S]*\.casefile-workbench-grid\[data-active-section="casefile-config"\] #casefile-config\s*\{[\s\S]*display:\s*grid;[\s\S]*animation:\s*casefile-section-shift 0\.18s ease;/,
    ],
    [
      "archive section shift keyframes slide in from the right",
      /@keyframes casefile-section-shift\s*\{[\s\S]*from\s*\{[\s\S]*opacity:\s*0;[\s\S]*transform:\s*translateX\(18px\);[\s\S]*to\s*\{[\s\S]*opacity:\s*1;[\s\S]*transform:\s*translateX\(0\);/,
    ],
    [
      "archive overview uses three independent audit cards rather than one merged strip",
      /\.casefile-audit-brief\s*\{[\s\S]*grid-template-columns:\s*repeat\(3, minmax\(0, 1fr\)\);[\s\S]*gap:\s*22px;[\s\S]*border:\s*0;[\s\S]*background:\s*transparent;/,
    ],
    [
      "archive audit cards keep the parchment card surface",
      /\.casefile-audit-card\s*\{[\s\S]*min-height:\s*96px;[\s\S]*padding:\s*12px 10px;[\s\S]*border:\s*1px solid rgba\(93,\s*48,\s*17,\s*0\.18\);[\s\S]*border-radius:\s*8px;[\s\S]*box-shadow:/,
    ],
    [
      "vertical archive phase buttons keep the target alternating offset",
      /\.casefile-phase-strip--vertical \.casefile-phase-button:nth-child\(even\)\s*\{[\s\S]*margin-left:\s*82px[\s\S]*border-radius:\s*4px 30px 30px 30px[\s\S]*background:\s*#9884d7/,
    ],
    [
      "vertical archive phase buttons keep the green odd-side cards",
      /\.casefile-phase-strip--vertical \.casefile-phase-button:nth-child\(odd\)\s*\{[\s\S]*margin-left:\s*0[\s\S]*border-radius:\s*30px 30px 4px 30px[\s\S]*background:\s*#7bc58f/,
    ],
    [
      "horizontal archive phase buttons keep the lower purple row",
      /\.casefile-phase-strip--horizontal \.casefile-phase-button:nth-child\(even\)\s*\{[\s\S]*margin-top:\s*28px[\s\S]*border-radius:\s*28px 8px 28px 28px[\s\S]*background:\s*#9884d7/,
    ],
  ]);
});

test("EvidenceLink game targets point to Logs archive workspace", () => {
  const links = readSource("../src/components/history/evidenceLinks.ts");

  assert.match(
    links,
    /buildHashLink\('logs', \{ game_id: gameId, workspace: 'archive' \}\)/,
  );
  assert.match(links, /params:\s*\{ game_id: gameId, workspace: 'archive' \}/);
  assert.doesNotMatch(links, /buildHashLink\('evidence'/);
});
