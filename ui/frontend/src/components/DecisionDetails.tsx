import { ChevronRight } from "lucide-react";
import { Badge } from "./ui/badge";
import { roleName } from "../presentation";
import { speechLabel, decisionChoiceText, decisionSourceName } from "./shared";
import type { AgentDecision, ArchiveMap } from "../types";

export function DecisionDetails({
  decisions,
  compact = false,
  archiveMap,
}: {
  decisions: AgentDecision[];
  compact?: boolean;
  archiveMap?: ArchiveMap;
}) {
  if (decisions.length === 0) return null;
  return (
    <details className={compact ? "group mt-2 text-xs" : "group mt-4 rounded-md border border-border bg-muted/30 p-3 text-sm"}>
      <summary className="flex cursor-pointer list-none items-center gap-1.5 font-medium text-muted-foreground marker:hidden">
        <ChevronRight className="h-3.5 w-3.5 transition-transform group-open:rotate-90" />
        决策过程
        {decisions.length > 1 ? <span className="text-xs font-normal">({decisions.length})</span> : null}
      </summary>
      <div className={compact ? "mt-2 space-y-2" : "mt-3 space-y-3"}>
        {decisions.map((decision) => (
          <DecisionBody key={decision.decision_id ?? decision.index} decision={decision} archiveEntry={archiveEntryForDecision(decision, archiveMap)} />
        ))}
      </div>
    </details>
  );
}

function archiveEntryForDecision(decision: AgentDecision, archiveMap?: ArchiveMap) {
  if (!archiveMap) return undefined;
  if (decision.decision_id) {
    const byId = archiveMap.get(decision.decision_id);
    if (byId) return byId;
  }
  return archiveMap.get(decision.index);
}

function DecisionBody({
  decision,
  archiveEntry,
}: {
  decision: AgentDecision;
  archiveEntry?: Record<string, unknown>;
}) {
  // Defensive defaults for fields that may be missing from API response
  const d = {
    ...decision,
    candidates: decision.candidates ?? [],
    alternatives: decision.alternatives ?? [],
    rejected_reasons: decision.rejected_reasons ?? [],
    memory_refs: decision.memory_refs ?? [],
    memory_summary: decision.memory_summary ?? [],
    errors: decision.errors ?? [],
    policy_adjustments: decision.policy_adjustments ?? [],
    raw_output: decision.raw_output ?? "",
    selected_skill: decision.selected_skill ?? (Array.isArray((decision as unknown as Record<string, unknown>)["selected_skills"]) ? ((decision as unknown as Record<string, unknown>)["selected_skills"] as string[])[0] : ""),
  };
  const ac = archiveEntry;
  const promptMessages = (ac?.prompt_messages as Array<Record<string, unknown>> | undefined) ?? [];
  const selectedSkills = (ac?.selected_skills as string[] | undefined) ?? [];
  const memoryContext = ac?.memory_context as Record<string, unknown> | undefined;
  const beliefContext = ac?.belief_context as Record<string, unknown> | undefined;
  return (
    <details className="group rounded-md border border-border bg-card p-3">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 marker:hidden">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline">{d.player_id ?? "-"} 号</Badge>
          <Badge variant="secondary">{roleName(d.role)}</Badge>
          <span className="text-xs text-muted-foreground">{speechLabel(d.action_type)}</span>
          <span className="text-xs text-muted-foreground">{decisionSourceName(d.source)}</span>
          {d.confidence > 0 ? (
            <span className="text-xs text-muted-foreground">置信度: {(d.confidence * 100).toFixed(0)}%</span>
          ) : null}
          {d.selected_skill ? (
            <Badge variant="secondary" className="text-xs">{d.selected_skill}</Badge>
          ) : null}
        </div>
        <ChevronRight className="h-3.5 w-3.5 shrink-0 transition-transform group-open:rotate-90" />
      </summary>
      <div className="mt-3 space-y-3">
        <p className="whitespace-pre-wrap text-sm leading-6">{d.private_reasoning}</p>
        <div className="grid gap-2 text-xs sm:grid-cols-2">
          <DecisionMeta label="选择" value={decisionChoiceText(d)} />
          <DecisionMeta label="候选" value={d.candidates.length > 0 ? d.candidates.join("、") : "-"} />
          <DecisionMeta label="备选" value={d.alternatives.length > 0 ? d.alternatives.join("、") : "-"} />
          <DecisionMeta label="置信度" value={d.confidence > 0 ? `${(d.confidence * 100).toFixed(0)}%` : "-"} />
          <DecisionMeta label="记忆事件" value={d.memory_summary.length > 0 ? d.memory_summary.slice(-2).join("；") : "-"} />
          <DecisionMeta label="记忆引用" value={d.memory_refs.length > 0 ? d.memory_refs.join("、") : "-"} />
        </div>
        {d.confidence > 0 ? (
          <div className="h-1.5 rounded-full bg-muted overflow-hidden">
            <div className={`h-full rounded-full ${d.confidence > 0.7 ? "bg-emerald-500" : d.confidence > 0.4 ? "bg-amber-500" : "bg-red-500"}`} style={{ width: `${d.confidence * 100}%` }}></div>
          </div>
        ) : null}
        {d.rejected_reasons.length > 0 ? (
          <div className="text-xs text-muted-foreground">排除理由：{d.rejected_reasons.join("；")}</div>
        ) : null}
        {d.policy_adjustments.length > 0 ? (
          <div className="rounded-sm border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800">
            <span className="font-medium">策略修正：</span>
            {d.policy_adjustments.join("；")}
          </div>
        ) : null}
        {d.errors.length > 0 ? (
          <div className="rounded-sm border border-red-200 bg-red-50 p-2 text-xs text-red-800">
            <span className="font-medium">错误：</span>
            {d.errors.join("；")}
          </div>
        ) : null}
        <DecisionExpandedSections
          decision={d}
          promptMessages={promptMessages}
          selectedSkills={selectedSkills}
          memoryContext={memoryContext}
          beliefContext={beliefContext}
        />
      </div>
    </details>
  );
}

