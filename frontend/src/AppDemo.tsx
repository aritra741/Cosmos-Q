import React, { useCallback, useState, useRef } from 'react';
import { ChatPanel } from './components/ChatPanel';
import { MemoryTheater } from './components/MemoryTheater';
import {
  BUDGET_TOTAL,
  INITIAL_BUDGET,
  INITIAL_SESSION_LABEL,
  initialActiveMemories,
  initialMessages,
  initialNodes,
  initialSchemas,
  turns,
} from './demoScript';
import { ActiveMemory, GraphEvent, MemoryNode, Message, Schema } from './types';

export function AppDemo() {
  const [messages, setMessages] = useState<Message[]>(initialMessages);
  const [nodes, setNodes] = useState<MemoryNode[]>(initialNodes);
  const [activeMemories, setActiveMemories] = useState<ActiveMemory[]>(
    initialActiveMemories
  );
  const [schemas, setSchemas] = useState<Schema[]>(initialSchemas);
  const [budgetUsed, setBudgetUsed] = useState(INITIAL_BUDGET);
  const [sessionLabel, setSessionLabel] = useState(INITIAL_SESSION_LABEL);
  const [graphEvent, setGraphEvent] = useState<GraphEvent>(null);
  const [turnIndex, setTurnIndex] = useState(0);
  const [isBusy, setIsBusy] = useState(false);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const schedule = useCallback((fn: () => void, ms: number) => {
    const t = setTimeout(fn, ms);
    timers.current.push(t);
  }, []);
  const isComplete = turnIndex >= turns.length;
  const nextChip = !isComplete ? turns[turnIndex].chip : undefined;
  const advance = useCallback(
    (userText: string) => {
      if (isBusy || isComplete) return;
      const turn = turns[turnIndex];
      setIsBusy(true);
      const pending: Message[] = [];
      if (turn.divider) {
        pending.push({
          id: `${turn.id}-div`,
          role: 'system',
          content: turn.divider.label,
          metadata: turn.divider.meta,
        });
        pending.push({
          id: `${turn.id}-session`,
          role: 'system',
          content: turn.sessionLabel,
        });
      }
      pending.push({
        id: `${turn.id}-user`,
        role: 'user',
        content: userText || turn.userMessage,
      });
      setMessages((prev) => [...prev, ...pending]);
      if (turn.divider) setSessionLabel(turn.sessionLabel);
      const hasInterference =
        turn.interferenceNodeIds && turn.interferenceNodeIds.length > 0;
      if (hasInterference) {
        schedule(() => {
          setNodes((prev) =>
            prev.map((n) =>
              turn.interferenceNodeIds!.includes(n.id)
                ? { ...n, isInterfering: true }
                : n
            )
          );
          setGraphEvent({
            kind: 'evict',
            nodeIds: turn.interferenceNodeIds!,
          });
        }, 500);
      }
      const snapshotDelay = hasInterference ? 2600 : 900;
      schedule(() => {
        setNodes(turn.nodes);
        setActiveMemories(turn.activeMemories);
        setSchemas(turn.schemas);
        setBudgetUsed(turn.budgetUsed);
        setSessionLabel(turn.sessionLabel);
        if (hasInterference) setGraphEvent(null);
      }, snapshotDelay);
      const hasConsolidation =
        turn.consolidationNodeIds && turn.consolidationNodeIds.length > 0;
      if (hasConsolidation) {
        schedule(() => {
          setGraphEvent({
            kind: 'consolidate',
            nodeIds: turn.consolidationNodeIds!,
            label: turn.consolidationLabel ?? 'Schema',
          });
        }, snapshotDelay + 200);
        schedule(() => setGraphEvent(null), snapshotDelay + 3000);
      }
      const replyDelay = snapshotDelay + (hasConsolidation ? 600 : 250);
      schedule(() => {
        setMessages((prev) => [
          ...prev,
          {
            id: `${turn.id}-agent`,
            role: 'agent',
            content: turn.agentMessage,
          },
        ]);
        setTurnIndex((i) => i + 1);
        setIsBusy(false);
      }, replyDelay);
    },
    [isBusy, isComplete, schedule, turnIndex]
  );
  const handleReplay = useCallback(() => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
    setMessages(initialMessages);
    setNodes(initialNodes);
    setActiveMemories(initialActiveMemories);
    setSchemas(initialSchemas);
    setBudgetUsed(INITIAL_BUDGET);
    setSessionLabel(INITIAL_SESSION_LABEL);
    setGraphEvent(null);
    setTurnIndex(0);
    setIsBusy(false);
  }, []);
  return (
    <div className="flex w-full h-screen bg-zinc-950 text-zinc-200 overflow-hidden font-sans selection:bg-emerald-500/30">
      <div className="w-[44%] min-w-[400px] h-full">
        <ChatPanel
          messages={messages}
          sessionLabel={sessionLabel}
          nextChip={nextChip}
          isBusy={isBusy}
          isComplete={isComplete}
          mode="demo"
          onSendMessage={advance}
          onReplay={handleReplay}
        />
      </div>
      <div className="flex-1 h-full border-l border-zinc-800">
        <MemoryTheater
          nodes={nodes}
          activeMemories={activeMemories}
          schemas={schemas}
          budgetUsed={budgetUsed}
          budgetTotal={BUDGET_TOTAL}
          graphEvent={graphEvent}
        />
      </div>
    </div>
  );
}
