import { useCallback, useEffect, useRef, useState } from "react";
import { getHumanAction, submitHumanAction, type HumanActionPending } from "../api";
import { Button } from "./ui/button";
import { speechLabel } from "./shared";

interface HumanActionPanelProps {
  gameId: string;
  gameStatus: string;
}

const TEXT_ACTIONS = new Set([
  "speak",
  "last_word",
  "sheriff_speak",
  "pk_speak",
]);

const OPTIONAL_TARGET_ACTIONS = new Set([
  "guard_protect",
  "sheriff_vote",
  "exile_vote",
  "pk_vote",
  "hunter_shoot",
]);

type SubmitPayload = {
  target?: number | null;
  choice?: string | null;
  text?: string;
};

export function HumanActionPanel({ gameId, gameStatus }: HumanActionPanelProps) {
  const [pending, setPending] = useState<HumanActionPending | null>(null);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const isRunning = gameStatus === "running";

  const poll = useCallback(async () => {
    try {
      const action = await getHumanAction(gameId);
      setPending(action);
      setError(null);
    } catch {
      setError("无法读取真人玩家操作");
    }
  }, [gameId]);

  useEffect(() => {
    if (!isRunning) {
      setPending(null);
      setError(null);
      return;
    }
    void poll();
    pollingRef.current = setInterval(poll, 500);
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, [isRunning, poll]);

  useEffect(() => {
    setText("");
  }, [pending?.action_type]);

  if (!pending) {
    if (!error) return null;
    return (
      <PanelWrapper label="真人玩家">
        <p className="text-sm text-destructive">{error}</p>
      </PanelWrapper>
    );
  }

  async function handleSubmit(payload: SubmitPayload = {}) {
    if (!pending) return;
    setSubmitting(true);
    setError(null);
    try {
      await submitHumanAction(gameId, {
        action_type: pending.action_type,
        target: payload.target ?? null,
        choice: payload.choice ?? null,
        text: payload.text ?? text,
      });
      setPending(null);
    } catch (err) {
      console.error("submit failed", err);
      setError(err instanceof Error ? err.message : "提交操作失败");
    } finally {
      setSubmitting(false);
    }
  }

  const { action_type, candidates, metadata } = pending;
  const label = speechLabel(action_type);

  if (action_type === "sheriff_run") {
    return (
      <PanelWrapper label={label} error={error}>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={() => handleSubmit({ choice: "run" })} disabled={submitting}>
            上警
          </Button>
          <Button size="sm" variant="ghost" onClick={() => handleSubmit({ choice: "pass" })} disabled={submitting}>
            不上警
          </Button>
        </div>
      </PanelWrapper>
    );
  }

  if (action_type === "sheriff_withdraw") {
    return (
      <PanelWrapper label={label} error={error}>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={() => handleSubmit({ choice: "stay" })} disabled={submitting}>
            继续竞选
          </Button>
          <Button size="sm" variant="ghost" onClick={() => handleSubmit({ choice: "withdraw" })} disabled={submitting}>
            退水
          </Button>
        </div>
      </PanelWrapper>
    );
  }

  if (action_type === "speech_order") {
    return (
      <PanelWrapper label={label} error={error}>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={() => handleSubmit({ choice: "forward" })} disabled={submitting}>
            顺序发言
          </Button>
          <Button size="sm" variant="secondary" onClick={() => handleSubmit({ choice: "reverse" })} disabled={submitting}>
            逆序发言
          </Button>
        </div>
      </PanelWrapper>
    );
  }

  if (action_type === "witch_act") {
    const canSave = metadata.can_save === true;
    const canPoison = metadata.can_poison === true;
    const attackedPlayer = metadataNumber(metadata, "attacked_player");
    return (
      <PanelWrapper label={label} error={error}>
        <div className="space-y-2 text-sm">
          {attackedPlayer != null && canSave && (
            <Button size="sm" onClick={() => handleSubmit({ target: attackedPlayer, choice: "save" })} disabled={submitting}>
              救 {attackedPlayer} 号
            </Button>
          )}
          {canPoison && candidates.length > 0 && (
            <div className="space-y-1">
              <p className="text-xs text-muted-foreground">毒杀目标：</p>
              <div className="flex flex-wrap gap-2">
                {candidates.map((c) => (
                  <Button key={c} size="sm" variant="secondary" onClick={() => handleSubmit({ target: c, choice: "poison" })} disabled={submitting}>
                    {c} 号
                  </Button>
                ))}
              </div>
            </div>
          )}
          <Button size="sm" variant="ghost" onClick={() => handleSubmit({ choice: "none" })} disabled={submitting}>
            不使用
          </Button>
        </div>
      </PanelWrapper>
    );
  }

  // White wolf explode: confirm or skip
  if (action_type === "white_wolf_explode") {
    return (
      <PanelWrapper label={label} error={error}>
        <div className="space-y-2">
          {candidates.length > 0 && (
            <div className="space-y-1">
              <p className="text-xs text-muted-foreground">选择自爆带走目标：</p>
              <div className="flex flex-wrap gap-2">
                {candidates.map((c) => (
                  <Button key={c} size="sm" variant="destructive" onClick={() => handleSubmit({ target: c, choice: "explode" })} disabled={submitting}>
                    {c} 号
                  </Button>
                ))}
              </div>
            </div>
          )}
          <Button size="sm" variant="ghost" onClick={() => handleSubmit({ choice: "pass" })} disabled={submitting}>
            不自爆
          </Button>
        </div>
      </PanelWrapper>
    );
  }

  // Text input actions (speak, last_word, sheriff_speak, pk_speak)
  if (TEXT_ACTIONS.has(action_type)) {
    return (
      <PanelWrapper label={label} error={error}>
        <div className="space-y-2">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="输入你的发言..."
            rows={3}
            className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring resize-none"
          />
          <Button size="sm" onClick={() => handleSubmit({ text })} disabled={submitting || !text.trim()}>
            提交发言
          </Button>
        </div>
      </PanelWrapper>
    );
  }

  // Sheriff badge transfer
  if (action_type === "sheriff_badge") {
    return (
      <PanelWrapper label="警徽移交" error={error}>
        <div className="space-y-1">
          <p className="text-xs text-muted-foreground">选择移交对象（或撕毁）：</p>
          <div className="flex flex-wrap gap-2">
            {candidates.map((c) => (
              <Button key={c} size="sm" onClick={() => handleSubmit({ target: c, choice: "transfer" })} disabled={submitting}>
                {c} 号
              </Button>
            ))}
            <Button size="sm" variant="destructive" onClick={() => handleSubmit({ choice: "destroy" })} disabled={submitting}>
              撕毁警徽
            </Button>
          </div>
        </div>
      </PanelWrapper>
    );
  }

  return (
    <PanelWrapper label={label} error={error}>
      <div className="space-y-1">
        {candidates.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {candidates.map((c) => (
              <Button key={c} size="sm" onClick={() => handleSubmit({ target: c })} disabled={submitting}>
                {c} 号
              </Button>
            ))}
            {OPTIONAL_TARGET_ACTIONS.has(action_type) && (
              <Button size="sm" variant="ghost" onClick={() => handleSubmit()} disabled={submitting}>
                {optionalTargetLabel(action_type)}
              </Button>
            )}
          </div>
        ) : OPTIONAL_TARGET_ACTIONS.has(action_type) ? (
          <Button size="sm" variant="ghost" onClick={() => handleSubmit()} disabled={submitting}>
            {optionalTargetLabel(action_type)}
          </Button>
        ) : (
          <p className="text-xs text-muted-foreground">暂无可选目标</p>
        )}
      </div>
    </PanelWrapper>
  );
}

function metadataNumber(metadata: Record<string, unknown>, key: string): number | null {
  const value = metadata[key];
  return typeof value === "number" ? value : null;
}

function optionalTargetLabel(actionType: string): string {
  if (actionType === "guard_protect") return "不守护";
  if (actionType === "hunter_shoot") return "不开枪";
  return "弃票";
}

function PanelWrapper({ label, error, children }: { label: string; error?: string | null; children: React.ReactNode }) {
  return (
    <div className="fixed bottom-4 left-1/2 z-50 -translate-x-1/2">
      <div className="rounded-lg border border-primary/50 bg-card px-5 py-4 shadow-lg ring-2 ring-primary/20 min-w-[280px]">
        <p className="mb-2 text-sm font-semibold text-primary">{label}</p>
        {children}
        {error && <p className="mt-2 text-xs text-destructive">{error}</p>}
      </div>
    </div>
  );
}
