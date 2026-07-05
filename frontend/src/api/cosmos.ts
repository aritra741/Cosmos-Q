import {
  ActiveMemory,
  MemoryNode,
  Schema,
} from '../types';

const API_BASE = import.meta.env.VITE_API_URL ?? '';

export interface TheaterState {
  nodes: Array<Omit<MemoryNode, 'x' | 'y'>>;
  activeMemories: ActiveMemory[];
  schemas: Schema[];
  budgetUsed: number;
  budgetTotal: number;
}

export interface ChatResult {
  response: string;
  user_id: string;
  session_id: string;
  turn_index: number;
  theater: TheaterState;
}

export interface SessionEndResult {
  archived_ids: string[];
  consolidated_ids: string[];
  consolidation_label: string;
  theater: TheaterState;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = (body as { detail?: string }).detail ?? res.statusText;
    throw new Error(detail || `Request failed (${res.status})`);
  }
  return res.json() as Promise<T>;
}

export async function fetchUser(userId?: string): Promise<string> {
  const qs = userId ? `?user_id=${encodeURIComponent(userId)}` : '';
  const data = await request<{ user_id: string }>(`/api/user${qs}`);
  return data.user_id;
}

export async function fetchState(
  userId: string,
  query = ''
): Promise<TheaterState> {
  const params = new URLSearchParams({ user_id: userId });
  if (query) params.set('query', query);
  return request<TheaterState>(`/api/state?${params}`);
}

export async function sendChat(
  message: string,
  opts: { userId: string; sessionId: string; turnIndex: number }
): Promise<ChatResult> {
  return request<ChatResult>('/api/chat', {
    method: 'POST',
    body: JSON.stringify({
      message,
      user_id: opts.userId,
      session_id: opts.sessionId,
      turn_index: opts.turnIndex,
    }),
  });
}

export async function endSession(
  userId: string,
  sessionId: string
): Promise<SessionEndResult> {
  return request<SessionEndResult>('/api/session/end', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, session_id: sessionId }),
  });
}

export async function checkHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/health`);
    return res.ok;
  } catch {
    return false;
  }
}