function DecisionExpandedSections({
  decision,
  promptMessages,
  selectedSkills,
  memoryContext,
  beliefContext,
}: {
  decision: AgentDecision;
  promptMessages: Array<Record<string, unknown>>;
  selectedSkills: string[];
  memoryContext?: Record<string, unknown>;
  beliefContext?: Record<string, unknown>;
}) {
  const hasBelief = beliefContext && Object.keys(beliefContext).length > 0;
  const hasRaw = decision.raw_output.length > 0;
  const hasPrompt = promptMessages.length > 0;
  const hasMemory = memoryContext && Object.keys(memoryContext).length > 0;
  const hasSkill = selectedSkills.length > 0 && !decision.selected_skill;
  const hasAny = hasBelief || hasRaw || hasPrompt || hasMemory || hasSkill;
  if (!hasAny) return null;
  return (
    <div className="space-y-2">
      {hasSkill ? (
        <details className="group rounded-sm border border-border p-2">
          <summary className="flex cursor-pointer list-none items-center gap-1.5 text-xs font-medium text-muted-foreground marker:hidden">
            <ChevronRight className="h-3 w-3 transition-transform group-open:rotate-90" />
            注入 Skills
          </summary>
          <div className="mt-2 flex flex-wrap gap-1">
            {selectedSkills.map((sk) => (
              <Badge key={sk} variant="secondary" className="text-xs">{sk}</Badge>
            ))}
          </div>
        </details>
      ) : null}

      {hasMemory ? (
        <details className="group rounded-sm border border-border p-2">
          <summary className="flex cursor-pointer list-none items-center gap-1.5 text-xs font-medium text-muted-foreground marker:hidden">
            <ChevronRight className="h-3 w-3 transition-transform group-open:rotate-90" />
            记忆上下文
          </summary>
          <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-xs text-muted-foreground">
            {JSON.stringify(memoryContext, null, 2)}
          </pre>
        </details>
      ) : null}

      {hasBelief ? (
        <details className="group rounded-sm border border-border p-2">
          <summary className="flex cursor-pointer list-none items-center gap-1.5 text-xs font-medium text-muted-foreground marker:hidden">
            <ChevronRight className="h-3 w-3 transition-transform group-open:rotate-90" />
            Belief 快照
          </summary>
          <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-xs text-muted-foreground">
            {JSON.stringify(beliefContext, null, 2)}
          </pre>
        </details>
      ) : null}

      {hasPrompt ? (
        <PromptBlock title="Prompt" messages={promptMessages} />
      ) : null}

      {hasRaw ? (
        <RawBlock title="Raw Output" value={decision.raw_output} />
      ) : null}
    </div>
  );
}

function PromptBlock({ title, messages }: { title: string; messages: Array<Record<string, unknown>> }) {
  return (
    <details className="group rounded-sm border border-border p-2">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 text-xs font-medium text-muted-foreground marker:hidden">
        <ChevronRight className="h-3 w-3 transition-transform group-open:rotate-90" />
        {title} ({messages.length} 条)
      </summary>
      <div className="mt-2 space-y-2">
        {messages.map((msg, idx) => (
          <div key={idx} className="rounded-sm border border-border bg-card p-2 text-xs">
            <Badge variant="outline" className="mb-1">{(msg.role as string) ?? "unknown"}</Badge>
            <pre className="mt-1 overflow-x-auto whitespace-pre-wrap text-muted-foreground">
              {typeof msg.content === "string" ? msg.content.slice(0, 500) : JSON.stringify(msg.content, null, 2).slice(0, 500)}
              {(typeof msg.content === "string" ? msg.content.length > 500 : false) ? "...": ""}
            </pre>
          </div>
        ))}
      </div>
    </details>
  );
}

function RawBlock({ title, value }: { title: string; value: string }) {
  return (
    <details className="group rounded-sm border border-border p-2">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 text-xs font-medium text-muted-foreground marker:hidden">
        <ChevronRight className="h-3 w-3 transition-transform group-open:rotate-90" />
        {title}
      </summary>
      <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-xs text-muted-foreground">
        {value}
      </pre>
    </details>
  );
}

function DecisionMeta({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-sm bg-muted/40 px-2 py-1">
      <span className="font-medium">{label}：</span>
      <span className="break-words text-muted-foreground">{value}</span>
    </div>
  );
}
