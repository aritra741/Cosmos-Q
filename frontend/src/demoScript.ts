import { MemoryNode, ActiveMemory, Schema, Message, Turn } from './types';

export const BUDGET_TOTAL = 2048;

/* ------------------------------------------------------------------ */
/* Stable node coordinates (percentages). Centers are kept within a    */
/* safe inset (x: 12-66, y: 18-82) so each node's full bounding box     */
/* stays inside the canvas — nothing overflows the right edge.          */
/*                                                                      */
/* Layout reads as three lanes:                                         */
/*   • testing lineage  (top)    pytest v1 → Ward v1 → pytest v2        */
/*   • api lane         (middle) FastAPI → Payments API                 */
/*   • deploy lane      (bottom) ECS + Docker → Deploy Config v2        */
/* ------------------------------------------------------------------ */
const POS = {
  pytestV1: { x: 12, y: 18 },
  wardV1: { x: 38, y: 18 },
  pytestV2: { x: 64, y: 18 },
  fastapi: { x: 18, y: 50 },
  paymentsApi: { x: 55, y: 50 },
  ecs: { x: 26, y: 82 },
  deployV2: { x: 64, y: 82 }
};

/* ------------------------------------------------------------------ */
/* Initial state — what is on screen when the demo opens (Session 4).  */
/* pytest v1 was superseded by Ward v1 in an earlier session.          */
/* ------------------------------------------------------------------ */
export const initialMessages: Message[] = [
{
  id: 'sys-1',
  role: 'system',
  content: 'Session 3 ended · Maintenance running',
  metadata: 'IAAF: 2 memories archived\nASC: 1 schema updated'
},
{ id: 'sys-2', role: 'system', content: 'Session 4' },
{
  id: 'msg-1',
  role: 'user',
  content: 'Help me set up tests for the payments module'
},
{
  id: 'msg-2',
  role: 'agent',
  content:
  "Here's your Ward test suite for payments — wired up against your FastAPI app and ready to run in the ECS + Docker pipeline you use."
}];


export const initialNodes: MemoryNode[] = [
{
  id: 'node-pytest-v1',
  label: 'pytest v1',
  status: 'SUPERSEDED',
  stability: 0.45,
  ...POS.pytestV1
},
{
  id: 'node-ward-v1',
  label: 'Ward v1',
  status: 'ACTIVE',
  stability: 0.62,
  ...POS.wardV1,
  parentId: 'node-pytest-v1'
},
{
  id: 'node-fastapi',
  label: 'FastAPI',
  status: 'ACTIVE',
  stability: 0.78,
  ...POS.fastapi
},
{
  id: 'node-ecs',
  label: 'ECS + Docker',
  status: 'ACTIVE',
  stability: 0.8,
  ...POS.ecs
}];


export const initialActiveMemories: ActiveMemory[] = [
{ id: 'am-ward', label: 'Ward preference', utility: 0.91 },
{ id: 'am-ecs', label: 'ECS deployment', utility: 0.87 },
{ id: 'am-fastapi', label: 'FastAPI structure', utility: 0.73 },
{
  id: 'am-jenkins',
  label: 'Legacy Jenkins config',
  utility: 0.21,
  excluded: true
}];


export const initialSchemas: Schema[] = [
{
  id: 'sch-testing',
  type: 'PREFERENCE',
  summary: 'Testing → Ward',
  confidence: 0.85
},
{
  id: 'sch-deploy',
  type: 'PROCEDURE',
  summary: 'Deploy → ECS',
  confidence: 0.92
},
{ id: 'sch-db', type: 'FACT', summary: 'DB → DynamoDB', confidence: 0.78 }];


export const INITIAL_BUDGET = 1847;
export const INITIAL_SESSION_LABEL = 'Session 4';

