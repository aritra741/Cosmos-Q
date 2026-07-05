import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ChatPanel } from './components/ChatPanel';
import { MemoryTheater } from './components/MemoryTheater';
import {
  checkHealth,
  endSession,
  fetchState,
  fetchUser,
  sendChat,
  TheaterState,
} from './api/cosmos';
import { layoutMemories } from './layoutMemories';
import { ActiveMemory, GraphEvent, MemoryNode, Message, Schema } from './types';

const BUDGET_TOTAL = 2048;

function applyTheater(
  theater: TheaterState,
  positions: Map<string, { x: number; y: number }>
): {
  nodes: MemoryNode[];
  activeMemories: ActiveMemory[];
  schemas: Schema[];
  budgetUsed: number;
} {
  return {
    nodes: layoutMemories(theater.nodes, positions),
    activeMemories: theater.activeMemories,
    schemas: theater.schemas,
    budgetUsed: theater.budgetUsed,
  };
}

export function AppLive() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [nodes, setNodes] = useState<MemoryNode[]>([]);
  const [activeMemories, setActiveMemories] = useState<ActiveMemory[]>([]);
  const [schemas, setSchemas] = useState<Schema[]>([]);
  const [budgetUsed, setBudgetUsed] = useState(0);
  const [sessionLabel, setSessionLabel] = useState('Session 1');
  const [graphEvent, setGraphEvent] = useState<GraphEvent>(null);
  const [isBusy, setIsBusy] = useState(false);
  const [isReady, setIsReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const userId = useRef<string>('');
  const sessionId = useRef(`session-${Date.now()}`);
  const sessionNumber = useRef(1);
  const turnIndex = useRef(0);
  const positions = useRef(new Map<string, { x: number; y: number }>());
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);

  const schedule = useCallback((fn: () => void, ms: number) => {
    const t = setTimeout(fn, ms);
    timers.current.push(t);
  }, []);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      const healthy = await checkHealth();
      if (!healthy) {
        if (!cancelled) {
          setError('Backend unavailable. Start the API server: cosmos-q mcp-server');
        }
        return;
      }

      try {
        userId.current = await fetchUser();
        const theater = await fetchState(userId.current);
        if (cancelled) return;

        const applied = applyTheater(theater, positions.current);
        setNodes(applied.nodes);
        setActiveMemories(applied.activeMemories);
        setSchemas(applied.schemas);
        setBudgetUsed(applied.budgetUsed);
        setIsReady(true);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to connect');
        }
      }
    })();

    return () => {
      cancelled = true;
      timers.current.forEach(clearTimeout);
    };
  }, []);

  const handleSend = useCallback(
    async (text: string) => {
      if (isBusy || !isReady || !text.trim()) return;
      setIsBusy(true);
      setError(null);

      const userMsg: Message = {
        id: `user-${Date.now()}`,
        role: 'user',
        content: text.trim(),
      };
      setMessages((prev) => [...prev, userMsg]);

      try {
        const result = await sendChat(text.trim(), {
          userId: userId.current,
          sessionId: sessionId.current,
          turnIndex: turnIndex.current,
        });

        turnIndex.current += 1;

        const applied = applyTheater(result.theater, positions.current);
        setNodes(applied.nodes);
        setActiveMemories(applied.activeMemories);
        setSchemas(applied.schemas);
        setBudgetUsed(applied.budgetUsed);

        setMessages((prev) => [
          ...prev,
          {
            id: `agent-${Date.now()}`,
            role: 'agent',
            content: result.response,
          },
        ]);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Chat failed');
      } finally {
        setIsBusy(false);
      }
    },
    [isBusy, isReady]
  );

  const handleEndSession = useCallback(async () => {
    if (isBusy || !isReady) return;
    setIsBusy(true);
    setError(null);

    try {
      const result = await endSession(userId.current, sessionId.current);

      if (result.archived_ids.length > 0) {
        setNodes((prev) =>
          prev.map((n) =>
            result.archived_ids.includes(n.id)
              ? { ...n, isInterfering: true }
              : n
          )
        );
        setGraphEvent({ kind: 'evict', nodeIds: result.archived_ids });
      }

      const snapshotDelay = result.archived_ids.length > 0 ? 2600 : 400;

      schedule(() => {
        const applied = applyTheater(result.theater, positions.current);
        setNodes(applied.nodes);
        setActiveMemories(applied.activeMemories);
        setSchemas(applied.schemas);
        setBudgetUsed(applied.budgetUsed);
        if (result.archived_ids.length > 0) setGraphEvent(null);
      }, snapshotDelay);

      if (result.consolidated_ids.length > 0) {
        schedule(() => {
          setGraphEvent({
            kind: 'consolidate',
            nodeIds: result.consolidated_ids,
            label: result.consolidation_label,
          });
        }, snapshotDelay + 200);
        schedule(() => setGraphEvent(null), snapshotDelay + 3000);
      }

      schedule(() => {
        sessionNumber.current += 1;
        sessionId.current = `session-${Date.now()}`;
        turnIndex.current = 0;
        setSessionLabel(`Session ${sessionNumber.current}`);
        setMessages((prev) => [
          ...prev,
          {
            id: `sys-${Date.now()}`,
            role: 'system',
            content: 'Session ended · Maintenance running',
            metadata:
              result.archived_ids.length > 0
                ? `IAAF: ${result.archived_ids.length} memories archived`
                : 'IAAF: no memories archived',
          },
          {
            id: `sys-session-${Date.now()}`,
            role: 'system',
            content: `Session ${sessionNumber.current}`,
          },
        ]);
        setIsBusy(false);
      }, snapshotDelay + (result.consolidated_ids.length > 0 ? 600 : 250));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Session end failed');
      setIsBusy(false);
    }
  }, [isBusy, isReady, schedule]);

  if (error && !isReady) {
    return (
      <div className="flex w-full h-screen items-center justify-center bg-zinc-950 text-zinc-300 font-mono text-sm">
        <div className="max-w-md text-center space-y-3">
          <p className="text-amber-400">{error}</p>
          <p className="text-zinc-500 text-xs">
            Run <code className="text-emerald-500">cosmos-q mcp-server</code> from the
            project root, then refresh.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex w-full h-screen bg-zinc-950 text-zinc-200 overflow-hidden font-sans selection:bg-emerald-500/30">
      <div className="w-[44%] min-w-[400px] h-full">
        <ChatPanel
          messages={messages}
          sessionLabel={sessionLabel}
          isBusy={isBusy || !isReady}
          isComplete={false}
          mode="live"
          error={error}
          onSendMessage={handleSend}
          onEndSession={handleEndSession}
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
