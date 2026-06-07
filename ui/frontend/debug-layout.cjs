const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

  await page.goto('http://127.0.0.1:5173/#logs');
  await page.waitForTimeout(3000);

  // Click first game if available
  const gameItem = page.locator('.history-game-item').first();
  if (await gameItem.isVisible()) {
    await gameItem.click();
    await page.waitForTimeout(2000);
  }

  // Full page screenshot
  await page.screenshot({ path: 'debug-full.png', fullPage: false });

  // Measure sidebar layout
  const debug = await page.evaluate(() => {
    const sideColumn = document.querySelector('.detail-side-column');
    const sideCards = document.querySelectorAll('.history-side-card');
    const seatLedger = document.querySelector('.history-seat-ledger');
    const assessModule = document.querySelector('.multi-assess-module');
    const detailContent = document.querySelector('.detail-content');
    const mainColumn = document.querySelector('.detail-main-column');
    const pageDetail = document.querySelector('.history-page-detail');

    function rect(el) {
      if (!el) return null;
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      return {
        top: Math.round(r.top), left: Math.round(r.left),
        width: Math.round(r.width), height: Math.round(r.height),
        bottom: Math.round(r.bottom), right: Math.round(r.right),
        overflow: cs.overflow, overflowY: cs.overflowY, overflowX: cs.overflowX,
        minHeight: cs.minHeight, maxHeight: cs.maxHeight, heightStyle: cs.height,
      };
    }

    return {
      viewport: { width: window.innerWidth, height: window.innerHeight },
      detailContent: rect(detailContent),
      mainColumn: rect(mainColumn),
      pageDetail: rect(pageDetail),
      sideColumn: rect(sideColumn),
      sideCards: [...sideCards].map((c, i) => ({ index: i, class: c.className, ...rect(c) })),
      seatLedger: rect(seatLedger),
      assessModule: rect(assessModule),
      // Check if any content overflows
      sideColumnScroll: sideColumn ? {
        scrollHeight: sideColumn.scrollHeight,
        clientHeight: sideColumn.clientHeight,
        overflows: sideColumn.scrollHeight > sideColumn.clientHeight,
      } : null,
      // Check seat ledger grid
      seatLedgerGrid: seatLedger ? {
        childCount: seatLedger.children.length,
        gridCols: getComputedStyle(seatLedger).gridTemplateColumns,
      } : null,
    };
  });

  console.log(JSON.stringify(debug, null, 2));

  // Screenshot just the sidebar area
  if (debug.sideColumn) {
    const sc = debug.sideColumn;
    await page.screenshot({
      path: 'debug-sidebar.png',
      clip: { x: Math.max(0, sc.left - 10), y: Math.max(0, sc.top - 10), width: sc.width + 20, height: Math.min(debug.viewport.height, sc.height + 20) }
    });
  }

  await browser.close();
})();