/* ------------------------------------------------------------------ */
/* The choreographed timeline.                                          */
/*                                                                      */
/* CAUSAL RULE: memory MUTATES only on INSTRUCTIONS (something new      */
/* makes a memory obsolete). A QUESTION is a pure READ — it retrieves   */
/* memories for the answer (updates "Active This Turn" + budget) but    */
/* never archives, supersedes, or consolidates anything.                */
/* ------------------------------------------------------------------ */
export const turns: Turn[] = [
/* ---- Turn 1 · INSTRUCTION: add a feature → reinforce + store (no eviction) ---- */
{
  id: 'turn-1',
  chip: 'Add a Stripe webhook route to the API',
  userMessage:
  'Add a webhook route to the API for processing Stripe payments.',
  agentMessage:
  'Scaffolded the webhook route on your FastAPI app. That reinforced the FastAPI memory, and I stored a new Payments API memory for it.',
  sessionLabel: 'Session 4',
  nodes: [
  {
    id: 'node-pytest-v1',
    label: 'pytest v1',
    status: 'SUPERSEDED',
    stability: 0.45,
    ...POS.pytestV1
  },
  {
    id: 'node-ward-v1',
    label: 'Ward v1',
    status: 'ACTIVE',
    stability: 0.62,
    ...POS.wardV1,
    parentId: 'node-pytest-v1'
  },
  // FastAPI reinforced — grows + pulses
  {
    id: 'node-fastapi',
    label: 'FastAPI',
    status: 'ACTIVE',
    stability: 0.95,
    ...POS.fastapi
  },
  {
    id: 'node-ecs',
    label: 'ECS + Docker',
    status: 'ACTIVE',
    stability: 0.8,
    ...POS.ecs
  },
  // new memory stored
  {
    id: 'node-payments-api',
    label: 'Payments API',
    status: 'ACTIVE',
    stability: 0.45,
    ...POS.paymentsApi,
    parentId: 'node-fastapi',
    isNew: true
  }],

  activeMemories: [
  { id: 'am-fastapi', label: 'FastAPI structure', utility: 0.96 },
  { id: 'am-payments', label: 'Payments API', utility: 0.82 },
  { id: 'am-ward', label: 'Ward preference', utility: 0.61 },
  {
    id: 'am-jenkins',
    label: 'Legacy Jenkins config',
    utility: 0.19,
    excluded: true
  }],

  schemas: [
  {
    id: 'sch-testing',
    type: 'PREFERENCE',
    summary: 'Testing → Ward',
    confidence: 0.85
  },
  {
    id: 'sch-deploy',
    type: 'PROCEDURE',
    summary: 'Deploy → ECS',
    confidence: 0.92
  },
  {
    id: 'sch-db',
    type: 'FACT',
    summary: 'DB → DynamoDB',
    confidence: 0.78
  }],

  budgetUsed: 1720
},

/* ---- Turn 2 · INSTRUCTION: retire Ward → RTR (supersede) + IAAF (archive obsolete) ---- */
{
  id: 'turn-2',
  chip: 'Standardize all tests on pytest, drop Ward',
  userMessage:
  "We're standardizing every test suite on pytest with fixtures — drop Ward entirely.",
  agentMessage:
  'Migrating the suites to pytest. Ward is now superseded by pytest v2, and the obsolete pytest v1 memory was archived since it’s no longer reachable.',
  sessionLabel: 'Session 4',
  // pytest v1 is made unusable by this instruction → red glow, then archived
  interferenceNodeIds: ['node-pytest-v1'],
  nodes: [
  // pytest v1 archived out (removed from snapshot → exits)
  // Ward v1 superseded by the new pytest v2 (RTR)
  {
    id: 'node-ward-v1',
    label: 'Ward v1',
    status: 'SUPERSEDED',
    stability: 0.5,
    ...POS.wardV1
  },
  {
    id: 'node-pytest-v2',
    label: 'pytest v2',
    status: 'ACTIVE',
    stability: 0.5,
    ...POS.pytestV2,
    parentId: 'node-ward-v1',
    isNew: true
  },
  {
    id: 'node-fastapi',
    label: 'FastAPI',
    status: 'ACTIVE',
    stability: 0.95,
    ...POS.fastapi
  },
  {
    id: 'node-ecs',
    label: 'ECS + Docker',
    status: 'ACTIVE',
    stability: 0.8,
    ...POS.ecs
  },
  {
    id: 'node-payments-api',
    label: 'Payments API',
    status: 'ACTIVE',
    stability: 0.58,
    ...POS.paymentsApi,
    parentId: 'node-fastapi'
  }],

  activeMemories: [
  { id: 'am-pytest', label: 'pytest preference', utility: 0.94 },
  { id: 'am-fastapi', label: 'FastAPI structure', utility: 0.8 },
  { id: 'am-payments', label: 'Payments API', utility: 0.72 },
  {
    id: 'am-ward',
    label: 'Ward preference (retired)',
    utility: 0.24,
    excluded: true
  }],

  schemas: [
  // instruction rewrites the testing schema
  {
    id: 'sch-testing',
    type: 'PREFERENCE',
    summary: 'Testing → pytest',
    confidence: 0.8
  },
  {
    id: 'sch-deploy',
    type: 'PROCEDURE',
    summary: 'Deploy → ECS',
    confidence: 0.92
  },
  {
    id: 'sch-db',
    type: 'FACT',
    summary: 'DB → DynamoDB',
    confidence: 0.78
  }],

  budgetUsed: 1805
},

/* ---- Turn 3 · INSTRUCTION: migrate deploys → RTR + ASC consolidation ---- */
{
  id: 'turn-3',
  chip: 'Migrate deploys to the new ECS task def',
  userMessage:
  'Migrate the service to the new containerized ECS task definition and retire the old pipeline.',
  agentMessage:
  'Cut over to the new task definition. ECS + Docker is superseded by Deploy Config v2, and I consolidated your FastAPI + Payments API memories into a reusable "FastAPI Services" schema.',
  sessionLabel: 'Session 4',
  // ASC: these two nodes converge into a new schema badge, then turn blue
  consolidationNodeIds: ['node-fastapi', 'node-payments-api'],
  consolidationLabel: 'FastAPI Services',
  nodes: [
  {
    id: 'node-ward-v1',
    label: 'Ward v1',
    status: 'SUPERSEDED',
    stability: 0.45,
    ...POS.wardV1
  },
  {
    id: 'node-pytest-v2',
    label: 'pytest v2',
    status: 'ACTIVE',
    stability: 0.66,
    ...POS.pytestV2,
    parentId: 'node-ward-v1'
  },
  // FastAPI + Payments API consolidated into a schema (blue)
  {
    id: 'node-fastapi',
    label: 'FastAPI',
    status: 'CONSOLIDATED',
    stability: 0.96,
    ...POS.fastapi
  },
  {
    id: 'node-payments-api',
    label: 'Payments API',
    status: 'CONSOLIDATED',
    stability: 0.7,
    ...POS.paymentsApi,
    parentId: 'node-fastapi'
  },
  // ECS superseded by Deploy Config v2 (RTR)
  {
    id: 'node-ecs',
    label: 'ECS + Docker',
    status: 'SUPERSEDED',
    stability: 0.7,
    ...POS.ecs
  },
  {
    id: 'node-deploy-v2',
    label: 'Deploy Config v2',
    status: 'ACTIVE',
    stability: 0.6,
    ...POS.deployV2,
    parentId: 'node-ecs',
    isNew: true
  }],

  activeMemories: [
  { id: 'am-deploy-v2', label: 'Deploy Config v2', utility: 0.95 },
  { id: 'am-fastapi', label: 'FastAPI structure', utility: 0.84 },
  { id: 'am-payments', label: 'Payments API', utility: 0.79 },
  { id: 'am-pytest', label: 'pytest preference', utility: 0.6 },
  {
    id: 'am-ecs',
    label: 'Legacy ECS config (retired)',
    utility: 0.22,
    excluded: true
  }],

  schemas: [
  {
    id: 'sch-testing',
    type: 'PREFERENCE',
    summary: 'Testing → pytest',
    confidence: 0.83
  },
  {
    id: 'sch-deploy',
    type: 'PROCEDURE',
    summary: 'Deploy → ECS v2',
    confidence: 0.9
  },
  // new schema created by ASC consolidation
  {
    id: 'sch-stack',
    type: 'FACT',
    summary: 'Stack → FastAPI Services',
    confidence: 0.95
  },
  {
    id: 'sch-db',
    type: 'FACT',
    summary: 'DB → DynamoDB',
    confidence: 0.78
  }],

  budgetUsed: 1910
},

/* ---- Turn 4 · QUESTION (pure read): retrieves memories, mutates NOTHING ---- */
{
  id: 'turn-4',
  chip: 'What testing & deploy setup are we on now?',
  userMessage:
  'Just to confirm — what testing and deployment setup are we on right now?',
  agentMessage:
  'You’re on pytest v2 for tests and Deploy Config v2 (containerized ECS) for deploys, against your consolidated FastAPI Services stack. (Read-only — nothing changed in memory.)',
  sessionLabel: 'Session 5',
  divider: {
    label: 'Session 4 ended · Session 5',
    meta: 'Read-only query · no memory mutation'
  },
  // IDENTICAL graph + schemas to Turn 3 → the question changes nothing visible.
  nodes: [
  {
    id: 'node-ward-v1',
    label: 'Ward v1',
    status: 'SUPERSEDED',
    stability: 0.45,
    ...POS.wardV1
  },
  {
    id: 'node-pytest-v2',
    label: 'pytest v2',
    status: 'ACTIVE',
    stability: 0.66,
    ...POS.pytestV2,
    parentId: 'node-ward-v1'
  },
  {
    id: 'node-fastapi',
    label: 'FastAPI',
    status: 'CONSOLIDATED',
    stability: 0.96,
    ...POS.fastapi
  },
  {
    id: 'node-payments-api',
    label: 'Payments API',
    status: 'CONSOLIDATED',
    stability: 0.7,
    ...POS.paymentsApi,
    parentId: 'node-fastapi'
  },
  {
    id: 'node-ecs',
    label: 'ECS + Docker',
    status: 'SUPERSEDED',
    stability: 0.7,
    ...POS.ecs
  },
  {
    id: 'node-deploy-v2',
    label: 'Deploy Config v2',
    status: 'ACTIVE',
    stability: 0.6,
    ...POS.deployV2,
    parentId: 'node-ecs'
  }],

  activeMemories: [
  { id: 'am-pytest', label: 'pytest preference', utility: 0.9 },
  { id: 'am-deploy-v2', label: 'Deploy Config v2', utility: 0.88 },
  { id: 'am-stack', label: 'FastAPI Services', utility: 0.85 },
  { id: 'am-db', label: 'DynamoDB detail', utility: 0.34, excluded: true }],

  schemas: [
  {
    id: 'sch-testing',
    type: 'PREFERENCE',
    summary: 'Testing → pytest',
    confidence: 0.83
  },
  {
    id: 'sch-deploy',
    type: 'PROCEDURE',
    summary: 'Deploy → ECS v2',
    confidence: 0.9
  },
  {
    id: 'sch-stack',
    type: 'FACT',
    summary: 'Stack → FastAPI Services',
    confidence: 0.95
  },
  {
    id: 'sch-db',
    type: 'FACT',
    summary: 'DB → DynamoDB',
    confidence: 0.78
  }],

  budgetUsed: 1480
}];