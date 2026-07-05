import React, { memo } from 'react';
import { motion } from 'framer-motion';
import { ActiveMemory } from '../types';
import { Play } from 'lucide-react';
import { cn } from '../lib/utils';
interface ActiveMemoriesProps {
  memories: ActiveMemory[];
  budgetUsed: number;
  budgetTotal: number;
}
export function ActiveMemories({
  memories,
  budgetUsed,
  budgetTotal
}: ActiveMemoriesProps) {
  const budgetPercentage = Math.min(100, budgetUsed / budgetTotal * 100);
  return (
    <div className="flex flex-col h-full bg-zinc-950/80 rounded-2xl border border-zinc-800/80 p-5 shadow-xl min-h-0">
      <div className="text-[11px] font-bold text-zinc-500 tracking-widest uppercase mb-3 drop-shadow-sm shrink-0">
        Active This Turn
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto space-y-2 pr-2 scrollbar-thin scrollbar-thumb-zinc-800">
        {memories.map((memory, idx) =>
        <motion.div
          key={memory.id}
          initial={{
            opacity: 0,
            x: -10
          }}
          animate={{
            opacity: 1,
            x: 0
          }}
          transition={{
            delay: idx * 0.1
          }}
          className={cn(
            'flex items-center justify-between px-3 py-2 rounded-md text-xs transition-colors',
            memory.excluded ?
            'bg-zinc-900/30 text-zinc-600 border border-zinc-800/30' :
            'bg-gradient-to-r from-zinc-900/60 to-zinc-900/30 text-zinc-300 border border-zinc-700/40 shadow-sm'
          )}>
          
            <div className="flex items-center gap-2.5 overflow-hidden">
              <Play
              size={10}
              className={cn(
                'shrink-0',
                memory.excluded ?
                'text-zinc-700' :
                'text-emerald-500 drop-shadow-[0_0_5px_rgba(16,185,129,0.4)]'
              )}
              fill="currentColor" />
            
              <span className="truncate font-medium tracking-wide">
                {memory.label}
              </span>
            </div>
            <div
            className={cn(
              'font-mono text-[10px] ml-3 shrink-0',
              memory.excluded ? 'text-zinc-600' : 'text-emerald-400'
            )}>
            
              {memory.utility.toFixed(2)}
            </div>
          </motion.div>
        )}
      </div>

      <div className="mt-4 pt-4 border-t border-zinc-800/80 shrink-0">
        <div className="flex justify-between items-center mb-3">
          <span className="text-[11px] font-bold text-zinc-500 uppercase tracking-widest">
            Token Budget
          </span>
          <span className="text-xs font-mono font-medium text-zinc-300">
            {budgetUsed} <span className="text-zinc-600">/ {budgetTotal}</span>
          </span>
        </div>
        <div className="h-2 w-full bg-zinc-900/80 rounded-full overflow-hidden border border-zinc-800/50 shadow-inner relative">
          <motion.div
            className="absolute top-0 left-0 h-full bg-gradient-to-r from-emerald-600 to-emerald-400 rounded-full shadow-[0_0_10px_rgba(52,211,153,0.5)]"
            initial={{
              width: 0
            }}
            animate={{
              width: `${budgetPercentage}%`
            }}
            transition={{
              duration: 1,
              ease: 'easeOut'
            }} />
          
        </div>
      </div>
    </div>);

}