export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };
export type OutputPredicate = { path: string } & (
  { op: 'eq' | 'neq'; value: JsonValue } | { op: 'in'; value: JsonValue[] } | { op: 'exists'; value?: never }
);
export type NodeCondition = OutputPredicate & { source: string };
export interface NodeRepeat { max_iterations: number; until: { path: string; op: 'eq'; value: JsonValue } | { path: string; op: 'exists'; value?: never } }
export interface NodeForeach { source: string; path: string; max_items: number; mode?: 'serial' | 'parallel'; nested?: { path: string; max_items: number; mode?: 'serial' | 'parallel' } }
export interface NodeLoop { body: string[]; max_iterations: number; until: NodeCondition }
export interface NodeDynamicPlan { source: string; path: string; max_items: number; mode?: 'serial' | 'parallel'; topology?: 'list' | 'dag' }
export interface NodeDynamicSubgraph { source: string; path: string; max_nodes: number; mode?: 'serial' | 'parallel' }
export interface SubgraphNode extends Omit<OrchestrationNode, 'subgraph'> {
  id: string;
  name?: string;
  agent_id?: string;
  model?: string;
  prompt?: string;
  deps?: string[];
  inputRefs?: string[];
  final_report?: boolean;
  x?: number;
  y?: number;
  subgraph?: NodeSubgraph;
}
export interface NodeSubgraph { max_concurrency?: number; nodes?: SubgraphNode[]; dynamic?: NodeDynamicSubgraph }
export interface OrchestrationNode {
  condition?: NodeCondition;
  repeat?: NodeRepeat;
  foreach?: NodeForeach;
  loop?: NodeLoop;
  dynamic_plan?: NodeDynamicPlan;
  subgraph?: NodeSubgraph;
  allow_missing_inputs?: boolean;
}
export interface TemplateNode extends OrchestrationNode {
  id: string;
  name: string;
  x: number;
  y: number;
  deps: string[];
  agent_id?: string;
  model?: string;
  prompt?: string;
  inputRefs?: string[];
  final_report?: boolean;
  requires_human?: boolean;
  node_type?: 'agent' | 'human' | 'human_gate';
  human_action?: 'select_outputs' | 'approve' | 'edit';
  allow_skip?: boolean;
  allow_missing_inputs?: boolean;
  [key: string]: unknown;
}

export interface ClientTemplate {
  id: string;
  title: string;
  description: string;
  nodes: TemplateNode[];
  version: number;
  max_concurrency?: number;
}
