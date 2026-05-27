import { useMemo } from "react";

/** Shapes matching the Python GoT data structures from agent/reasoning/got.py */
export interface GoTEvidenceNode {
  node_id: string;
  kind: string;
  summary: string;
  source?: string;
  reliability?: number;
}

export interface GoTHypothesis {
  hypothesis_id: string;
  claim: string;
  supporting_evidence: string[];
  conflicting_evidence: string[];
  expected_action?: Record<string, unknown>;
  confidence?: number;
}

export interface GoTData {
  evidence_nodes: GoTEvidenceNode[];
  hypotheses: GoTHypothesis[];
  selected_hypothesis_id?: string;
}

interface PositionedNode {
  id: string;
  x: number;
  y: number;
  label: string;
  fullText: string;
  kind: "evidence" | "hypothesis" | "observation";
  confidence?: number;
  reliability?: number;
  isSelected?: boolean;
}

interface Edge {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  relation: "supports" | "contradicts" | "refines";
  sourceId: string;
  targetId: string;
}

const COLORS = {
  evidence: { fill: "#3b82f6", stroke: "#2563eb", text: "#ffffff" },
  evidenceRelLow: { fill: "#93c5fd", stroke: "#60a5fa", text: "#1e3a5f" },
  hypothesis: { fill: "#22c55e", stroke: "#16a34a", text: "#ffffff" },
  hypothesisSelected: { fill: "#facc15", stroke: "#eab308", text: "#422006" },
  observation: { fill: "#9ca3af", stroke: "#6b7280", text: "#ffffff" },
};

const EDGE_STYLES: Record<string, { dash: string; color: string }> = {
  supports: { dash: "none", color: "#22c55e" },
  contradicts: { dash: "6,3", color: "#ef4444" },
  refines: { dash: "3,3", color: "#6366f1" },
};

function truncate(text: string, max: number): string {
  return text.length > max ? text.slice(0, max) + "..." : text;
}

