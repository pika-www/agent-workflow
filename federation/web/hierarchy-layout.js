/* Hierarchy layouts for the 3D adapter and the preserved OpenWiki sidebar. */
function hierarchy(nodes) {
  const hubs = nodes.filter(node => node.isFederationHub);
  const bySpace = new Map(hubs.map(node => [node.spaceId, node]));
  const children = new Map(hubs.map(node => [node.spaceId, []]));
  for (const node of hubs) {
    if (node.spaceId === 'central') continue;
    const parent = bySpace.has(node.parentSpaceId) ? node.parentSpaceId : 'central';
    children.get(parent)?.push(node);
  }
  return { hubs, children, bySpace };
}

export function hierarchyPositions(nodes) {
  const { children } = hierarchy(nodes);
  const positions = new Map([['central', { x: 0, y: 0, depth: 0 }]]);
  const weights = new Map();
  function weight(id, visiting = new Set()) {
    if (weights.has(id)) return weights.get(id);
    if (visiting.has(id)) return 1;
    const next = new Set(visiting).add(id);
    const value = Math.max(1, (children.get(id) || []).reduce((sum, child) => sum + weight(child.spaceId, next), 0));
    weights.set(id, value); return value;
  }
  function place(id, start, span, depth) {
    const items = children.get(id) || [];
    const total = items.reduce((sum, child) => sum + weight(child.spaceId), 0);
    let angle = start;
    for (const child of items) {
      const sector = span * weight(child.spaceId) / total;
      const middle = angle + sector / 2;
      const radius = depth === 1 ? 105 : 105 + (depth - 1) * 120;
      if (!positions.has(child.spaceId)) {
        positions.set(child.spaceId, { x: radius * Math.cos(middle), y: radius * Math.sin(middle), depth });
        place(child.spaceId, angle + sector * 0.065, sector * 0.87, depth + 1);
      }
      angle += sector;
    }
  }
  place('central', -Math.PI, Math.PI * 2, 1);
  return positions;
}

/* Shared geometry for the visible Agents and the decorative galaxy particles. */
export const GALAXY_RADIUS = 420;

export function galaxyArmPoint(armIndex, armCount, progress) {
  const count = Math.max(1, Number.isFinite(armCount) ? Math.floor(armCount) : 1);
  const index = Number.isFinite(armIndex) ? armIndex : 0;
  const fraction = Math.max(0, Math.min(1, Number.isFinite(progress) ? progress : 0));
  const phase = -Math.PI / 2 + index * Math.PI * 2 / count;
  const angle = phase + 3.7 * fraction;
  const radius = 60 + (GALAXY_RADIUS - 60) * fraction;
  return {
    x: radius * Math.cos(angle),
    y: radius * Math.sin(angle),
    // The disk has a little thickness and warp; the Agents never share one plane.
    z: 12 * Math.sin(2 * phase + 0.8 + fraction * 3)
      + 8 * Math.sin(angle * 3 + fraction * 4),
  };
}

export function hierarchyPositions3D(nodes) {
  const { children } = hierarchy(nodes);
  const compareIds = (left, right) => left.spaceId < right.spaceId ? -1 : left.spaceId > right.spaceId ? 1 : 0;
  for (const items of children.values()) items.sort(compareIds);
  const industries = children.get('central') || [];
  const armCount = industries.length;
  const positions = new Map([['central', { x: 0, y: 0, z: 0, depth: 0, armIndex: -1, armCount, progress: 0 }]]);
  const visited = new Set(['central']);
  industries.forEach((industry, armIndex) => {
    if (visited.has(industry.spaceId)) return;
    visited.add(industry.spaceId);
    const industryProgress = 0.24;
    positions.set(industry.spaceId, {
      ...galaxyArmPoint(armIndex, armCount, industryProgress),
      depth: 1, armIndex, armCount, progress: industryProgress,
    });
    // Preorder preserves every parent before its descendants on the same arm.
    // As a branch grows, its arm redistributes its Agents inside the same disk.
    const descendants = [];
    function collect(id, depth) {
      for (const child of children.get(id) || []) {
        if (visited.has(child.spaceId)) continue;
        visited.add(child.spaceId);
        descendants.push({ node: child, depth });
        collect(child.spaceId, depth + 1);
      }
    }
    collect(industry.spaceId, 2);
    descendants.forEach(({ node, depth }, index) => {
      const fraction = descendants.length === 1 ? 0.45 : index / (descendants.length - 1);
      const progress = 0.43 + 0.57 * fraction;
      const point = galaxyArmPoint(armIndex, armCount, progress);
      const angle = Math.atan2(point.y, point.x);
      const side = Math.min(24, Math.max(0, depth - 2) * 7) * (index % 2 === 0 ? 1 : -1);
      positions.set(node.spaceId, {
        x: point.x - Math.sin(angle) * side,
        y: point.y + Math.cos(angle) * side,
        z: point.z + Math.max(0, depth - 2) * 2.5 * (index % 2 === 0 ? 1 : -1),
        depth, armIndex, armCount, progress,
      });
    });
  });
  return positions;
}

