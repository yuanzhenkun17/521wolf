import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { Badge } from "./ui/badge";
import { GoTGraph, type GoTData } from "./GoTGraph";

export function GoTDetails({ data }: { data: GoTData }) {
  const selectedHyp = data.hypotheses.find((h) => h.hypothesis_id === data.selected_hypothesis_id);
  const edgeCount = data.hypotheses.reduce(
    (sum, h) => sum + h.supporting_evidence.length + h.conflicting_evidence.length,
    0,
  );

  return (
    <Card className="border-indigo-200">
      <CardHeader className="bg-indigo-50">
        <CardTitle className="text-indigo-800">GoT 推理图</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 pt-4">
        {/* Graph */}
        <GoTGraph data={data} />

        {/* Quality summary */}
        <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
          <span>证据节点: <strong>{data.evidence_nodes.length}</strong></span>
          <span>假设节点: <strong>{data.hypotheses.length}</strong></span>
          <span>连接边数: <strong>{edgeCount}</strong></span>
        </div>

        {/* Hypotheses table */}
        {data.hypotheses.length > 0 && (
          <div>
            <h4 className="mb-2 text-xs font-medium text-foreground">假设列表</h4>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border text-left text-muted-foreground">
                    <th className="pb-1 pr-3 font-medium">ID</th>
                    <th className="pb-1 pr-3 font-medium">假设内容</th>
                    <th className="pb-1 pr-3 font-medium">置信度</th>
                    <th className="pb-1 font-medium">已选</th>
                  </tr>
                </thead>
                <tbody>
                  {data.hypotheses.map((hyp) => (
                    <tr
                      key={hyp.hypothesis_id}
                      className={hyp.hypothesis_id === data.selected_hypothesis_id ? "bg-amber-50" : ""}
                    >
                      <td className="py-1 pr-3 font-mono">{hyp.hypothesis_id}</td>
                      <td className="py-1 pr-3">{hyp.claim}</td>
                      <td className="py-1 pr-3">{((hyp.confidence ?? 0) * 100).toFixed(0)}%</td>
                      <td className="py-1">
                        {hyp.hypothesis_id === data.selected_hypothesis_id ? (
                          <Badge variant="default" className="bg-amber-500 text-white">已选</Badge>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Evidence summary */}
        {data.evidence_nodes.length > 0 && (
          <div>
            <h4 className="mb-2 text-xs font-medium text-foreground">证据列表</h4>
            <div className="space-y-1">
              {data.evidence_nodes.map((ev) => (
                <div key={ev.node_id} className="flex items-start gap-2 text-xs">
                  <Badge variant="outline" className="shrink-0 font-mono">{ev.node_id}</Badge>
                  <Badge variant="secondary" className="shrink-0">{ev.kind}</Badge>
                  <span className="text-muted-foreground">{ev.summary}</span>
                  {ev.reliability !== undefined && (
                    <span className="ml-auto shrink-0 text-muted-foreground">
                      {((ev.reliability) * 100).toFixed(0)}%
                    </span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Selected hypothesis detail */}
        {selectedHyp && (
          <div className="rounded-sm border border-amber-200 bg-amber-50 p-2 text-xs">
            <span className="font-medium text-amber-800">已选假设 {selectedHyp.hypothesis_id}：</span>
            <span className="text-amber-700">{selectedHyp.claim}</span>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
