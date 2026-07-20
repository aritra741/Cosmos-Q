import React from 'react';
import { MemoryGraph } from './MemoryGraph';
import { ActiveMemories } from './ActiveMemories';
import { Schemas } from './Schemas';
import {
  MemoryNode,
  ActiveMemory,
  Schema,
  GraphEvent,
  LineageEntry,
} from '../types';

interface MemoryTheaterProps {
  nodes: MemoryNode[];
  activeMemories: ActiveMemory[];
  schemas: Schema[];
  budgetUsed: number;
  budgetTotal: number;
  graphEvent: GraphEvent;
  focusedNodeId?: string | null;
}

export function MemoryTheater({
  nodes,
  activeMemories,
  schemas,
  budgetUsed,
  budgetTotal,
  graphEvent,
  focusedNodeId,
}: MemoryTheaterProps) {
  const [selectedNodeId, setSelectedNodeId] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (focusedNodeId === undefined) return;
    setSelectedNodeId(focusedNodeId);
  }, [focusedNodeId]);

  const selectedNode = React.useMemo(
    () => nodes.find((node) => node.id === selectedNodeId) ?? null,
    [nodes, selectedNodeId]
  );

  const selectedLineage = React.useMemo(() => {
    if (!selectedNode) return [] as LineageEntry[];
    if (selectedNode.lineage && selectedNode.lineage.length > 0) {
      return selectedNode.lineage;
    }

    return [
      {
        id: selectedNode.id,
        status:
          selectedNode.status === 'ACTIVE' || selectedNode.status === 'SUPERSEDED'
            ? selectedNode.status
            : 'ACTIVE',
        contentSnippet: selectedNode.label,
        timestamp: 'Timestamp unavailable',
        trigger: 'Lineage metadata unavailable in this view.',
      },
    ];
  }, [selectedNode]);

  return (
    <div className="relative flex flex-col h-full bg-zinc-950 p-5 gap-5">
      <div className="flex-[3] min-h-0">
        <MemoryGraph
          nodes={nodes}
          graphEvent={graphEvent}
          selectedNodeId={selectedNodeId}
          onNodeSelect={(node) => setSelectedNodeId(node.id)}
        />
      </div>

      <div className="flex-[2] min-h-0 flex gap-5">
        <div className="flex-1 min-w-0">
          <ActiveMemories
            memories={activeMemories}
            budgetUsed={budgetUsed}
            budgetTotal={budgetTotal}
          />
        </div>
        <div className="flex-1 min-w-0">
          <Schemas schemas={schemas} />
        </div>
      </div>

      {selectedNode && selectedLineage.length > 0 ? (
        <div className="absolute top-5 right-5 bottom-5 w-[440px] z-40">
          <div className="h-full rounded-2xl border border-zinc-700/70 bg-zinc-950/92 backdrop-blur-xl shadow-[0_0_40px_rgba(0,0,0,0.55)] flex flex-col overflow-hidden">
            <div className="px-6 py-5 border-b border-zinc-800/80">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="text-[11px] font-mono font-bold text-emerald-500 tracking-[0.24em] uppercase">
                    Version Lineage
                  </div>
                  <div className="mt-2 text-[26px] leading-tight font-semibold text-zinc-100">
                    {selectedNode.label}
                  </div>
                  <div className="mt-2 text-sm leading-6 text-zinc-400">
                    Auditable reconsolidation trail across superseded and active versions.
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setSelectedNodeId(null)}
                  className="shrink-0 rounded-full border border-zinc-700 px-3 py-1.5 text-[11px] font-mono uppercase tracking-[0.2em] text-zinc-400 hover:text-zinc-200 hover:border-zinc-500 transition-colors"
                >
                  Close
                </button>
              </div>
            </div>
            <div className="flex-1 overflow-y-auto px-6 py-5">
              <div className="relative pl-8">
                <div className="absolute left-[11px] top-2 bottom-2 w-px bg-gradient-to-b from-emerald-500/40 via-zinc-700/80 to-zinc-800/10" />
                <div className="space-y-5">
                  {selectedLineage.map((entry, index) => (
                    <div
                      key={entry.id}
                      className="relative rounded-xl border border-zinc-800/80 bg-zinc-900/60 px-5 py-4 shadow-lg"
                    >
                      <div
                        className={`absolute -left-[23px] top-5 h-3 w-3 rounded-full border ${
                          entry.status === 'ACTIVE'
                            ? 'border-emerald-300 bg-emerald-400 shadow-[0_0_10px_rgba(52,211,153,0.7)]'
                            : 'border-amber-300 bg-amber-400 shadow-[0_0_10px_rgba(251,191,36,0.55)]'
                        }`}
                      />
                      <div className="flex items-center justify-between gap-4">
                        <span
                          className={`rounded-full px-3 py-1 text-[11px] font-mono font-bold uppercase tracking-[0.18em] ${
                            entry.status === 'ACTIVE'
                              ? 'bg-emerald-500/14 text-emerald-300 border border-emerald-500/30'
                              : 'bg-amber-500/12 text-amber-300 border border-amber-500/30'
                          }`}
                        >
                          {entry.status}
                        </span>
                        <span className="text-sm font-mono text-zinc-500">
                          {entry.timestamp}
                        </span>
                      </div>
                      <div className="mt-4 text-[20px] leading-7 font-medium text-zinc-100">
                        {entry.contentSnippet}
                      </div>
                      <div className="mt-3 text-sm leading-6 text-zinc-400">
                        {entry.trigger}
                      </div>
                      <div className="mt-4 text-[10px] font-mono uppercase tracking-[0.22em] text-zinc-600">
                        Version {index + 1}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