export function hierarchyNodePositions3D(nodes) {
  const hubs = hierarchyPositions3D(nodes);
  const positions = new Map();
  const pages = new Map();
  for (const node of nodes) {
    if (node.isFederationHub) {
      if (hubs.has(node.spaceId)) positions.set(node.id, { ...hubs.get(node.spaceId) });
    } else {
      if (!pages.has(node.spaceId)) pages.set(node.spaceId, []);
      pages.get(node.spaceId).push(node);
    }
  }
  const goldenAngle = Math.PI * (3 - Math.sqrt(5));
  for (const [spaceId, items] of pages) {
    const hub = hubs.get(spaceId);
    if (!hub) continue;
    items.sort((left, right) => left.id < right.id ? -1 : left.id > right.id ? 1 : 0);
    // Expanding shells keep large libraries from collapsing into one dense ball.
    for (let index = 0; index < items.length; index++) {
      const shell = Math.floor(index / 24);
      const shellIndex = index % 24;
      const shellSize = Math.min(24, items.length - shell * 24);
      const radius = 20 + shell * 12;
      const vertical = 1 - 2 * (shellIndex + 0.5) / shellSize;
      const ring = Math.sqrt(Math.max(0, 1 - vertical * vertical));
      const angle = (index + 1) * goldenAngle;
      positions.set(items[index].id, {
        x: hub.x + radius * ring * Math.cos(angle),
        y: hub.y + radius * ring * Math.sin(angle),
        z: hub.z + radius * vertical * 0.4,
        depth: hub.depth,
        armIndex: hub.armIndex,
        armCount: hub.armCount,
        progress: hub.progress,
        ownerSpaceId: spaceId,
      });
    }
  }
  return positions;
}

export function hierarchyZoom(nodes, width, height) {
  const points = [...hierarchyPositions(nodes).values()];
  const x = Math.max(100, ...points.map(point => Math.abs(point.x)));
  const y = Math.max(100, ...points.map(point => Math.abs(point.y)));
  return Math.max(0.15, Math.min(2, (width - 90) / (2 * x + 100), (height - 90) / (2 * y + 70)));
}

export function hierarchySidebarGroups(graph) {
  const { children, bySpace } = hierarchy(graph.nodes);
  const pages = new Map();
  for (const node of graph.nodes) {
    if (!pages.has(node.spaceId)) pages.set(node.spaceId, []);
    if (!node.isFederationHub) pages.get(node.spaceId).push(node);
  }
  function collect(id, nested, seen = new Set()) {
    if (seen.has(id)) return [];
    seen.add(id);
    const hub = bySpace.get(id);
    const own = [...(pages.get(id) || [])].sort((a, b) => a.title.localeCompare(b.title));
    return [...(hub ? [hub] : []), ...own,
      ...(nested ? (children.get(id) || []).flatMap(child => collect(child.spaceId, true, seen)) : [])];
  }
  const central = bySpace.get('central');
  const groups = central ? [{ t: '中央主库', type: central.type, items: collect('central', false) }] : [];
  for (const child of children.get('central') || []) {
    groups.push({ t: child.title, type: child.type, items: collect(child.spaceId, true) });
  }
  return groups;
}
