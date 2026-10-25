import type { AdminRunFlow } from '../lib/api';

type Kind = 'rect' | 'diamond';

interface LayoutNode {
  key: string;
  x: number;
  y: number;
  w: number;
  h: number;
  kind: Kind;
  color: string;
  terminal?: boolean;
}

/** 坐标与 RAG 问答溯源同构：主链居中，终端右岔。 */
const LAYOUT: Record<string, LayoutNode> = {
  received: { key: 'received', x: 250, y: 40, w: 190, h: 48, kind: 'rect', color: 'blue' },
  quota_check: { key: 'quota_check', x: 250, y: 142, w: 210, h: 84, kind: 'diamond', color: 'blue' },
  quota_paused: { key: 'quota_paused', x: 520, y: 142, w: 180, h: 48, kind: 'rect', color: 'red', terminal: true },
  plan: { key: 'plan', x: 250, y: 244, w: 190, h: 48, kind: 'rect', color: 'purple' },
  route: { key: 'route', x: 250, y: 346, w: 210, h: 84, kind: 'diamond', color: 'purple' },
  chitchat: { key: 'chitchat', x: 520, y: 346, w: 180, h: 48, kind: 'rect', color: 'gray', terminal: true },
  tools: { key: 'tools', x: 250, y: 448, w: 190, h: 48, kind: 'rect', color: 'teal' },
  error: { key: 'error', x: 520, y: 448, w: 180, h: 48, kind: 'rect', color: 'red', terminal: true },
  retrieve: { key: 'retrieve', x: 250, y: 532, w: 190, h: 48, kind: 'rect', color: 'teal' },
  validate: { key: 'validate', x: 250, y: 634, w: 210, h: 84, kind: 'diamond', color: 'amber' },
  mismatch: { key: 'mismatch', x: 520, y: 634, w: 180, h: 48, kind: 'rect', color: 'amber', terminal: true },
  generate: { key: 'generate', x: 250, y: 736, w: 190, h: 48, kind: 'rect', color: 'green' },
  done: { key: 'done', x: 250, y: 820, w: 190, h: 48, kind: 'rect', color: 'green', terminal: true },
};

const FALLBACK_EDGES = [
  { from: 'received', to: 'quota_check' },
  { from: 'quota_check', to: 'quota_paused', label: '不足' },
  { from: 'quota_check', to: 'plan', label: '通过' },
  { from: 'plan', to: 'route' },
  { from: 'route', to: 'chitchat', label: '直答' },
  { from: 'route', to: 'tools', label: '需工具' },
  { from: 'tools', to: 'retrieve', label: '检索' },
  { from: 'retrieve', to: 'validate' },
  { from: 'tools', to: 'validate', label: '无检索' },
  { from: 'tools', to: 'error', label: '出错' },
  { from: 'validate', to: 'mismatch', label: '未对齐' },
  { from: 'validate', to: 'generate', label: '通过' },
  { from: 'generate', to: 'done' },
];

function nodeOf(key: string): LayoutNode | undefined {
  return LAYOUT[key];
}

function topOf(n: LayoutNode): number {
  return n.y - n.h / 2;
}

function bottomOf(n: LayoutNode): number {
  return n.y + n.h / 2;
}

function diamondPoints(n: LayoutNode): string {
  return [
    `${n.x},${n.y - n.h / 2}`,
    `${n.x + n.w / 2},${n.y}`,
    `${n.x},${n.y + n.h / 2}`,
    `${n.x - n.w / 2},${n.y}`,
  ].join(' ');
}

function edgePath(from: string, to: string): string | null {
  const a = nodeOf(from);
  const b = nodeOf(to);
  if (!a || !b) return null;
  if (a.y === b.y) {
    return `M ${a.x + a.w / 2} ${a.y} L ${b.x - b.w / 2} ${b.y}`;
  }
  if (from === 'tools' && to === 'validate') {
    const x = a.x - a.w / 2 - 36;
    const y1 = bottomOf(a);
    const y2 = topOf(b);
    return `M ${a.x - 24} ${y1} L ${x} ${y1 + 8} L ${x} ${y2 - 8} L ${b.x - 24} ${y2}`;
  }
  return `M ${a.x} ${bottomOf(a)} L ${b.x} ${topOf(b)}`;
}

