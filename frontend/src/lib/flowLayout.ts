// 流程图排版。后端只给节点、连线和实走顺序，坐标在这里算。
// 主链居中自上而下；从主链岔出去、且不是下一步的节点放到右侧，画成未走分支。

export interface FlowNode {
  id: string;
  label: string;
  kind: 'rect' | 'diamond';
  lane: string;
}

export interface FlowEdge {
  from: string;
  to: string;
  label?: string;
}

export interface FlowSpec {
  kind: 'flow';
  title?: string;
  nodes: FlowNode[];
  edges: FlowEdge[];
  path: string[];
}

export interface PlacedNode extends FlowNode {
  x: number;
  y: number;
  w: number;
  h: number;
}

const SPINE_X = 230;
const SIDE_X = 500;
const TOP = 46;
const GAP = 108;

export function layoutFlow(spec: FlowSpec): {
  nodes: PlacedNode[];
  width: number;
  height: number;
} {
  const byId = new Map(spec.nodes.map((node) => [node.id, node]));
  const spine = spec.path.filter((id, index) => byId.has(id) && spec.path.indexOf(id) === index);
  const placed = new Map<string, PlacedNode>();
  spine.forEach((id, index) => {
    const node = byId.get(id)!;
    const diamond = node.kind === 'diamond';
    placed.set(id, {
      ...node,
      x: SPINE_X,
      y: TOP + index * GAP,
      w: diamond ? 200 : 180,
      h: diamond ? 78 : 46,
    });
  });

  const sideSlot = new Map<string, number>();
  for (const edge of spec.edges) {
    if (!placed.has(edge.from) || placed.has(edge.to) || !byId.has(edge.to)) continue;
    const source = placed.get(edge.from)!;
    const slot = sideSlot.get(edge.from) ?? 0;
    sideSlot.set(edge.from, slot + 1);
    const node = byId.get(edge.to)!;
    const diamond = node.kind === 'diamond';
    placed.set(edge.to, {
      ...node,
      x: SIDE_X,
      y: source.y + slot * 64,
      w: diamond ? 180 : 168,
      h: diamond ? 72 : 44,
    });
  }

  let extra = 0;
  for (const node of spec.nodes) {
    if (placed.has(node.id)) continue;
    const diamond = node.kind === 'diamond';
    placed.set(node.id, {
      ...node,
      x: SPINE_X,
      y: TOP + (spine.length + extra) * GAP,
      w: diamond ? 200 : 180,
      h: diamond ? 78 : 46,
    });
    extra += 1;
  }

  const nodes = [...placed.values()];
  const bottom = nodes.reduce((max, node) => Math.max(max, node.y + node.h / 2), 80);
  const right = nodes.some((node) => node.x > SPINE_X) ? 680 : 420;
  return { nodes, width: right, height: bottom + 36 };
}

export function edgeActive(path: string[], from: string, to: string): boolean {
  const index = path.indexOf(from);
  return index >= 0 && path[index + 1] === to;
}