/** Build a simple deterministic layout for GoT nodes. */
function layoutNodes(got: GoTData): { nodes: PositionedNode[]; edges: Edge[] } {
  const evidenceNodes: PositionedNode[] = [];
  const hypothesisNodes: PositionedNode[] = [];
  const observationNodes: PositionedNode[] = [];

  // Classify evidence by kind
  for (const ev of got.evidence_nodes) {
    const isObservation = ev.kind === "observation" || ev.kind === "belief";
    const collection = isObservation ? observationNodes : evidenceNodes;
    collection.push({
      id: ev.node_id,
      x: 0,
      y: 0,
      label: `${ev.node_id}: ${truncate(ev.summary, 20)}`,
      fullText: `[${ev.kind}] ${ev.summary}${ev.source ? ` (来源: ${ev.source})` : ""}  可靠度: ${((ev.reliability ?? 0.5) * 100).toFixed(0)}%`,
      kind: isObservation ? "observation" : "evidence",
      reliability: ev.reliability,
    });
  }

  for (const hyp of got.hypotheses) {
    hypothesisNodes.push({
      id: hyp.hypothesis_id,
      x: 0,
      y: 0,
      label: `${hyp.hypothesis_id}: ${truncate(hyp.claim, 20)}`,
      fullText: `${hyp.claim}  置信度: ${((hyp.confidence ?? 0) * 100).toFixed(0)}%`,
      kind: "hypothesis",
      confidence: hyp.confidence,
      isSelected: hyp.hypothesis_id === got.selected_hypothesis_id,
    });
  }

  // Layout: observations top, evidence left, hypotheses right
  const VIEW_W = 800;
  const VIEW_H = 420;
  const MARGIN_X = 70;
  const MARGIN_Y = 40;
  const COL_GAP = VIEW_W - 2 * MARGIN_X;

  // Observations along the top
  const obsCount = observationNodes.length;
  for (let i = 0; i < obsCount; i++) {
    observationNodes[i].x = MARGIN_X + (obsCount > 1 ? (COL_GAP * i) / (obsCount - 1) : COL_GAP / 2);
    observationNodes[i].y = MARGIN_Y;
  }

  // Evidence on the left
  const evCount = evidenceNodes.length;
  const evStartY = obsCount > 0 ? MARGIN_Y + 80 : MARGIN_Y;
  const evEndY = VIEW_H - MARGIN_Y;
  const evSpanY = evEndY - evStartY;
  for (let i = 0; i < evCount; i++) {
    evidenceNodes[i].x = MARGIN_X;
    evidenceNodes[i].y = evStartY + (evCount > 1 ? (evSpanY * i) / (evCount - 1) : evSpanY / 2);
  }

  // Hypotheses on the right
  const hypCount = hypothesisNodes.length;
  const hypStartY = obsCount > 0 ? MARGIN_Y + 80 : MARGIN_Y;
  const hypEndY = VIEW_H - MARGIN_Y;
  const hypSpanY = hypEndY - hypStartY;
  for (let i = 0; i < hypCount; i++) {
    hypothesisNodes[i].x = VIEW_W - MARGIN_X;
    hypothesisNodes[i].y = hypStartY + (hypCount > 1 ? (hypSpanY * i) / (hypCount - 1) : hypSpanY / 2);
  }

  const allNodes = [...observationNodes, ...evidenceNodes, ...hypothesisNodes];
  const nodeMap = new Map(allNodes.map((n) => [n.id, n]));

  // Build edges from hypothesis supporting/conflicting evidence lists
  const edges: Edge[] = [];
  for (const hyp of got.hypotheses) {
    const hypNode = nodeMap.get(hyp.hypothesis_id);
    if (!hypNode) continue;

    for (const evId of hyp.supporting_evidence) {
      const evNode = nodeMap.get(evId);
      if (!evNode) continue;
      edges.push({
        x1: evNode.x,
        y1: evNode.y,
        x2: hypNode.x,
        y2: hypNode.y,
        relation: "supports",
        sourceId: evId,
        targetId: hyp.hypothesis_id,
      });
    }
    for (const evId of hyp.conflicting_evidence) {
      const evNode = nodeMap.get(evId);
      if (!evNode) continue;
      edges.push({
        x1: evNode.x,
        y1: evNode.y,
        x2: hypNode.x,
        y2: hypNode.y,
        relation: "contradicts",
        sourceId: evId,
        targetId: hyp.hypothesis_id,
      });
    }
  }

  return { nodes: allNodes, edges };
}

