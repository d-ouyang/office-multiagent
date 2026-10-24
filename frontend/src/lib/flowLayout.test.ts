import { describe, expect, it } from 'vitest';

import { edgeActive, layoutFlow } from './flowLayout';

describe('layoutFlow', () => {
  it('puts the taken path in a column and the branch to the side', () => {
    const layout = layoutFlow({
      kind: 'flow',
      nodes: [
        { id: 'a', label: '提交', kind: 'rect', lane: 'blue' },
        { id: 'b', label: '超限?', kind: 'diamond', lane: 'amber' },
        { id: 'c', label: '加签', kind: 'rect', lane: 'red' },
      ],
      edges: [
        { from: 'a', to: 'b' },
        { from: 'b', to: 'c', label: '是' },
      ],
      path: ['a', 'b'],
    });
    const byId = Object.fromEntries(layout.nodes.map((node) => [node.id, node]));
    expect(byId.a.x).toBe(byId.b.x);
    expect(byId.b.y).toBeGreaterThan(byId.a.y);
    expect(byId.c.x).toBeGreaterThan(byId.b.x);
    expect(edgeActive(['a', 'b'], 'a', 'b')).toBe(true);
    expect(edgeActive(['a', 'b'], 'b', 'c')).toBe(false);
  });
});
