export type MemoryStatus = 'ACTIVE' | 'SUPERSEDED' | 'CONSOLIDATED' | 'ARCHIVED';

export interface MemoryNode {
  id: string;
  label: string;
  status: MemoryStatus;
  stability: number; // 0 to 1 — drives node size / pulsing
  x: number; // percentage 0-100
  y: number; // percentage 0-100
  parentId?: string;
  isInterfering?: boolean;
  isNew?: boolean;
}

export interface ActiveMemory {
  id: string;
  label: string;
  utility: number;
  excluded?: boolean;
}

export interface Schema {
  id: string;
  type: 'PREFERENCE' | 'PROCEDURE' | 'FACT' | 'GOAL' | 'BEHAVIOR';
  summary: string;
  confidence: number;
}

export interface Message {
  id: string;
  role: 'user' | 'agent' | 'system';
  content: string;
  metadata?: string;
}

/**
 * A single choreographed turn of the demo. Each turn carries the user prompt,
 * the agent reply, an optional session-boundary divider shown BEFORE the turn,
 * and a full snapshot of the memory state that should be rendered once the
 * turn lands. Modeling each turn as a complete snapshot keeps the reducer
 * trivial — framer-motion handles the diff animations via stable node ids.
 */
export interface Turn {
  id: string;
  userMessage: string;
  /** Short label shown on the suggested-prompt chip for this turn. */
  chip: string;
  agentMessage: string;
  /** Session label to switch the chat header to when this turn lands. */
  sessionLabel: string;
  /**
   * Optional maintenance divider rendered in the chat before the user message.
   * `meta` lines are shown in the monospace maintenance log block.
   */
  divider?: {
    label: string;
    meta?: string;
  };
  /**
   * Node ids that should glow red (interference) for ~1.5s BEFORE the snapshot
   * is applied — this is the IAAF "forgetting" beat. Once the snapshot lands,
   * those nodes are expected to be ARCHIVED / removed.
   */
  interferenceNodeIds?: string[];
  /**
   * ASC consolidation beat: when the snapshot lands, animated dotted links
   * draw from these node ids up to a floating schema badge, then the nodes
   * settle into their CONSOLIDATED (blue) status. `consolidationLabel` is the
   * text shown on the badge the links converge into.
   */
  consolidationNodeIds?: string[];
  consolidationLabel?: string;
  /** Full memory state after this turn resolves. */
  nodes: MemoryNode[];
  activeMemories: ActiveMemory[];
  schemas: Schema[];
  budgetUsed: number;
}

/** Transient overlay event the MemoryGraph renders on top of the nodes. */
export type GraphEvent =
{kind: 'evict';nodeIds: string[];} |
{kind: 'consolidate';nodeIds: string[];label: string;} |
null;