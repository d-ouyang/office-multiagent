import { edgeActive, layoutFlow, type FlowSpec } from '../lib/flowLayout';

const LANE: Record<string, { fill: string; stroke: string }> = {
  blue: { fill: '#DBEAFE', stroke: '#60A5FA' },
  purple: { fill: '#EDE9FE', stroke: '#A78BFA' },
  teal: { fill: '#CCFBF1', stroke: '#2DD4BF' },
  amber: { fill: '#FFEDD5', stroke: '#FB923C' },
  green: { fill: '#DCFCE7', stroke: '#4ADE80' },
  red: { fill: '#FFE4E6', stroke: '#FB7185' },
  gray: { fill: '#F3F4F6', stroke: '#D1D5DB' },
};

function points(node: { x: number; y: number; w: number; h: number }): string {
  return [
    `${node.x},${node.y - node.h / 2}`,
    `${node.x + node.w / 2},${node.y}`,
    `${node.x},${node.y + node.h / 2}`,
    `${node.x - node.w / 2},${node.y}`,
  ].join(' ');
}

export function FlowChart({ spec }: { spec: FlowSpec }) {
  const layout = layoutFlow(spec);
  const placed = new Map(layout.nodes.map((node) => [node.id, node]));
  return (
    <figure className="flow-card">
      {spec.title && <figcaption>{spec.title}</figcaption>}
      <svg viewBox={`0 0 ${layout.width} ${layout.height}`} role="img" aria-label={spec.title || '流程图'}>
        {spec.edges.map((edge) => {
          const from = placed.get(edge.from);
          const to = placed.get(edge.to);
          if (!from || !to) return null;
          const on = edgeActive(spec.path, edge.from, edge.to);
          const horizontal = Math.abs(from.x - to.x) > 40;
          const x1 = horizontal ? from.x + from.w / 2 : from.x;
          const y1 = horizontal ? from.y : from.y + from.h / 2;
          const x2 = horizontal ? to.x - to.w / 2 : to.x;
          const y2 = horizontal ? to.y : to.y - to.h / 2;
          const midX = (x1 + x2) / 2;
          const midY = (y1 + y2) / 2;
          return (
            <g key={`${edge.from}-${edge.to}`}>
              <line x1={x1} y1={y1} x2={x2} y2={y2} className={on ? 'flow-edge on' : 'flow-edge'} />
              {edge.label && (
                <text x={midX + 6} y={midY - 4} className={on ? 'flow-elabel on' : 'flow-elabel'}>
                  {edge.label}
                </text>
              )}
            </g>
          );
        })}
        {layout.nodes.map((node) => {
          const on = spec.path.includes(node.id);
          const color = LANE[node.lane] || LANE.blue;
          const step = spec.path.indexOf(node.id);
          return (
            <g key={node.id} opacity={on ? 1 : 0.55}>
              {node.kind === 'diamond' ? (
                <polygon points={points(node)} fill={color.fill} stroke={color.stroke} />
              ) : (
                <rect
                  x={node.x - node.w / 2}
                  y={node.y - node.h / 2}
                  width={node.w}
                  height={node.h}
                  rx={12}
                  fill={color.fill}
                  stroke={color.stroke}
                />
              )}
              <text x={node.x} y={node.y + 5} textAnchor="middle" className="flow-label">
                {node.label}
              </text>
              {step >= 0 && (
                <>
                  <circle cx={node.x - node.w / 2} cy={node.y - node.h / 2} r={11} className="flow-step" />
                  <text x={node.x - node.w / 2} y={node.y - node.h / 2 + 4} textAnchor="middle" className="flow-step-text">
                    {step + 1}
                  </text>
                </>
              )}
            </g>
          );
        })}
      </svg>
    </figure>
  );
}