/** Pure SVG GoT graph renderer -- no external deps. */
export function GoTGraph({ data }: { data: GoTData }) {
  const { nodes, edges } = useMemo(() => layoutNodes(data), [data]);

  const VIEW_W = 800;
  const VIEW_H = 420;
  const NODE_R = 28;
  const SEL_R = 34;

  return (
    <svg
      viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
      className="w-full rounded-md border border-border bg-white"
      style={{ maxHeight: 420 }}
    >
      <defs>
        <marker
          id="arrow-supports"
          viewBox="0 0 10 10"
          refX="10"
          refY="5"
          markerWidth="8"
          markerHeight="8"
          orient="auto-start-reverse"
        >
          <path d="M 0 0 L 10 5 L 0 10 z" fill={EDGE_STYLES.supports.color} />
        </marker>
        <marker
          id="arrow-contradicts"
          viewBox="0 0 10 10"
          refX="10"
          refY="5"
          markerWidth="8"
          markerHeight="8"
          orient="auto-start-reverse"
        >
          <path d="M 0 0 L 10 5 L 0 10 z" fill={EDGE_STYLES.contradicts.color} />
        </marker>
        <marker
          id="arrow-refines"
          viewBox="0 0 10 10"
          refX="10"
          refY="5"
          markerWidth="8"
          markerHeight="8"
          orient="auto-start-reverse"
        >
          <path d="M 0 0 L 10 5 L 0 10 z" fill={EDGE_STYLES.refines.color} />
        </marker>
        <filter id="glow-selected" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="4" result="blur" />
          <feFlood floodColor="#eab308" floodOpacity="0.5" result="color" />
          <feComposite in="color" in2="blur" operator="in" result="glow" />
          <feMerge>
            <feMergeNode in="glow" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {/* Edges */}
      {edges.map((edge, idx) => {
        const style = EDGE_STYLES[edge.relation];
        const dx = edge.x2 - edge.x1;
        const dy = edge.y2 - edge.y1;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const targetNode = nodes.find((n) => n.id === edge.targetId);
        const r = targetNode?.isSelected ? SEL_R : NODE_R;
        const sx = edge.x1 + (dx / dist) * NODE_R;
        const sy = edge.y1 + (dy / dist) * NODE_R;
        const ex = edge.x2 - (dx / dist) * r;
        const ey = edge.y2 - (dy / dist) * r;
        return (
          <line
            key={idx}
            x1={sx}
            y1={sy}
            x2={ex}
            y2={ey}
            stroke={style.color}
            strokeWidth={2}
            strokeDasharray={style.dash}
            markerEnd={`url(#arrow-${edge.relation})`}
            opacity={0.7}
          />
        );
      })}

      {/* Nodes */}
      {nodes.map((node) => {
        const isSelected = node.isSelected;
        const r = isSelected ? SEL_R : NODE_R;
        let colors;
        if (node.kind === "hypothesis") {
          colors = isSelected ? COLORS.hypothesisSelected : COLORS.hypothesis;
        } else if (node.kind === "observation") {
          colors = COLORS.observation;
        } else {
          colors = (node.reliability ?? 0.5) >= 0.5 ? COLORS.evidence : COLORS.evidenceRelLow;
        }
        return (
          <g key={node.id}>
            {isSelected && (
              <circle
                cx={node.x}
                cy={node.y}
                r={r + 4}
                fill="none"
                stroke={COLORS.hypothesisSelected.stroke}
                strokeWidth={2}
                opacity={0.4}
                filter="url(#glow-selected)"
              />
            )}
            <circle
              cx={node.x}
              cy={node.y}
              r={r}
              fill={colors.fill}
              stroke={colors.stroke}
              strokeWidth={isSelected ? 3 : 2}
              filter={isSelected ? "url(#glow-selected)" : undefined}
            />
            <title>{node.fullText}</title>
            <text
              x={node.x}
              y={node.y}
              textAnchor="middle"
              dominantBaseline="central"
              fill={colors.text}
              fontSize={10}
              fontWeight={isSelected ? 700 : 500}
              style={{ pointerEvents: "none" }}
            >
              {node.id}
            </text>
          </g>
        );
      })}

      {/* Legend */}
      <g transform={`translate(12, ${VIEW_H - 60})`} fontSize={10} fill="#6b7280">
        <circle cx={6} cy={6} r={5} fill={COLORS.evidence.fill} />
        <text x={16} y={10}>证据</text>
        <circle cx={56} cy={6} r={5} fill={COLORS.hypothesis.fill} />
        <text x={66} y={10}>假设</text>
        <circle cx={106} cy={6} r={5} fill={COLORS.hypothesisSelected.fill} />
        <text x={116} y={10}>已选假设</text>
        <circle cx={176} cy={6} r={5} fill={COLORS.observation.fill} />
        <text x={186} y={10}>观察/信念</text>
        <line x1={6} y1={24} x2={26} y2={24} stroke={EDGE_STYLES.supports.color} strokeWidth={2} />
        <text x={32} y={28}>支持</text>
        <line x1={66} y1={24} x2={86} y2={24} stroke={EDGE_STYLES.contradicts.color} strokeWidth={2} strokeDasharray="6,3" />
        <text x={92} y={28}>冲突</text>
        <line x1={126} y1={24} x2={146} y2={24} stroke={EDGE_STYLES.refines.color} strokeWidth={2} strokeDasharray="3,3" />
        <text x={152} y={28}>细化</text>
      </g>
    </svg>
  );
}
