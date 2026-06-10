import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { test } from 'vitest'
import { chromium } from 'playwright'

function readSource(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8')
}

function chromiumIsInstalled() {
  try {
    return existsSync(chromium.executablePath())
  } catch {
    return false
  }
}

function assertSourceContract(source, contracts) {
  for (const [label, pattern] of contracts) {
    assert.match(source, pattern, label)
  }
}

test('Benchmark Lab views keep narrow screens constrained by scrollable table owners', () => {
  const benchmarkPage = readSource('../src/pages/BenchmarkPage.vue')
  const benchmarkSuiteRail = readSource('../src/components/benchmark/BenchmarkSuiteRail.vue')
  const batchRunsTable = readSource('../src/components/benchmark/BenchmarkBatchRunsTable.vue')
  const leaderboardTable = readSource('../src/components/benchmark/BenchmarkLeaderboardTable.vue')
  const runReport = readSource('../src/components/benchmark/BenchmarkRunReportPanel.vue')
  const snapshotRelease = readSource('../src/components/benchmark/BenchmarkSnapshotReleasePanel.vue')

  assertSourceContract(benchmarkPage, [
    ['Benchmark shell keeps suite, workspace, and context columns shrinkable', /\.bench-workbench-shell[\s\S]*--lab-rail-width:\s*252px[\s\S]*--lab-context-width:\s*300px[\s\S]*grid-template-columns:\s*var\(--lab-rail-width\) minmax\(0, 1fr\) var\(--lab-context-width\)/],
    ['Benchmark context panel owns vertical overflow', /\.bench-context-panel\s*\{[\s\S]*min-width:\s*0[\s\S]*min-height:\s*0[\s\S]*overflow-y:\s*auto/],
    ['Benchmark context cards keep content-height rows inside the scrolling panel', /\.bench-context-panel\s*\{[\s\S]*align-items:\s*start[\s\S]*grid-auto-rows:\s*max-content/],
    ['Benchmark context values ellipsize long ids', /\.bench-context-gates b,[\s\S]*\.bench-context-artifacts em\s*\{[\s\S]*min-width:\s*0[\s\S]*overflow:\s*hidden[\s\S]*text-overflow:\s*ellipsis[\s\S]*white-space:\s*nowrap/],
    ['Benchmark boundary summary lives in the context rail', /bench-context-section--boundary[\s\S]*<small>评测边界<\/small>[\s\S]*bench-context-boundary/],
    ['Benchmark right rail separates suite, boundary, and gate context', /bench-context-section--suite[\s\S]*<small>当前套件<\/small>[\s\S]*bench-context-section--boundary[\s\S]*<small>评测边界<\/small>[\s\S]*bench-context-section--gate[\s\S]*<small>入榜门禁<\/small>/],
    ['Benchmark uses compact shell command header with refresh action', /:meta="benchmarkCommandMetaRows"[\s\S]*action-label="刷新"[\s\S]*@action="refresh"/],
    ['Benchmark context rail carries selected suite detail sections', /contextSuiteDetailRows[\s\S]*contextSuiteSeedRows[\s\S]*contextSuiteMetricRows[\s\S]*contextSuiteJudgeRows[\s\S]*contextGateRows/],
    ['Benchmark overview uses a single shrinkable workspace column', /\.bench-overview\s*\{[\s\S]*grid-template-columns:\s*minmax\(0, 1fr\)/],
    ['Benchmark plan summary uses shrinkable minmax tracks', /\.bench-plan-summary\s*\{[\s\S]*grid-template-columns:\s*repeat\(4, minmax\(0, 1fr\)\)/],
    ['Benchmark diagnostic grid uses bounded shrinkable tracks', /\.bench-diagnostic-grid\s*\{[\s\S]*grid-template-columns:\s*repeat\(3, minmax\(0, 1fr\)\)/],
  ])
  assert.doesNotMatch(benchmarkPage, /:meta="labHeaderMeta"|<template #boundary>|<BenchmarkBoundaryBar|boundary-label=|:show-header="false"|<template #tabs-actions>|bench-tabs-refresh/)
  assert.doesNotMatch(benchmarkPage, /<small>评测口径<\/small>|bench-plan-grid|bench-cost-breakdown|bench-policy-breakdown/)

  assertSourceContract(benchmarkSuiteRail, [
    ['Benchmark suite rail keeps rows as selection-only entries', /<span class="suite-row-main">[\s\S]*<strong>{{ suite\.label }}<\/strong>[\s\S]*<em>{{ suite\.id }}<\/em>/],
  ])
  assert.doesNotMatch(benchmarkSuiteRail, /suite-rail-summary|suite-row-tags|suite-row-meta|suite-row-foot|suite-row-activity|suite-rail-selected|selectedSpecRows|selectedSeedRows|selectedMetricRows|selectedGateRows|selectedJudgeRows/)

  assertSourceContract(batchRunsTable, [
    ['Batch run table owns horizontal overflow', /\.bench-table\s*\{[\s\S]*overflow-x:\s*auto/],
    ['Batch run rows keep their wide columns inside the table scroller', /\.bench-row\s*\{[\s\S]*min-width:\s*880px/],
    ['Batch run cells ellipsize instead of widening the page', /\.bench-row span,[\s\S]*\.bench-id\s*\{[\s\S]*min-width:\s*0[\s\S]*overflow:\s*hidden[\s\S]*text-overflow:\s*ellipsis[\s\S]*white-space:\s*nowrap/],
    ['Batch run layout stacks to one column below tablet width', /@media \(max-width: 960px\)[\s\S]*\.bench-runs-layout\s*\{[\s\S]*grid-template-columns:\s*1fr/],
    ['Batch run stats collapse to two columns on phones', /@media \(max-width: 640px\)[\s\S]*\.bench-run-stats\s*\{[\s\S]*grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\)/],
  ])

  assertSourceContract(leaderboardTable, [
    ['Leaderboard table owns horizontal overflow', /\.bench-table\s*\{[\s\S]*overflow-x:\s*auto/],
    ['Leaderboard rows keep wide columns inside the table scroller', /\.bench-row\s*\{[\s\S]*min-width:\s*580px/],
    ['Leaderboard board layout stacks below tablet width', /@media \(max-width: 960px\)[\s\S]*\.bench-board-layout\s*\{[\s\S]*grid-template-columns:\s*1fr/],
    ['Leaderboard cards make header metadata shrinkable on phones', /@media \(max-width: 640px\)[\s\S]*\.bench-card header\s*\{[\s\S]*grid-template-columns:\s*minmax\(0, 1fr\)/],
  ])

  assertSourceContract(runReport, [
    ['Run report problem-game table does not widen its parent', /\.game-table\s*\{[\s\S]*min-width:\s*0[\s\S]*overflow:\s*hidden/],
    ['Run report rows use shrinkable identity columns', /\.game-row\s*\{[\s\S]*grid-template-columns:\s*minmax\(150px, 1\.3fr\)[\s\S]*min-width:\s*0/],
    ['Run report tags wrap long metadata chips', /\.tag-list\s*\{[\s\S]*flex-wrap:\s*wrap/],
    ['Run report keeps export actions in the side column without a preview textarea', /class="report-section report-export"[\s\S]*class="export-actions"[\s\S]*copyExport\('json'\)[\s\S]*copyExport\('csv'\)/],
  ])
  assert.doesNotMatch(runReport, /<textarea :value="markdownReport"|\.report-export textarea|report-bundle|report-header-grid/)

  assertSourceContract(snapshotRelease, [
    ['Snapshot delta table clips inside its panel', /\.snapshot-delta-table\s*\{[\s\S]*overflow:\s*hidden/],
    ['Snapshot delta rows use shrinkable cells', /\.snapshot-delta-row\s*\{[\s\S]*grid-template-columns:\s*minmax\(190px, 1fr\)[\s\S]*min-width:\s*0/],
    ['Snapshot chips wrap instead of stretching the page', /\.snapshot-chip-list\s*\{[\s\S]*flex-wrap:\s*wrap/],
  ])
})

test('Evolution Trust drawer and navigation keep mobile overflow local', () => {
  const evolutionPage = readSource('../src/pages/EvolutionPage.vue')
  const trustDrawer = readSource('../src/components/evolution/TrustBundleDrawer.vue')

  assertSourceContract(evolutionPage, [
    ['Evolution desktop shell uses a shrinkable content column', /\.evo-shell\s*\{[\s\S]*grid-template-columns:\s*248px minmax\(0, 1fr\)/],
    ['Evolution nav owns horizontal overflow', /\.evo-nav\s*\{[\s\S]*overflow-x:\s*auto/],
    ['Evolution mobile shell suppresses document-level x overflow', /@media \(max-width: 960px\)[\s\S]*\.evo-shell,[\s\S]*\.evo-shell\.parchment-logbook\s*\{[\s\S]*grid-template-columns:\s*1fr[\s\S]*overflow-x:\s*hidden/],
    ['Evolution role rail becomes a local horizontal scroller', /@media \(max-width: 960px\)[\s\S]*\.evo-role-list\s*\{[\s\S]*display:\s*flex[\s\S]*overflow-x:\s*auto/],
    ['Evolution phone nav uses bounded equal-width tracks', /@media \(max-width: 640px\)[\s\S]*\.evo-nav\s*\{[\s\S]*grid-template-columns:\s*repeat\(7, minmax\(0, 1fr\)\)/],
  ])

  assertSourceContract(trustDrawer, [
    ['Trust drawer is constrained by viewport height and scrolls vertically', /\.evo-trust-drawer\s*\{[\s\S]*max-height:\s*100vh[\s\S]*overflow:\s*auto/],
    ['Trust authority rows use shrinkable value columns', /\.evo-trust-authority\s*\{[\s\S]*grid-template-columns:\s*auto minmax\(0, 1fr\)[\s\S]*min-width:\s*0/],
    ['Trust consistency values wrap dense ids', /\.evo-trust-check-values\s*\{[\s\S]*flex-wrap:\s*wrap[\s\S]*min-width:\s*0/],
    ['Trust field grid uses shrinkable columns', /\.evo-trust-field-grid\s*\{[\s\S]*grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\)/],
    ['Trust evidence chips wrap instead of expanding the drawer', /\.evo-trust-chip-row,[\s\S]*\.evo-trust-id-grid\s*\{[\s\S]*flex-wrap:\s*wrap[\s\S]*min-width:\s*0/],
    ['Trust seed table owns horizontal overflow', /\.evo-trust-seed-table\s*\{[\s\S]*overflow-x:\s*auto/],
    ['Trust drawer becomes full-width on phones', /@media \(max-width: 760px\)[\s\S]*\.evo-trust-drawer\s*\{[\s\S]*width:\s*100vw[\s\S]*border-left:\s*0/],
    ['Trust mobile fields collapse to one shrinkable column', /@media \(max-width: 760px\)[\s\S]*\.evo-trust-field-grid,[\s\S]*\.evo-trust-authority\s*\{[\s\S]*grid-template-columns:\s*minmax\(0, 1fr\)/],
  ])
})

test('History Review and detail context keep audit content inside narrow viewports', () => {
  const logsPage = readSource('../src/pages/LogsPage.vue')
  const reviewReport = readSource('../src/components/history/ReviewReportPanel.vue')

  assertSourceContract(logsPage, [
    ['Logs detail collapses to one content column below desktop width', /@media \(max-width: 1120px\)[\s\S]*\.detail-content\s*\{[\s\S]*grid-template-columns:\s*1fr[\s\S]*overflow-y:\s*auto/],
    ['Logs side column hides x overflow when stacked', /@media \(max-width: 1120px\)[\s\S]*\.detail-side-column\s*\{[\s\S]*grid-template-columns:\s*1fr[\s\S]*overflow-x:\s*hidden/],
    ['Logs shell suppresses x overflow on mobile', /@media \(max-width: 960px\)[\s\S]*\.battle-log-shell\s*\{[\s\S]*grid-template-columns:\s*1fr[\s\S]*overflow-x:\s*hidden/],
    ['Logs review/archive main columns hide x overflow', /\.detail-content\.workspace-review \.detail-main-column,[\s\S]*\.detail-content\.workspace-archive \.detail-main-column\s*\{[\s\S]*overflow-x:\s*hidden[\s\S]*scrollbar-gutter:\s*stable/],
    ['Logs detail topbar keeps compact metadata phase-only', /const detailMetaItems = computed\(\(\) =>[\s\S]*<div v-if="selectedHistoryGame" :class="\['detail-topbar', 'workspace-' \+ workspaceTab\]">[\s\S]*<div v-if="workspaceTab === 'phase'" class="detail-context-line" aria-label="对局配置">[\s\S]*v-for="item in detailMetaItems"/],
    ['Logs compact metadata line clips dense ids', /\.detail-context-line\s*\{[\s\S]*flex-wrap:\s*nowrap[\s\S]*overflow:\s*hidden/],
    ['Logs compact metadata values ellipsize long ids', /\.detail-context-line b\s*\{[\s\S]*min-width:\s*0[\s\S]*overflow:\s*hidden[\s\S]*text-overflow:\s*ellipsis/],
    ['Logs compact metadata stacks below review width', /@media \(max-width: 920px\)[\s\S]*\.detail-topbar\.workspace-phase\s*\{[\s\S]*grid-template-areas:\s*"workspace"\s*"context"\s*"phases"/],
    ['Logs phone layout keeps detail columns single-column', /@media \(max-width: 640px\)[\s\S]*\.detail-content,[\s\S]*\.detail-side-column\s*\{[\s\S]*grid-template-columns:\s*1fr/],
    ['Logs raw log headers wrap on phones', /@media \(max-width: 640px\)[\s\S]*\.history-raw-log header\s*\{[\s\S]*flex-wrap:\s*wrap/],
  ])
  assert.doesNotMatch(logsPage, /import EvidenceContextBar from '\.\.\/components\/history\/EvidenceContextBar\.vue'/)

  assertSourceContract(reviewReport, [
    ['Review report does not duplicate the shared evidence context', /<section class="archive-review-panel">[\s\S]*<h3>复盘报告<\/h3>(?![\s\S]*review-evidence-context)/],
    ['Review summary chips wrap', /\.review-summary-strip\s*\{[\s\S]*flex-wrap:\s*wrap/],
    ['Review judge summary uses shrinkable metric columns', /\.review-judge-summary\s*\{[\s\S]*grid-template-columns:\s*repeat\(4, minmax\(0, 1fr\)\)/],
    ['Review judge cards use shrinkable columns', /\.review-judge-list\s*\{[\s\S]*grid-template-columns:\s*repeat\(3, minmax\(0, 1fr\)\)/],
    ['Review turning point badges wrap', /\.review-tp-badges\s*\{[\s\S]*flex-wrap:\s*wrap/],
    ['Review summary becomes two columns on narrow screens', /@media \(max-width: 720px\)[\s\S]*\.review-summary-strip\s*\{[\s\S]*grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\)/],
    ['Review timeline becomes one column at 420px', /@media \(max-width: 420px\)[\s\S]*\.review-tl-item\s*\{[\s\S]*grid-template-columns:\s*minmax\(0, 1fr\)/],
  ])
})

test('390px mobile fixture keeps review evidence and Lab tables from widening the document', { timeout: 30000 }, async (t) => {
  if (!chromiumIsInstalled()) {
    t.skip('Playwright Chromium is not installed; source-level mobile layout contracts are still covered.')
    return
  }

  let browser = null
  try {
    browser = await chromium.launch()
    const page = await browser.newPage({
      viewport: { width: 390, height: 844 },
      isMobile: true,
      deviceScaleFactor: 2,
    })

    await page.setContent(`
      <!doctype html>
      <html>
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
          <style>
            * { box-sizing: border-box; }
            html, body {
              width: 100%;
              min-height: 100%;
              margin: 0;
              background: #f1ead8;
              color: #2f2519;
              font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            }
            .mobile-audit-fixture {
              display: grid;
              gap: 12px;
              width: 100%;
              max-width: 100vw;
              padding:
                calc(12px + env(safe-area-inset-top, 0px))
                calc(10px + env(safe-area-inset-right, 0px))
                calc(14px + env(safe-area-inset-bottom, 0px))
                calc(10px + env(safe-area-inset-left, 0px));
              overflow-x: hidden;
            }
            .review-panel,
            .lab-panel {
              display: grid;
              gap: 10px;
              min-width: 0;
              padding: 12px;
              border: 1px solid rgba(93, 48, 17, 0.18);
              border-radius: 8px;
              background: rgba(255, 252, 245, 0.76);
            }
            .detail-topbar {
              display: grid;
              gap: 8px;
              width: 100%;
              min-width: 0;
              padding: 8px;
              border: 1px solid rgba(92, 54, 20, 0.18);
              border-radius: 8px;
              background: rgba(255, 249, 232, 0.72);
            }
            .detail-context-line {
              display: flex;
              flex-wrap: nowrap;
              align-items: center;
              gap: 10px;
              min-width: 0;
              overflow: hidden;
              color: rgba(74, 37, 15, 0.72);
              font-size: 12px;
              font-weight: 900;
            }
            .detail-context-line span {
              display: inline-flex;
              align-items: baseline;
              flex: 0 1 auto;
              gap: 2px;
              max-width: 100%;
              min-width: 0;
              white-space: nowrap;
            }
            .detail-context-line small {
              flex: 0 0 auto;
              color: rgba(74, 37, 15, 0.58);
            }
            .detail-context-line b {
              min-width: 0;
              overflow: hidden;
              text-overflow: ellipsis;
              white-space: nowrap;
              color: #3b1c09;
            }
            .review-summary-strip {
              display: grid;
              grid-template-columns: repeat(2, minmax(0, 1fr));
              gap: 8px;
              min-width: 0;
            }
            .review-summary-item,
            .review-judge-card {
              min-width: 0;
              padding: 8px 9px;
              border: 1px solid rgba(93, 48, 17, 0.14);
              border-radius: 6px;
              background: rgba(255, 239, 194, 0.46);
            }
            .review-summary-item b,
            .review-judge-card strong {
              display: block;
              min-width: 0;
              overflow: hidden;
              text-overflow: ellipsis;
              white-space: nowrap;
            }
            .review-judge-section {
              display: grid;
              grid-template-columns: minmax(0, 1fr);
              gap: 8px;
              min-width: 0;
            }
            .review-judge-card p {
              margin: 6px 0 0;
              overflow-wrap: anywhere;
              font-size: 12px;
              line-height: 1.45;
            }
            .lab-table {
              display: flex;
              flex-direction: column;
              width: 100%;
              max-width: 100%;
              min-width: 0;
              overflow-x: auto;
              border: 1px solid rgba(31, 111, 84, 0.18);
              border-radius: 7px;
              background: #ffffff;
            }
            .lab-row {
              display: grid;
              grid-template-columns:
                minmax(86px, 0.5fr)
                minmax(156px, 0.95fr)
                minmax(130px, 0.8fr)
                minmax(76px, 0.45fr)
                minmax(80px, 0.5fr)
                minmax(82px, 0.48fr)
                minmax(124px, 0.62fr);
              gap: 10px;
              align-items: center;
              min-width: 880px;
              padding: 9px 10px;
              border-bottom: 1px solid #e2e8e5;
            }
            .lab-row span,
            .lab-row small {
              min-width: 0;
              overflow: hidden;
              text-overflow: ellipsis;
              white-space: nowrap;
            }
            .lab-row small {
              color: #62706a;
            }
          </style>
        </head>
        <body>
          <main class="mobile-audit-fixture">
            <section class="review-panel" aria-label="review evidence fixture">
              <section class="detail-topbar workspace-phase" data-source="benchmark">
                <div class="detail-context-line" aria-label="对局配置">
                  <span><small>来源：</small><b>benchmark_release_evidence_bundle_with_long_identifier</b></span>
                  <span><small>运行：</small><b>benchmark_run_260609_mobile_safe_area_contract_long_hash</b></span>
                  <span><small>版本：</small><b>seer=v_prod_candidate_20260609, wolf=v_baseline_20260601</b></span>
                </div>
              </section>
              <div class="review-summary-strip">
                <span class="review-summary-item"><small>winner</small><b>villagers_with_long_label</b></span>
                <span class="review-summary-item"><small>seed</small><b>260609390844</b></span>
                <span class="review-summary-item"><small>judge</small><b>paired_seed_gate_passed</b></span>
                <span class="review-summary-item"><small>evidence</small><b>authority_bundle_verified</b></span>
              </div>
              <section class="review-judge-section">
                <article class="review-judge-card">
                  <strong>1号 预言家 candidate_long_role_version</strong>
                  <p>这是一条很长的审核原因，用于验证文字只能在卡片内部换行，不能把 review 面板撑出 390px 视口。</p>
                </article>
                <article class="review-judge-card">
                  <strong>7号 狼人 baseline_long_role_version</strong>
                  <p>paired seed 明细、judge 证据和 reject reason 需要在同一个窄屏审核流内保持可读。</p>
                </article>
              </section>
            </section>
            <section class="lab-panel" aria-label="Lab table fixture">
              <div class="lab-table" role="table">
                <div class="lab-row" role="row">
                  <span>run_260609_mobile_safe_area_long_identifier</span>
                  <span>seer / candidate_release_track</span>
                  <span>benchmark_release_suite</span>
                  <span>running</span>
                  <span>42%</span>
                  <small>judge 0.72</small>
                  <span>打开报告</span>
                </div>
                <div class="lab-row" role="row">
                  <span>run_260609_mobile_safe_area_baseline</span>
                  <span>wolf / baseline_registry_track</span>
                  <span>paired_seed_suite</span>
                  <span>review</span>
                  <span>100%</span>
                  <small>judge 0.69</small>
                  <span>回放样本局</span>
                </div>
              </div>
            </section>
          </main>
        </body>
      </html>
    `, { waitUntil: 'load' })

    const summary = await page.evaluate(() => {
      const viewport = { width: window.innerWidth, height: window.innerHeight }
      const selectors = [
        '.mobile-audit-fixture',
        '.review-panel',
        '.detail-topbar',
        '.detail-context-line',
        '.detail-context-line span',
        '.review-summary-strip',
        '.review-judge-section',
        '.lab-panel',
        '.lab-table',
      ]
      const rects = selectors.map((selector) => {
        const element = document.querySelector(selector)
        const rect = element.getBoundingClientRect()
        const style = getComputedStyle(element)
        return {
          selector,
          left: rect.left,
          right: rect.right,
          width: rect.width,
          height: rect.height,
          overflowX: style.overflowX,
          scrollWidth: element.scrollWidth,
          clientWidth: element.clientWidth,
        }
      })
      const labTable = document.querySelector('.lab-table')
      return {
        viewport,
        documentClientWidth: document.documentElement.clientWidth,
        documentScrollWidth: document.documentElement.scrollWidth,
        bodyClientWidth: document.body.clientWidth,
        bodyScrollWidth: document.body.scrollWidth,
        bodyTextLength: document.body.innerText.trim().length,
        rects,
        labTable: {
          scrollWidth: labTable.scrollWidth,
          clientWidth: labTable.clientWidth,
          overflowX: getComputedStyle(labTable).overflowX,
        },
      }
    })

    assert.equal(summary.viewport.width, 390)
    assert.equal(summary.viewport.height, 844)
    assert.ok(summary.bodyTextLength > 220)
    assert.ok(
      summary.documentScrollWidth <= summary.documentClientWidth,
      `document overflows horizontally: ${summary.documentScrollWidth} > ${summary.documentClientWidth}`,
    )
    assert.ok(
      summary.bodyScrollWidth <= summary.bodyClientWidth,
      `body overflows horizontally: ${summary.bodyScrollWidth} > ${summary.bodyClientWidth}`,
    )

    for (const rect of summary.rects) {
      assert.ok(rect.width > 0, `${rect.selector} should be visible`)
      assert.ok(rect.left >= -0.5, `${rect.selector} overflows left: ${rect.left}`)
      assert.ok(rect.right <= summary.viewport.width + 0.5, `${rect.selector} overflows right: ${rect.right}`)
    }

    assert.equal(summary.labTable.overflowX, 'auto')
    assert.ok(
      summary.labTable.scrollWidth > summary.labTable.clientWidth,
      'Lab table should keep wide columns inside its own horizontal scroller',
    )

    console.info(`mobile layout fixture viewport=${summary.viewport.width}x${summary.viewport.height}; labTable=${summary.labTable.clientWidth}/${summary.labTable.scrollWidth}`)
  } finally {
    await browser?.close()
  }
})
