import React from 'react';
import { motion } from 'framer-motion';
import { Schema } from '../types';
import { cn } from '../lib/utils';
interface SchemasProps {
  schemas: Schema[];
}
export function Schemas({ schemas }: SchemasProps) {
  return (
    <div className="flex flex-col h-full bg-zinc-950/80 rounded-2xl border border-zinc-800/80 p-5 shadow-xl min-h-0">
      <div className="text-[11px] font-bold text-zinc-500 tracking-widest uppercase mb-3 drop-shadow-sm shrink-0">
        Schemas
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto space-y-2 pr-2 scrollbar-thin scrollbar-thumb-zinc-800">
        {schemas.map((schema, idx) => {
          let dotColor = 'bg-red-500';
          if (schema.confidence > 0.8) dotColor = 'bg-emerald-500';else
          if (schema.confidence >= 0.5) dotColor = 'bg-amber-500';
          return (
            <motion.div
              key={schema.id}
              initial={{
                opacity: 0,
                y: 10
              }}
              animate={{
                opacity: 1,
                y: 0
              }}
              transition={{
                delay: idx * 0.15
              }}
              className="flex items-center justify-between px-3.5 py-2 rounded-lg bg-gradient-to-r from-zinc-900/60 to-zinc-900/30 border border-zinc-700/40 hover:border-zinc-600 transition-colors shadow-sm">
              
              <div className="flex flex-col gap-0.5 overflow-hidden pr-4">
                <span className="text-[9px] font-bold text-zinc-500 tracking-widest uppercase">
                  {schema.type}
                </span>
                <span className="text-[13px] font-medium text-zinc-200 truncate tracking-wide">
                  {schema.summary}
                </span>
              </div>
              <div className="flex items-center gap-2.5 shrink-0">
                <span className="text-[11px] font-mono text-zinc-400">
                  {schema.confidence.toFixed(2)}
                </span>
                <div
                  className={cn(
                    'w-2 h-2 rounded-full',
                    dotColor,
                    schema.confidence > 0.8 ?
                    'shadow-[0_0_8px_rgba(16,185,129,0.6)]' :
                    schema.confidence >= 0.5 ?
                    'shadow-[0_0_8px_rgba(245,158,11,0.6)]' :
                    'shadow-[0_0_8px_rgba(239,68,68,0.6)]'
                  )} />
                
              </div>
            </motion.div>);

        })}
      </div>
    </div>);

}