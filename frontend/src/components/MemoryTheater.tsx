import React, { memo } from 'react';
import { MemoryGraph } from './MemoryGraph';
import { ActiveMemories } from './ActiveMemories';
import { Schemas } from './Schemas';
import { MemoryNode, ActiveMemory, Schema, GraphEvent } from '../types';
interface MemoryTheaterProps {
  nodes: MemoryNode[];
  activeMemories: ActiveMemory[];
  schemas: Schema[];
  budgetUsed: number;
  budgetTotal: number;
  graphEvent: GraphEvent;
}
export function MemoryTheater({
  nodes,
  activeMemories,
  schemas,
  budgetUsed,
  budgetTotal,
  graphEvent
}: MemoryTheaterProps) {
  return (
    <div className="flex flex-col h-full bg-zinc-950 p-5 gap-5">
      {/* Top Section: Memory Graph — the hero, takes the largest share */}
      <div className="flex-[3] min-h-0">
        <MemoryGraph nodes={nodes} graphEvent={graphEvent} />
      </div>

      {/* Bottom row: Active This Turn + Schemas SIDE BY SIDE */}
      <div className="flex-[2] min-h-0 flex gap-5">
        <div className="flex-1 min-w-0">
          <ActiveMemories
            memories={activeMemories}
            budgetUsed={budgetUsed}
            budgetTotal={budgetTotal} />
          
        </div>
        <div className="flex-1 min-w-0">
          <Schemas schemas={schemas} />
        </div>
      </div>
    </div>);

}