import { useState } from "react";
import { Loader2, Play, Settings, X } from "lucide-react";
import type { GameConfig } from "../api";
import { Button } from "./ui/button";

interface GameConfigDialogProps {
  open: boolean;
  onClose: () => void;
  onSubmit: (config: GameConfig) => void;
  starting?: boolean;
}

const PLAYER_COUNTS = [6, 8, 10, 12];

export function GameConfigDialog({ open, onClose, onSubmit, starting = false }: GameConfigDialogProps) {
  const [playerCount, setPlayerCount] = useState(12);
  const [maxDays, setMaxDays] = useState(20);
  const [enableSheriff, setEnableSheriff] = useState(true);
  const [skillDir, setSkillDir] = useState("");
  const [seed, setSeed] = useState("");

  if (!open) return null;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const config: GameConfig = {
      player_count: playerCount,
      max_days: maxDays,
      enable_sheriff: enableSheriff,
    };
    if (skillDir.trim()) config.skill_dir = skillDir.trim();
    if (seed.trim()) config.seed = Number(seed);
    onSubmit(config);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />

      {/* Dialog */}
      <div className="relative z-10 w-full max-w-md rounded-lg border border-border bg-card shadow-lg">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <div className="flex items-center gap-2">
            <Settings className="h-5 w-5 text-muted-foreground" />
            <h2 className="text-lg font-semibold">游戏配置</h2>
          </div>
          <button
            className="rounded-md p-1 hover:bg-muted"
            onClick={onClose}
          >
            <X className="h-5 w-5 text-muted-foreground" />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-5 p-5">
          {/* Player count */}
          <div className="space-y-2">
            <label className="text-sm font-medium">玩家人数</label>
            <div className="flex gap-2">
              {PLAYER_COUNTS.map((count) => (
                <button
                  key={count}
                  type="button"
                  className={
                    playerCount === count
                      ? "flex-1 rounded-md bg-primary py-2 text-sm font-medium text-primary-foreground"
                      : "flex-1 rounded-md border border-border bg-card py-2 text-sm hover:bg-muted"
                  }
                  onClick={() => setPlayerCount(count)}
                >
                  {count} 人
                </button>
              ))}
            </div>
          </div>

          {/* Max days */}
          <div className="space-y-2">
            <label className="text-sm font-medium" htmlFor="max-days">
              最大天数
            </label>
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
            <label htmlFor="enable-sheriff" className="text-sm font-medium">
              启用警长模式
            </label>
          </div>

          {/* Skill dir */}
          <div className="space-y-2">
            <label className="text-sm font-medium" htmlFor="skill-dir">
              Agent 技能目录
              <span className="ml-2 text-xs font-normal text-muted-foreground">（可选，默认使用内置技能）</span>
            </label>
            <input
              id="skill-dir"
              type="text"
              value={skillDir}
              onChange={(e) => setSkillDir(e.target.value)}
              placeholder="留空使用默认值"
              className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            />
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
            <Button type="button" variant="secondary" onClick={onClose} disabled={starting}>
              取消
            </Button>
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
