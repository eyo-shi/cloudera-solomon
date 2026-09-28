/**
 * ノードドラッグ時に近接ノードも連動して動く — Neo4j Browser 風の軽量 force シミュレーション。
 */
import type { Core, EventObject } from "cytoscape";

const REST_LENGTH = 110;
const SPRING = 0.045;
const REPULSE = 1400;
const DAMPING = 0.82;
const MAX_V = 9;
const DRAG_STEPS = 4;
const SETTLE_FRAMES = 22;

export function attachDragPhysics(cy: Core): () => void {
  let pinnedId: string | null = null;
  let settleRaf = 0;
  const velocities = new Map<string, { vx: number; vy: number }>();

  function step() {
    const nodes = cy.nodes();
    if (nodes.empty()) return;

    const fxMap = new Map<string, { fx: number; fy: number }>();
    nodes.forEach((n) => {
      fxMap.set(n.id(), { fx: 0, fy: 0 });
    });

    cy.edges().forEach((edge) => {
      const s = edge.source();
      const t = edge.target();
      const sp = s.position();
      const tp = t.position();
      let dx = tp.x - sp.x;
      let dy = tp.y - sp.y;
      const dist = Math.max(Math.hypot(dx, dy), 1);
      const force = SPRING * (dist - REST_LENGTH);
      dx = (dx / dist) * force;
      dy = (dy / dist) * force;
      const sf = fxMap.get(s.id())!;
      sf.fx += dx;
      sf.fy += dy;
      const tf = fxMap.get(t.id())!;
      tf.fx -= dx;
      tf.fy -= dy;
    });

    const nodeArr = nodes.toArray();
    for (let i = 0; i < nodeArr.length; i++) {
      for (let j = i + 1; j < nodeArr.length; j++) {
        const a = nodeArr[i];
        const b = nodeArr[j];
        const ap = a.position();
        const bp = b.position();
        let dx = ap.x - bp.x;
        let dy = ap.y - bp.y;
        const dist = Math.max(Math.hypot(dx, dy), 36);
        const force = REPULSE / (dist * dist);
        dx = (dx / dist) * force;
        dy = (dy / dist) * force;
        const af = fxMap.get(a.id())!;
        af.fx += dx;
        af.fy += dy;
        const bf = fxMap.get(b.id())!;
        bf.fx -= dx;
        bf.fy -= dy;
      }
    }

    nodes.forEach((n) => {
      if (n.id() === pinnedId) return;
      const f = fxMap.get(n.id())!;
      const prev = velocities.get(n.id()) ?? { vx: 0, vy: 0 };
      const vx = Math.max(-MAX_V, Math.min(MAX_V, (prev.vx + f.fx) * DAMPING));
      const vy = Math.max(-MAX_V, Math.min(MAX_V, (prev.vy + f.fy) * DAMPING));
      velocities.set(n.id(), { vx, vy });
      const p = n.position();
      n.position({ x: p.x + vx, y: p.y + vy });
    });
  }

  function runSteps(count: number) {
    for (let i = 0; i < count; i++) step();
  }

  function cancelSettle() {
    if (settleRaf) {
      cancelAnimationFrame(settleRaf);
      settleRaf = 0;
    }
  }

  function settle() {
    cancelSettle();
    let frame = 0;
    const tick = () => {
      runSteps(2);
      frame += 1;
      if (frame < SETTLE_FRAMES) {
        settleRaf = requestAnimationFrame(tick);
      } else {
        settleRaf = 0;
        velocities.clear();
      }
    };
    settleRaf = requestAnimationFrame(tick);
  }

  const onGrab = (evt: EventObject) => {
    cancelSettle();
    pinnedId = evt.target.id();
  };

  const onDrag = () => {
    runSteps(DRAG_STEPS);
  };

  const onFree = () => {
    pinnedId = null;
    settle();
  };

  cy.on("grab", "node", onGrab);
  cy.on("drag", "node", onDrag);
  cy.on("free", "node", onFree);

  return () => {
    cancelSettle();
    cy.removeListener("grab", "node", onGrab);
    cy.removeListener("drag", "node", onDrag);
    cy.removeListener("free", "node", onFree);
    velocities.clear();
  };
}
