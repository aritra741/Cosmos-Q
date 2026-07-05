import { MemoryNode } from './types';

type NodeInput = Omit<MemoryNode, 'x' | 'y'> & { x?: number; y?: number };

const COLS = 3;
const X_START = 14;
const X_STEP = 28;
const Y_START = 18;
const Y_STEP = 22;

/**
 * Assign canvas coordinates to memory nodes. Preserves positions for ids
 * already on screen so the graph doesn't jump on every update.
 */
export function layoutMemories(
  nodes: NodeInput[],
  existing: Map<string, { x: number; y: number }>
): MemoryNode[] {
  const positioned: MemoryNode[] = [];

  nodes.forEach((node, index) => {
    const saved = existing.get(node.id);
    const col = index % COLS;
    const row = Math.floor(index / COLS);
    const x = saved?.x ?? node.x ?? X_START + col * X_STEP;
    const y = saved?.y ?? node.y ?? Y_START + row * Y_STEP;

    existing.set(node.id, { x, y });
    positioned.push({ ...node, x, y });
  });

  return positioned;
}
