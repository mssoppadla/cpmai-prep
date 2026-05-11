"use client";
/**
 * AI chat state + API hook.
 *
 * Owns the conversation history, quota tracking, and the request
 * pipeline. The widget UI is purely presentational on top of this.
 *
 * Persistence: history is kept in localStorage so reloads don't lose
 * context for the user. Keyed by user_id so different users on the
 * same browser don't see each other's chats. Capped at the last 20
 * turns to keep request payloads small (sending 100 turns of history
 * makes the LLM call slow + expensive).
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { assistant, errMsg } from "@/lib/api";
import type {
  AssistantResponse, ChatMessage, ChatQuota,
} from "@/types/api";

const HISTORY_KEY = (userId: number) => `cpmai.chat.history.${userId}`;
const HISTORY_CAP = 20;

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
  /** Set on assistant turns only — server's response metadata. */
  response?: AssistantResponse;
  /** Client-side timestamp for ordering / display. */
  ts: number;
}

export interface AssistantState {
  turns: ChatTurn[];
  quota: ChatQuota | null;
  busy: boolean;
  error: string | null;
}

export function useAssistant(userId: number | null) {
  const [state, setState] = useState<AssistantState>({
    turns: [], quota: null, busy: false, error: null,
  });
  const hydrated = useRef(false);

  // Hydrate from localStorage on first render (or when userId changes).
  // Skipped if no userId — anon visitors get no persisted history.
  useEffect(() => {
    if (!userId) {
      setState((s) => ({ ...s, turns: [], error: null }));
      hydrated.current = true;
      return;
    }
    try {
      const raw = window.localStorage.getItem(HISTORY_KEY(userId));
      if (raw) {
        const turns = JSON.parse(raw) as ChatTurn[];
        if (Array.isArray(turns)) {
          setState((s) => ({ ...s, turns: turns.slice(-HISTORY_CAP) }));
        }
      }
    } catch {
      // Corrupted localStorage; ignore and start fresh.
    }
    hydrated.current = true;
  }, [userId]);

  // Persist on any turn change. Skip the first hydration tick so we
  // don't clobber stored history with an empty array.
  useEffect(() => {
    if (!hydrated.current || !userId) return;
    try {
      window.localStorage.setItem(
        HISTORY_KEY(userId), JSON.stringify(state.turns.slice(-HISTORY_CAP)));
    } catch {
      // Quota exceeded / private browsing — non-fatal.
    }
  }, [state.turns, userId]);

  const send = useCallback(async (message: string) => {
    const trimmed = message.trim();
    if (!trimmed) return;

    const userTurn: ChatTurn = {
      role: "user", content: trimmed, ts: Date.now(),
    };
    setState((s) => ({ ...s, turns: [...s.turns, userTurn],
                       busy: true, error: null }));

    // Send only the last N-1 turns of history (excluding the new one
    // we just added locally) — server expects history WITHOUT the
    // current message.
    const history: ChatMessage[] = state.turns
      .slice(-HISTORY_CAP + 1)
      .map((t) => ({
        role: t.role,
        content: t.content,
      }));

    try {
      const { response, quota } = await assistant.chat({
        message: trimmed, history,
      });
      const asstTurn: ChatTurn = {
        role: "assistant", content: response.message,
        response, ts: Date.now(),
      };
      setState((s) => ({
        ...s,
        turns: [...s.turns, asstTurn],
        quota, busy: false,
      }));
    } catch (e) {
      setState((s) => ({
        ...s,
        busy: false,
        error: errMsg(e),
      }));
    }
  }, [state.turns]);

  const clear = useCallback(() => {
    setState((s) => ({ ...s, turns: [], error: null }));
    if (userId) {
      try { window.localStorage.removeItem(HISTORY_KEY(userId)); } catch {}
    }
  }, [userId]);

  return { ...state, send, clear };
}
