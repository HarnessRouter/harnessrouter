export interface TemplateNode {
  id: string;
  name: string;
  x: number;
  y: number;
  deps: string[];
}

export interface ClientTemplate {
  id: string;
  title: string;
  description: string;
  nodes: TemplateNode[];
  version: number;
}