function edgeLabelPos(from: string, to: string): { x: number; y: number; anchor: 'start' | 'end' | 'middle' } | null {
  const a = nodeOf(from);
  const b = nodeOf(to);
  if (!a || !b) return null;
  if (a.y === b.y) {
    return { x: (a.x + a.w / 2 + b.x - b.w / 2) / 2, y: a.y - 9, anchor: 'middle' };
  }
  if (from === 'tools' && to === 'validate') {
    return { x: a.x - a.w / 2 - 42, y: (bottomOf(a) + topOf(b)) / 2, anchor: 'end' };
  }
  return { x: a.x + 10, y: (bottomOf(a) + topOf(b)) / 2, anchor: 'start' };
}

export function flowPathOf(flow?: AdminRunFlow | null): string[] {
  if (!flow) return [];
  return flow.flow_path?.length ? flow.flow_path : (flow.path ?? []);
}

export default function FlowPathSvg({ flow }: { flow?: AdminRunFlow | null }) {
  const path = flowPathOf(flow);
  const marks = new Set(flow?.marks ?? []);
  const active = new Set([...path, ...marks]);
  const labels = new Map((flow?.nodes ?? []).map((n) => [n.key, n.label]));
  const edges = flow?.edges?.length ? flow.edges : FALLBACK_EDGES;
  const nodes = Object.values(LAYOUT);

  const stepOf = (key: string): number | null => {
    const i = path.indexOf(key);
    return i < 0 ? null : i + 1;
  };
  const edgeActive = (from: string, to: string) => {
    const i = path.indexOf(from);
    return i >= 0 && path[i + 1] === to;
  };

  if (!flow || path.length === 0) {
    return <p className="admin-sub">没有可用的节点流（无 trace）。</p>;
  }

  return (
    <div className="admin-flow-wrap">
      <svg viewBox="0 0 680 860" className="admin-flow-svg" role="img" aria-label="任务实走路径">
        <defs>
          <marker id="fa-on" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#475569" />
          </marker>
          <marker id="fa-off" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#cbd5e1" />
          </marker>
        </defs>
        {edges.map((e) => {
          const d = edgePath(e.from, e.to);
          if (!d) return null;
          const on = edgeActive(e.from, e.to);
          const pos = e.label ? edgeLabelPos(e.from, e.to) : null;
          return (
            <g key={`${e.from}-${e.to}`}>
              <path
                d={d}
                className={on ? 'edge on' : 'edge'}
                fill="none"
                markerEnd={on ? 'url(#fa-on)' : 'url(#fa-off)'}
              />
              {e.label && pos && (
                <text x={pos.x} y={pos.y} textAnchor={pos.anchor} className={on ? 'elabel on' : 'elabel'}>
                  {e.label}
                </text>
              )}
            </g>
          );
        })}
        {nodes.map((n) => {
          const on = active.has(n.key);
          const step = stepOf(n.key);
          const cls = `nd c-${n.color} ${on ? 'on' : 'off'}`;
          const stepY = n.kind === 'diamond' ? n.y : n.y - n.h / 2;
          return (
            <g key={n.key}>
              {n.kind === 'diamond' ? (
                <polygon points={diamondPoints(n)} className={cls} />
              ) : (
                <rect x={n.x - n.w / 2} y={n.y - n.h / 2} width={n.w} height={n.h} rx={10} className={cls} />
              )}
              <text x={n.x} y={n.y + 5} textAnchor="middle" className={on ? 'tt on' : 'tt off'}>
                {labels.get(n.key) ?? n.key}
              </text>
              {step != null && (
                <g>
                  <circle cx={n.x - n.w / 2} cy={stepY} r={11} className="stepbg" />
                  <text x={n.x - n.w / 2} y={stepY + 4} textAnchor="middle" className="steptext">{step}</text>
                </g>
              )}
            </g>
          );
        })}
      </svg>
      <div className="admin-flow-legend">
        <span><i className="dot d-blue" />额度</span>
        <span><i className="dot d-purple" />意图</span>
        <span><i className="dot d-teal" />工具/检索</span>
        <span><i className="dot d-amber" />校验</span>
        <span><i className="dot d-green" />生成</span>
        <span><i className="dot d-red" />拒答/出错</span>
        <span><i className="dot d-gray" />直答</span>
        <span className="sep" />
        <span><i className="lg lg-on" />实线 = 实走（角标 = 第几步）</span>
        <span><i className="lg lg-off" />虚线 = 未走</span>
      </div>
    </div>
  );
}
