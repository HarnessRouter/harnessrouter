export interface TemplateNode {
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
}
