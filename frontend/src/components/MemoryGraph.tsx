import React, { useMemo, memo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { MemoryNode, GraphEvent } from '../types';
import { cn } from '../lib/utils';
interface MemoryGraphProps {
  nodes: MemoryNode[];
  graphEvent?: GraphEvent;
}
export function MemoryGraph({ nodes, graphEvent }: MemoryGraphProps) {
  // Calculate SVG lines for arrows
  const lines = useMemo(() => {
    return nodes.
    filter((n) => n.parentId).
    map((node) => {
      const parent = nodes.find((n) => n.id === node.parentId);
      if (!parent) return null;
      return {
        id: `${parent.id}-${node.id}`,
        x1: parent.x + 10,
        y1: parent.y + 5,
        x2: node.x - 2,
        y2: node.y + 5
      };
    }).
    filter(Boolean);
  }, [nodes]);
  // Consolidation overlay: dotted links converge from the consolidating nodes
  // up into a floating schema badge at their horizontal centroid.
  const consolidation = useMemo(() => {
    if (!graphEvent || graphEvent.kind !== 'consolidate') return null;
    const pts = graphEvent.nodeIds.
    map((id) => nodes.find((n) => n.id === id)).
    filter(Boolean) as MemoryNode[];
    if (pts.length === 0) return null;
    const cx = pts.reduce((s, n) => s + n.x, 0) / pts.length;
    const topY = Math.min(...pts.map((n) => n.y));
    const badgeY = Math.max(8, topY - 22);
    return {
      pts,
      cx,
      badgeY,
      label: graphEvent.label
    };
  }, [graphEvent, nodes]);
  return (
    <div className="relative w-full h-full bg-zinc-950 rounded-2xl border border-zinc-800/60 overflow-hidden shadow-[0_0_40px_rgba(0,0,0,0.5)]">
      {/* Background Grid & Glow */}
      <div className="absolute inset-0 bg-[linear-gradient(to_right,#3f3f4620_1px,transparent_1px),linear-gradient(to_bottom,#3f3f4620_1px,transparent_1px)] bg-[size:32px_32px]" />
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(16,185,129,0.08)_0%,transparent_80%)] pointer-events-none" />

      {/* Scanning Line Effect */}
      <motion.div
        className="absolute inset-0 w-full h-[2px] bg-emerald-500/20 shadow-[0_0_15px_rgba(16,185,129,0.5)] pointer-events-none"
        animate={{
          top: ['0%', '100%', '0%']
        }}
        transition={{
          duration: 10,
          ease: 'linear',
          repeat: Infinity
        }} />
      

      <div className="absolute top-5 left-5 text-[10px] font-mono text-emerald-500/70 tracking-widest uppercase z-10 drop-shadow-sm">
        Memory Graph // Live
      </div>

      {/* Status legend — makes the color encoding decodable */}
      <div className="absolute top-4 right-4 z-20 flex flex-col gap-1.5 rounded-lg border border-zinc-800/70 bg-zinc-950/70 px-3 py-2 backdrop-blur-sm">
        {[
        {
          label: 'Active',
          dot: 'bg-emerald-400 shadow-[0_0_6px_rgba(16,185,129,0.7)]'
        },
        {
          label: 'Superseded',
          dot: 'bg-zinc-600'
        },
        {
          label: 'Consolidated',
          dot: 'bg-blue-400 shadow-[0_0_6px_rgba(59,130,246,0.7)]'
        },
        {
          label: 'Archived',
          dot: 'bg-red-400 shadow-[0_0_6px_rgba(239,68,68,0.7)]'
        }].
        map((item) =>
        <div key={item.label} className="flex items-center gap-2">
            <span
            className={cn('h-1.5 w-1.5 rounded-full shrink-0', item.dot)} />
          
            <span className="text-[10px] font-mono uppercase tracking-wider text-zinc-500">
              {item.label}
            </span>
          </div>
        )}
      </div>

      {/* SVG Layer for Arrows */}
      <svg className="absolute inset-0 w-full h-full pointer-events-none z-0">
        <defs>
          <marker
            id="arrowhead"
            markerWidth="8"
            markerHeight="6"
            refX="7"
            refY="3"
            orient="auto">
            
            <polygon points="0 0, 8 3, 0 6" fill="#10b981" opacity="0.5" />
          </marker>
        </defs>
        <AnimatePresence>
          {lines.map((line: any) =>
          <motion.line
            key={line.id}
            initial={{
              pathLength: 0,
              opacity: 0
            }}
            animate={{
              pathLength: 1,
              opacity: 0.5
            }}
            transition={{
              duration: 0.8,
              ease: 'easeInOut',
              delay: 0.2
            }}
            x1={`${line.x1}%`}
            y1={`${line.y1}%`}
            x2={`${line.x2}%`}
            y2={`${line.y2}%`}
            stroke="#10b981"
            strokeWidth="1.5"
            strokeDasharray="4 4"
            markerEnd="url(#arrowhead)" />

          )}
        </AnimatePresence>

        {/* ASC consolidation: links converge into the schema badge */}
        <AnimatePresence>
          {consolidation &&
          consolidation.pts.map((n) =>
          <motion.line
            key={`consol-${n.id}`}
            initial={{
              pathLength: 0,
              opacity: 0
            }}
            animate={{
              pathLength: 1,
              opacity: 0.9
            }}
            exit={{
              opacity: 0
            }}
            transition={{
              duration: 0.6,
              ease: 'easeInOut'
            }}
            x1={`${n.x}%`}
            y1={`${n.y}%`}
            x2={`${consolidation.cx}%`}
            y2={`${consolidation.badgeY}%`}
            stroke="#3b82f6"
            strokeWidth="2"
            strokeDasharray="3 3" />

          )}
        </AnimatePresence>
      </svg>

      {/* Floating schema badge the consolidation links converge into */}
      <AnimatePresence>
        {consolidation &&
        <motion.div
          key="schema-badge"
          initial={{
            opacity: 0,
            scale: 0.6,
            y: 6
          }}
          animate={{
            opacity: 1,
            scale: 1,
            y: 0
          }}
          exit={{
            opacity: 0,
            scale: 0.8
          }}
          transition={{
            type: 'spring',
            stiffness: 220,
            damping: 18
          }}
          className="absolute z-30 -translate-x-1/2 -translate-y-1/2 flex items-center gap-2 rounded-md border border-blue-400/60 bg-blue-950/70 px-3 py-1.5 backdrop-blur-md shadow-[0_0_24px_rgba(59,130,246,0.45)]"
          style={{
            left: `${consolidation.cx}%`,
            top: `${consolidation.badgeY}%`
          }}>
          
            <motion.span
            className="h-1.5 w-1.5 rounded-full bg-blue-400"
            animate={{
              scale: [1, 1.6, 1],
              opacity: [1, 0.5, 1]
            }}
            transition={{
              duration: 1,
              repeat: Infinity
            }} />
          
            <span className="text-[11px] font-mono font-semibold tracking-wide text-blue-200 whitespace-nowrap">
              ◆ {consolidation.label}
            </span>
          </motion.div>
        }
      </AnimatePresence>

      {/* Nodes Layer */}
      <div className="absolute inset-0 z-10">
        <AnimatePresence>
          {nodes.map((node) => {
            const isGreen = node.status === 'ACTIVE';
            const isGrey = node.status === 'SUPERSEDED';
            const isBlue = node.status === 'CONSOLIDATED';
            const isRed = node.isInterfering;
            // Base size based on stability
            const scale = 0.85 + node.stability * 0.3;
            return (
              <motion.div
                key={node.id}
                initial={
                node.isNew ?
                {
                  opacity: 0,
                  scale: 0.5,
                  left: `${node.x + 10}%`,
                  top: `${node.y}%`
                } :
                {
                  opacity: 0,
                  scale: scale,
                  left: `${node.x}%`,
                  top: `${node.y}%`
                }
                }
                animate={{
                  opacity: node.status === 'ARCHIVED' ? 0.2 : 1,
                  scale: scale,
                  left: `${node.x}%`,
                  top: `${node.y}%`,
                  boxShadow: isRed ?
                  '0 0 30px 4px rgba(239, 68, 68, 0.6)' :
                  isGreen && node.stability > 0.7 ?
                  '0 0 20px 2px rgba(16, 185, 129, 0.15)' :
                  '0 0 0px 0px rgba(0,0,0,0)'
                }}
                exit={{
                  opacity: 0,
                  scale: 0.5
                }}
                transition={{
                  type: 'spring',
                  stiffness: 200,
                  damping: 20,
                  boxShadow: {
                    duration: 0.5
                  }
                }}
                className={cn(
                  'absolute -translate-x-1/2 -translate-y-1/2 px-4 py-2 rounded-md border backdrop-blur-md flex items-center justify-center min-w-[110px] transition-colors duration-500 shadow-lg',
                  isGreen &&
                  !isRed &&
                  'bg-emerald-950/40 border-emerald-500/50 text-emerald-400 shadow-[0_0_15px_rgba(16,185,129,0.15)]',
                  isGrey &&
                  !isRed &&
                  'bg-zinc-900/60 border-zinc-700/50 text-zinc-500',
                  isBlue &&
                  !isRed &&
                  'bg-blue-950/40 border-blue-500/50 text-blue-400 shadow-[0_0_15px_rgba(59,130,246,0.15)]',
                  isRed &&
                  'bg-red-950/40 border-red-500/50 text-red-400 shadow-[0_0_15px_rgba(239,68,68,0.15)]'
                )}>
                
                {/* Pulsing ring for active/stable memories */}
                {isGreen && node.stability > 0.7 &&
                <motion.div
                  className="absolute inset-0 rounded-md border border-emerald-400/30"
                  animate={{
                    scale: [1, 1.1, 1],
                    opacity: [0.5, 0, 0.5]
                  }}
                  transition={{
                    duration: 3,
                    repeat: Infinity,
                    ease: 'easeInOut'
                  }} />

                }

                {/* Consolidation flash ring */}
                {isBlue &&
                <motion.div
                  className="absolute inset-0 rounded-md border-2 border-blue-400/60"
                  animate={{
                    scale: [1, 1.25, 1],
                    opacity: [0.8, 0, 0.8]
                  }}
                  transition={{
                    duration: 1.6,
                    repeat: Infinity,
                    ease: 'easeInOut'
                  }} />

                }

                {/* IAAF eviction: hard red pulsing ring + floating ARCHIVING tag */}
                {isRed &&
                <>
                    <motion.div
                    className="absolute -inset-1 rounded-md border-2 border-red-500/70"
                    animate={{
                      scale: [1, 1.3, 1],
                      opacity: [0.9, 0.2, 0.9]
                    }}
                    transition={{
                      duration: 0.9,
                      repeat: Infinity,
                      ease: 'easeInOut'
                    }} />
                  
                    <motion.div
                    initial={{
                      opacity: 0,
                      y: 4
                    }}
                    animate={{
                      opacity: 1,
                      y: 0
                    }}
                    className="absolute -top-6 left-1/2 -translate-x-1/2 rounded bg-red-500/90 px-2 py-0.5 text-[9px] font-mono font-bold uppercase tracking-widest text-red-50 whitespace-nowrap shadow-[0_0_12px_rgba(239,68,68,0.7)]">
                    
                      ⊘ Archiving
                    </motion.div>
                  </>
                }

                <span
                  title={node.label}
                  className="text-xs font-mono font-medium whitespace-nowrap truncate max-w-[130px] tracking-wider">
                  
                  {node.label}
                </span>
              </motion.div>);

          })}
        </AnimatePresence>
      </div>
    </div>);

}