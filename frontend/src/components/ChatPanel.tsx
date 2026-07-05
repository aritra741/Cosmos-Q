import React, { useEffect, useState, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Message } from '../types';
import { ArrowUpIcon, RotateCcwIcon, SparklesIcon, PowerIcon } from 'lucide-react';
import { cn } from '../lib/utils';
interface ChatPanelProps {
  messages: Message[];
  sessionLabel: string;
  nextChip?: string;
  isBusy: boolean;
  isComplete: boolean;
  mode?: 'demo' | 'live';
  error?: string | null;
  onSendMessage: (text: string) => void;
  onReplay?: () => void;
  onEndSession?: () => void;
}
export function ChatPanel({
  messages,
  sessionLabel,
  nextChip,
  isBusy,
  isComplete,
  mode = 'demo',
  error,
  onSendMessage,
  onReplay,
  onEndSession
}: ChatPanelProps) {
  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({
      behavior: 'smooth'
    });
  }, [messages]);
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (input.trim() && !isBusy && !isComplete) {
      onSendMessage(input.trim());
      setInput('');
    }
  };
  return (
    <div className="flex flex-col h-full bg-zinc-950 border-r border-zinc-800">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-zinc-800/60 bg-zinc-950/80 backdrop-blur-md z-10">
        <div className="flex items-center gap-3">
          <div className="w-2 h-2 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.8)] animate-pulse" />
          <h2 className="text-xs font-mono font-bold text-emerald-500 tracking-widest uppercase">
            {sessionLabel}
          </h2>
        </div>
        <span className="text-[10px] font-mono text-zinc-500 uppercase tracking-widest">
          SYS.TERMINAL // UACP
        </span>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-6 space-y-6 scrollbar-thin scrollbar-thumb-zinc-800">
        <AnimatePresence initial={false}>
          {messages.map((msg) =>
          <motion.div
            key={msg.id}
            initial={{
              opacity: 0,
              y: 8
            }}
            animate={{
              opacity: 1,
              y: 0
            }}
            transition={{
              duration: 0.3
            }}
            className={cn(
              'flex flex-col',
              msg.role === 'system' ? 'items-center my-8' : ''
            )}>
            
              {msg.role === 'system' ?
            <div className="w-full flex flex-col items-center gap-2">
                  <div className="flex items-center gap-4 w-full">
                    <div className="h-px bg-zinc-800/50 flex-1" />
                    <span className="text-[10px] font-mono font-bold text-zinc-500 uppercase tracking-widest whitespace-nowrap">
                      {msg.content}
                    </span>
                    <div className="h-px bg-zinc-800/50 flex-1" />
                  </div>
                  {msg.metadata &&
              <div className="text-[10px] text-amber-400/80 whitespace-pre-line text-center font-mono bg-amber-950/30 px-4 py-2 rounded border border-amber-500/20 shadow-[0_0_10px_rgba(245,158,11,0.1)]">
                      {msg.metadata}
                    </div>
              }
                </div> :

            <div
              className={cn(
                'max-w-[85%] rounded-xl px-4 py-3 text-sm leading-relaxed shadow-lg backdrop-blur-md border',
                msg.role === 'user' ?
                'bg-zinc-800/40 text-zinc-200 self-end border-zinc-700/50' :
                'bg-emerald-950/20 text-emerald-100 self-start border-emerald-500/20 shadow-[0_0_15px_rgba(16,185,129,0.05)]'
              )}>
              
                  <div
                className={cn(
                  'font-mono font-bold text-[9px] mb-1.5 uppercase tracking-widest',
                  msg.role === 'user' ?
                  'text-zinc-500' :
                  'text-emerald-500/70'
                )}>
                
                    {msg.role}
                  </div>
                  <div className="tracking-wide font-mono text-[13px]">
                    {msg.content}
                  </div>
                </div>
            }
            </motion.div>
          )}
        </AnimatePresence>

        {isBusy &&
        <div className="flex items-center gap-1.5 self-start text-zinc-500 pl-1">
            {[0, 1, 2].map((i) =>
          <motion.span
            key={i}
            className="w-1.5 h-1.5 rounded-full bg-zinc-600"
            animate={{
              opacity: [0.3, 1, 0.3]
            }}
            transition={{
              duration: 1,
              repeat: Infinity,
              delay: i * 0.2
            }} />

          )}
          </div>
        }
        <div ref={messagesEndRef} />
      </div>

      {/* Suggested prompt / composer */}
      <div className="p-4 bg-zinc-950 border-t border-zinc-800 space-y-3">
        {error &&
        <p className="text-xs font-mono text-amber-400/90 text-center">{error}</p>
        }
        {mode === 'demo' && isComplete ?
        <button
          onClick={onReplay}
          className="w-full flex items-center justify-center gap-2 bg-emerald-500/10 border border-emerald-500/40 text-emerald-300 rounded-full py-3 text-sm font-medium hover:bg-emerald-500/20 transition-colors">
          
            <RotateCcwIcon size={16} />
            Demo complete · Replay
          </button> :

        <>
            {mode === 'demo' && nextChip &&
          <button
            type="button"
            disabled={isBusy}
            onClick={() => onSendMessage(turnsPromptFromChip(nextChip))}
            className="group w-full flex items-center gap-2.5 text-left bg-zinc-900/60 border border-zinc-800 rounded-xl px-4 py-2.5 text-sm text-zinc-400 hover:border-emerald-500/40 hover:text-zinc-200 transition-colors disabled:opacity-40">
            
                <SparklesIcon
              size={14}
              className="text-emerald-500 shrink-0 group-hover:scale-110 transition-transform" />
            
                <span className="truncate">{nextChip}</span>
                <span className="ml-auto text-[10px] font-mono uppercase tracking-widest text-zinc-600">
                  Suggested
                </span>
              </button>
          }
            <form
            onSubmit={handleSubmit}
            className="relative flex items-center">
            
              <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={isBusy}
              aria-label="Type a message"
              placeholder={isBusy ? 'Processing turn…' : 'Type a message…'}
              className="w-full bg-zinc-900 border border-zinc-800 rounded-full pl-5 pr-12 py-3.5 text-[15px] text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500/50 transition-all disabled:opacity-50" />
            
              <button
              type="submit"
              disabled={!input.trim() || isBusy}
              aria-label="Send message"
              className="absolute right-2 p-2 text-zinc-950 bg-emerald-500 disabled:bg-zinc-800 disabled:text-zinc-600 transition-colors rounded-full">
              
                <ArrowUpIcon size={16} />
              </button>
            </form>
            {mode === 'live' && onEndSession &&
            <button
              type="button"
              disabled={isBusy}
              onClick={onEndSession}
              className="w-full flex items-center justify-center gap-2 text-zinc-500 hover:text-amber-400 text-xs font-mono uppercase tracking-widest transition-colors disabled:opacity-40">
              
                <PowerIcon size={12} />
                End session · Run maintenance
              </button>
            }
          </>
        }
      </div>
    </div>);

}
// The chip shows a short label; sending the fuller phrasing keeps the
// transcript readable, but any typed text advances the same scripted turn.
function turnsPromptFromChip(chip: string): string {
  return chip;
}