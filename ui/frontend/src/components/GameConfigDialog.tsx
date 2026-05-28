import { useEffect, useState } from "react";
import { Loader2, Play, Settings, X } from "lucide-react";
import { listRoles, listRoleVersions, type GameConfig, type RoleVersion } from "../api";
import { Button } from "./ui/button";

interface GameConfigDialogProps {
  open: boolean;
  onClose: () => void;
  onSubmit: (config: GameConfig) => void;
  starting?: boolean;
}

const ROLE_LABELS: Record<string, string> = {
  werewolf: "狼人",
  seer: "预言家",
  witch: "女巫",
  guard: "守卫",
  hunter: "猎人",
  villager: "村民",
  white_wolf_king: "白狼王",
};

export function GameConfigDialog({ open, onClose, onSubmit, starting = false }: GameConfigDialogProps) {
  const [maxDays, setMaxDays] = useState(20);
  const [enableSheriff, setEnableSheriff] = useState(true);
  const [seed, setSeed] = useState("");

  // Per-role version selection: {role: {versions, selectedHash}}
  const [roles, setRoles] = useState<string[]>([]);
  const [roleVersions, setRoleVersions] = useState<Record<string, RoleVersion[]>>({});
  const [selectedHashes, setSelectedHashes] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!open) return;
    listRoles().then(async (r) => {
      setRoles(r);
      const allVersions: Record<string, RoleVersion[]> = {};
      const allHashes: Record<string, string> = {};
      for (const role of r) {
        try {
          const v = await listRoleVersions(role);
          allVersions[role] = v;
          const baseline = v.find((ver) => ver.is_baseline);
          allHashes[role] = baseline?.hash ?? v[0]?.hash ?? "";
        } catch {
          allVersions[role] = [];
          allHashes[role] = "";
        }
      }
      setRoleVersions(allVersions);
      setSelectedHashes(allHashes);
    }).catch(() => {});
  }, [open]);

  if (!open) return null;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const rv: Record<string, string> = {};
    for (const role of roles) {
      if (selectedHashes[role]) {
        rv[role] = selectedHashes[role];
      }
    }
    const config: GameConfig = {
      player_count: 12,
      max_days: maxDays,
      enable_sheriff: enableSheriff,
      role_versions: rv,
    };
    if (seed.trim()) config.seed = Number(seed);
    onSubmit(config);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />
      <div className="relative z-10 w-full max-w-lg rounded-lg border border-border bg-card shadow-lg">
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <div className="flex items-center gap-2">
            <Settings className="h-5 w-5 text-muted-foreground" />
            <h2 className="text-lg font-semibold">游戏配置</h2>
          </div>
          <button className="rounded-md p-1 hover:bg-muted" onClick={onClose}>
            <X className="h-5 w-5 text-muted-foreground" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5 p-5">
          {/* Per-role version selectors */}
          <div className="space-y-2">
            <label className="text-sm font-medium">各角色技能版本</label>
            <p className="text-xs text-muted-foreground">12人局，每个角色可独立选择技能版本</p>
            <div className="space-y-2 rounded-md border border-border p-3">
              {roles.map((role) => (
                <div key={role} className="flex items-center gap-3">
                  <span className="w-16 text-sm font-medium">{ROLE_LABELS[role] ?? role}</span>
                  <select
                    value={selectedHashes[role] ?? ""}
                    onChange={(e) => setSelectedHashes((prev) => ({ ...prev, [role]: e.target.value }))}
                    className="flex-1 rounded-md border border-border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  >
                    {(roleVersions[role] ?? []).map((v) => (
                      <option key={v.hash} value={v.hash}>
                        {v.hash}{v.is_baseline ? " (baseline)" : ""}
                      </option>
                    ))}
                  </select>
                </div>
              ))}
            </div>
          </div>

          {/* Max days */}
          <div className="space-y-2">
            <label className="text-sm font-medium" htmlFor="max-days">最大天数</label>
            <input
              id="max-days"
              type="number"
              min={1}
              max={100}
              value={maxDays}
              onChange={(e) => setMaxDays(Number(e.target.value))}
              className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>

          {/* Enable sheriff */}
          <div className="flex items-center gap-3">
            <input
              id="enable-sheriff"
              type="checkbox"
              checked={enableSheriff}
              onChange={(e) => setEnableSheriff(e.target.checked)}
              className="h-4 w-4 rounded border-border"
            />
            <label htmlFor="enable-sheriff" className="text-sm font-medium">启用警长模式</label>
          </div>

          {/* Seed */}
          <div className="space-y-2">
            <label className="text-sm font-medium" htmlFor="seed">
              随机种子
              <span className="ml-2 text-xs font-normal text-muted-foreground">（可选，留空则随机）</span>
            </label>
            <input
              id="seed"
              type="number"
              value={seed}
              onChange={(e) => setSeed(e.target.value)}
              placeholder="留空则随机生成"
              className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>

          {/* Actions */}
          <div className="flex justify-end gap-3 pt-2">
            <Button type="button" variant="secondary" onClick={onClose} disabled={starting}>取消</Button>
            <Button type="submit" disabled={starting}>
              {starting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              开始游戏
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
