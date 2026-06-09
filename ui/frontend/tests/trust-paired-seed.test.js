import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const drawer = readFileSync(
  new URL('../src/components/evolution/TrustBundleDrawer.vue', import.meta.url),
  'utf8'
)

function assertSourceContract(source, contracts) {
  for (const [label, pattern] of contracts) {
    assert.match(source, pattern, label)
  }
}

test('TrustBundleDrawer links paired seed game ids to Logs archive workspace', () => {
  assertSourceContract(drawer, [
    ['paired seeds are normalized before rendering', /const seedRows = computed\(\(\) => pairedSeeds\.value\.slice\(0, 12\)\.map\(normalizeSeedRow\)\)/],
    ['game id helper accepts camelCase and snake_case baseline fields', /function seedGameId\(seed, side\)[\s\S]*seed\?\.\[`\$\{prefix\}GameId`\][\s\S]*seed\?\.\[`\$\{prefix\}_game_id`\][\s\S]*nested\.game_id[\s\S]*nested\.gameId/],
    ['game link helper targets the Logs archive workspace with game_id query', /function seedGameHref\(gameId\)[\s\S]*#logs\?\$\{new URLSearchParams\(\{ game_id: id, workspace: 'archive' \}\)\.toString\(\)\}/],
    ['baseline game id renders as a Logs archive link when present', /<a v-if="seed\.baselineGameHref" :href="seed\.baselineGameHref">\{\{ seed\.baselineGameId \}\}<\/a>/],
    ['candidate game id renders as a Logs archive link when present', /<a v-if="seed\.candidateGameHref" :href="seed\.candidateGameHref">\{\{ seed\.candidateGameId \}\}<\/a>/],
    ['missing game ids fall back to compact empty display cells', /<code v-else>\{\{ display\(seed\.baselineGameId\) \}\}<\/code>[\s\S]*<code v-else>\{\{ display\(seed\.candidateGameId\) \}\}<\/code>/],
  ])
})

test('TrustBundleDrawer renders paired seed rankable status and failure evidence only when present', () => {
  assertSourceContract(drawer, [
    ['rankable helper accepts direct and alias fields', /function rankableLabel\(seed\)[\s\S]*seed\?\.rankable[\s\S]*seed\?\.rankableStatus[\s\S]*seed\?\.rankable_status/],
    ['status helper accepts result outcome and pair_status aliases', /function seedStatusLabel\(seed\)[\s\S]*seed\?\.status[\s\S]*seed\?\.result[\s\S]*seed\?\.outcome[\s\S]*seed\?\.pair_status/],
    ['failure helper accepts normalized and source failure fields', /function failureReason\(seed\)[\s\S]*seed\?\.failureReason[\s\S]*seed\?\.failure_reason[\s\S]*seed\?\.rankableReason[\s\S]*seed\?\.rankable_reason[\s\S]*failure\.message/],
    ['audit badge list is assembled from non-empty values', /function seedAuditBadges\(seed\)[\s\S]*if \(rankable\)[\s\S]*if \(status && status !== rankable\)[\s\S]*if \(failure\)/],
    ['template renders no placeholder badge when audit metadata is empty', /<div class="evo-trust-seed-audit">[\s\S]*v-for="badge in seed\.auditBadges"[\s\S]*<\/div>/],
    ['audit badges expose stable tone classes and titles for long failure reasons', /:class="\['evo-trust-seed-badge', `tone-\$\{badge\.tone\}`\]"[\s\S]*:title="badge\.value"/],
  ])
})

test('TrustBundleDrawer keeps the expanded paired seed table inside a local scroller', () => {
  assertSourceContract(drawer, [
    ['paired seed table has the expanded audit columns', /<span>Seed<\/span>[\s\S]*<span>基线<\/span>[\s\S]*<span>候选<\/span>[\s\S]*<span>差值<\/span>[\s\S]*<span>胜方<\/span>[\s\S]*<span>基线局<\/span>[\s\S]*<span>候选局<\/span>[\s\S]*<span>审计<\/span>/],
    ['base table owns horizontal overflow', /\.evo-trust-seed-table\s*\{[\s\S]*grid-template-columns:[\s\S]*repeat\(2, minmax\(112px, 1fr\)\)[\s\S]*max-width:\s*100%[\s\S]*overflow-x:\s*auto[\s\S]*overflow-y:\s*hidden/],
    ['cells clip dense ids instead of widening the drawer', /\.evo-trust-seed-table > \*\s*\{[\s\S]*min-width:\s*0[\s\S]*overflow:\s*hidden[\s\S]*text-overflow:\s*ellipsis[\s\S]*white-space:\s*nowrap/],
    ['audit badges can wrap within the audit cell', /\.evo-trust-seed-audit\s*\{[\s\S]*flex-wrap:\s*wrap[\s\S]*min-width:\s*0[\s\S]*white-space:\s*normal/],
    ['mobile table keeps the same local scroller contract', /@media \(max-width: 760px\)[\s\S]*\.evo-trust-seed-table\s*\{[\s\S]*repeat\(2, minmax\(128px, 1fr\)\)[\s\S]*overflow-x:\s*auto/],
  ])
})
