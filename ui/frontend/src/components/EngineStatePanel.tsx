import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { roleName } from "../presentation";
import type { Player, RoleState } from "../types";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const ROLE_ICONS: Record<string, string> = {
  witch: "🧪",
  guard: "🛡️",
  seer: "🔮",
  hunter: "🏹",
  white_wolf_king: "🐺",
};

function hasRoleState(state: RoleState | undefined): boolean {
  if (!state) return false;
  return Object.keys(state).length > 0;
}

function checkResultLabel(result: string): { text: string; className: string } {
  if (result === "werewolves") {
    return { text: "狼人", className: "text-rose-600 font-medium" };
  }
  return { text: "好人", className: "text-emerald-600 font-medium" };
}

// ---------------------------------------------------------------------------
// Per-role card bodies
// ---------------------------------------------------------------------------

function WitchBody({ state }: { state: RoleState }) {
  const antidoteOk = state.antidote_available !== false;
  const poisonOk = state.poison_available !== false;
  const antidoteHistory = state.antidote_history ?? [];
  const poisonHistory = state.poison_history ?? [];
  const hasHistory = antidoteHistory.length > 0 || poisonHistory.length > 0;

  return (
    <div className="space-y-2 text-sm">
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        <span>
          解药: {antidoteOk
            ? <span className="text-emerald-600">✅ 可用</span>
            : <span className="text-rose-500">❌ 已用</span>}
        </span>
        <span>
          毒药: {poisonOk
            ? <span className="text-emerald-600">✅ 可用</span>
            : <span className="text-rose-500">❌ 已用</span>}
        </span>
      </div>
      <div>
        <span className="text-xs text-muted-foreground">用药历史: </span>
        {!hasHistory && <span className="text-xs text-muted-foreground">(暂无)</span>}
        {hasHistory && (
          <ul className="mt-1 space-y-0.5 text-xs">
            {antidoteHistory.map((entry, i) => (
              <li key={`a-${i}`} className="text-emerald-700">
                D{entry.day} 解药救 {entry.target} 号
              </li>
            ))}
            {poisonHistory.map((entry, i) => (
              <li key={`p-${i}`} className="text-rose-700">
                D{entry.day} 毒药毒 {entry.target} 号
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function GuardBody({ state }: { state: RoleState }) {
  const lastTarget = state.last_target;
  const history = state.protect_history ?? [];

  return (
    <div className="space-y-2 text-sm">
      <div>
        <span className="text-xs text-muted-foreground">上夜守护: </span>
        <span className="font-medium">
          {lastTarget != null ? `${lastTarget} 号` : "未守护"}
        </span>
      </div>
      <div>
        <span className="text-xs text-muted-foreground">守护历史: </span>
        {history.length === 0 && <span className="text-xs text-muted-foreground">(暂无)</span>}
        {history.length > 0 && (
          <span className="text-xs">
            {history.map((entry, i) => (
              <span key={i}>
                {i > 0 && ", "}
                <span className="font-medium">D{entry.day}</span>
                {"→"}
                {entry.target != null ? `${entry.target} 号` : "未守护"}
              </span>
            ))}
          </span>
        )}
      </div>
    </div>
  );
}

function SeerBody({ state }: { state: RoleState }) {
  const checks = state.checks ?? {};
  const entries = Object.entries(checks);

  return (
    <div className="space-y-1 text-sm">
      <span className="text-xs text-muted-foreground">查验记录: </span>
      {entries.length === 0 && <span className="text-xs text-muted-foreground">(暂无)</span>}
      {entries.length > 0 && (
        <ul className="mt-1 space-y-0.5">
          {entries
            .sort(([, a], [, b]) => a.day - b.day)
            .map(([targetId, info]) => {
              const { text, className } = checkResultLabel(info.result);
              return (
                <li key={targetId} className="text-xs">
                  <span className="font-medium">{info.target} 号</span>
                  {" → "}
                  <span className={className}>{text}</span>
                  <span className="text-muted-foreground ml-1">(D{info.day})</span>
                </li>
              );
            })}
        </ul>
      )}
    </div>
  );
}

function HunterBody({ state }: { state: RoleState }) {
  const hasShot = state.has_shot === true;

  return (
    <div className="text-sm">
      <span className="text-xs text-muted-foreground">开枪状态: </span>
      {hasShot ? (
        <span className="text-rose-500 font-medium">
          已开枪{state.shot_target != null ? ` → ${state.shot_target} 号` : ""}
        </span>
      ) : (
        <span className="text-emerald-600">未开枪</span>
      )}
    </div>
  );
}

function WhiteWolfKingBody({ state }: { state: RoleState }) {
  const hasExploded = state.has_exploded === true;

  return (
    <div className="text-sm">
      <span className="text-xs text-muted-foreground">自爆状态: </span>
      {hasExploded ? (
        <span className="text-rose-500 font-medium">已自爆</span>
      ) : (
        <span className="text-emerald-600">未自爆</span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Role card renderer
// ---------------------------------------------------------------------------

function roleCardBody(role: string, state: RoleState) {
  switch (role) {
    case "witch":
      return <WitchBody state={state} />;
    case "guard":
      return <GuardBody state={state} />;
    case "seer":
      return <SeerBody state={state} />;
    case "hunter":
      return <HunterBody state={state} />;
    case "white_wolf_king":
      return <WhiteWolfKingBody state={state} />;
    default:
      return null;
  }
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function EngineStatePanel({ players }: { players: Player[] }) {
  const playersWithState = players.filter((p) => hasRoleState(p.role_state));

  if (playersWithState.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>引擎状态</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3 sm:grid-cols-2">
        {playersWithState.map((player) => {
          const icon = ROLE_ICONS[player.role] ?? "";
          const body = roleCardBody(player.role, player.role_state!);
          if (!body) return null;
          return (
            <div
              key={player.id}
              className={`rounded-md border border-border bg-muted/30 p-3 transition-colors ${
                !player.alive ? "opacity-50" : ""
              }`}
            >
              <div className="mb-2 flex items-center gap-1.5 text-sm font-semibold">
                <span>{icon}</span>
                <span>{roleName(player.role)}</span>
                <span className="text-muted-foreground font-normal">
                  (#{player.id})
                </span>
                {!player.alive && (
                  <span className="ml-auto text-xs text-muted-foreground">已出局</span>
                )}
              </div>
              {body}
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}
