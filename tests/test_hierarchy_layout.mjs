import assert from 'node:assert/strict';
import { GALAXY_RADIUS, galaxyArmPoint, hierarchyPositions, hierarchyPositions3D, hierarchyNodePositions3D, hierarchyZoom, hierarchySidebarGroups } from '../federation/web/hierarchy-layout.js';
const hub = (spaceId, parentSpaceId, spaceDepth, title) => ({
  id: spaceId + '/index', spaceId, parentSpaceId, spaceDepth, title, type: '分支', isFederationHub: true,
});
const nodes = [hub('central', null, 0, '中央'), hub('software', 'central', 1, '软件'),
  hub('software-app', 'software', 2, 'App'), hub('ios', 'software-app', 3, 'iOS'),
  hub('backend', 'software', 2, '后端'), hub('commerce', 'central', 1, '零售'),
  {id:'ios/topic', spaceId:'ios', spaceDepth:3, title:'iOS 页面', type:'知识', isFederationHub:false}];
const positions = hierarchyPositions(nodes);
assert.equal(positions.size, 6);
assert.deepEqual(positions.get('central'), {x:0, y:0, depth:0});
assert.equal(new Set([...positions.values()].map(p => `${p.x},${p.y}`)).size, 6);
for (const [id, point] of positions) {
  assert(Number.isFinite(point.x) && Number.isFinite(point.y));
  if (id !== 'central') assert(Math.hypot(point.x, point.y) >= 100);
}
const groups = hierarchySidebarGroups({nodes});
assert.deepEqual(groups.map(g=>g.t), ['中央主库','软件','零售']);
assert.deepEqual(groups[1].items.map(n=>n.id), ['software/index','software-app/index','ios/index','ios/topic','backend/index']);
assert(hierarchyZoom(nodes, 500, 800) > 0 && hierarchyZoom(nodes, 500, 800) < 1);
assert(hierarchyZoom(nodes, 1000, 800) > hierarchyZoom(nodes, 500, 800));

const industryNames = ['software', 'content', 'commerce', 'business'];
const fullNodes = [hub('central', null, 0, '中央')];
for (const id of industryNames) {
  fullNodes.push(hub(id, 'central', 1, id));
  for (let index = 0; index < 5; index++) fullNodes.push(hub(`${id}-${index}`, id, 2, `${id}-${index}`));
}
const spatial = hierarchyPositions3D(fullNodes);
assert.deepEqual(spatial.get('central'), {x:0, y:0, z:0, depth:0, armIndex:-1, armCount:4, progress:0});
assert.equal(spatial.size, 25);
assert.equal(new Set([...spatial.values()].map(point => `${point.x},${point.y},${point.z}`)).size, 25);
for (const point of spatial.values()) assert([point.x, point.y, point.z].every(Number.isFinite));
const stableEntries = map => [...map.entries()].sort(([left], [right]) => left.localeCompare(right));
assert.deepEqual(stableEntries(hierarchyPositions3D([...fullNodes].reverse())), stableEntries(spatial));

// Keep the historical 25-node fixture above; the software arm can independently
// acquire a sixth specialty without forcing equal branch sizes or flattening it.
const withUiux = [...fullNodes, hub('software-uiux', 'software', 2, 'UI/UX 设计师')];
const expandedSpatial = hierarchyPositions3D(withUiux);
assert.equal(expandedSpatial.size, 26);
assert.equal(expandedSpatial.get('software-uiux').depth, 2);
assert.equal(expandedSpatial.get('software-uiux').armIndex, expandedSpatial.get('software').armIndex);
assert.equal(new Set([...expandedSpatial.values()].map(point => `${point.x},${point.y},${point.z}`)).size, 26);
assert.deepEqual(stableEntries(hierarchyPositions3D([...withUiux].reverse())), stableEntries(expandedSpatial));
for (const industry of industryNames.filter(id => id !== 'software')) {
  for (const identifier of [industry, ...Array.from({length:5}, (_, index) => `${industry}-${index}`)]) {
    assert.deepEqual(expandedSpatial.get(identifier), spatial.get(identifier), 'Other industry arms retain their positions');
  }
}

// A scalar triple product proves that the view contains actual volume, not a tilted plane.
const [a, b, c] = industryNames.slice(0, 3).map(id => spatial.get(id));
const volume = a.x * (b.y * c.z - b.z * c.y)
  - a.y * (b.x * c.z - b.z * c.x) + a.z * (b.x * c.y - b.y * c.x);
assert(Math.abs(volume) > 1000);
const sortedIndustries = [...industryNames].sort();
assert.equal(GALAXY_RADIUS, 420);
for (const [armIndex, industry] of sortedIndustries.entries()) {
  const parent = spatial.get(industry);
  assert.equal(parent.armIndex, armIndex);
  assert.equal(parent.armCount, 4);
  assert.equal(parent.progress, 0.24);
  const expectedParent = galaxyArmPoint(armIndex, 4, 0.24);
  assert.deepEqual({x:parent.x, y:parent.y, z:parent.z}, expectedParent);
  const children = Array.from({length:5}, (_, index) => spatial.get(`${industry}-${index}`));
  for (const [index, child] of children.entries()) {
    assert.equal(child.armIndex, parent.armIndex, 'Specialties inherit their industry spiral arm');
    assert.equal(child.armCount, 4);
    assert.equal(child.progress, 0.43 + 0.57 * index / 4);
    assert(Math.hypot(child.x, child.y) > Math.hypot(parent.x, parent.y));
    const expected = galaxyArmPoint(armIndex, 4, child.progress);
    assert.deepEqual({x:child.x, y:child.y, z:child.z}, expected);
  }
  // The arm turns visibly as it travels outwards; it is not a radial spoke.
  const cross = children[0].x * children[4].y - children[0].y * children[4].x;
  assert(cross > 50_000);
}
for (let armIndex = 0; armIndex < 4; armIndex++) {
  const start = galaxyArmPoint(armIndex, 4, 0);
  const end = galaxyArmPoint(armIndex, 4, 1);
  assert(Math.abs(Math.hypot(start.x, start.y) - 60) < 0.001);
  assert(Math.abs(Math.hypot(end.x, end.y) - GALAXY_RADIUS) < 0.001);
  assert.deepEqual(galaxyArmPoint(armIndex, 4, -2), start);
  assert.deepEqual(galaxyArmPoint(armIndex, 4, 2), end);
  for (let step = 0; step <= 20; step++) {
    const point = galaxyArmPoint(armIndex, 4, step / 20);
    assert([point.x, point.y, point.z].every(Number.isFinite));
    assert(Math.abs(point.z) <= 20, 'The spiral arms stay inside a thin warped disk');
  }
}
assert(Object.values(galaxyArmPoint(NaN, 0, NaN)).every(Number.isFinite));

const deepNodes = [...fullNodes];
let parent = 'software-0';
for (let depth = 3; depth <= 6; depth++) {
  const id = `nested-${depth}`;
  deepNodes.push(hub(id, parent, depth, id));
  parent = id;
}
const deepPositions = hierarchyPositions3D(deepNodes);
assert.equal(deepPositions.get('nested-6').depth, 6);
for (let depth = 3; depth <= 6; depth++) {
  const point = deepPositions.get(`nested-${depth}`);
  const previous = deepPositions.get(depth === 3 ? 'software-0' : `nested-${depth - 1}`);
  assert.equal(point.armIndex, spatial.get('software').armIndex);
  assert(point.progress > previous.progress, 'A descendant comes after its parent on the same arm');
  const arm = galaxyArmPoint(point.armIndex, point.armCount, point.progress);
  assert(Math.hypot(point.x - arm.x, point.y - arm.y, point.z - arm.z) <= 27);
  assert(Math.hypot(point.x, point.y) <= GALAXY_RADIUS + 1);
}
assert.deepEqual(stableEntries(hierarchyPositions3D([...deepNodes].reverse())), stableEntries(deepPositions));

const pages = Array.from({length:50}, (_, index) => ({
  id:`nested-6/page-${String(index).padStart(2, '0')}`, spaceId:'nested-6', title:`Page ${index}`, isFederationHub:false,
}));
const allNodes = [...deepNodes, ...pages];
const allPositions = hierarchyNodePositions3D(allNodes);
assert.equal(allPositions.size, allNodes.length);
assert.deepEqual(allPositions.get('nested-6/index'), deepPositions.get('nested-6'));
assert.equal(new Set([...allPositions.values()].map(point => `${point.x},${point.y},${point.z}`)).size, allNodes.length);
const owner = allPositions.get('nested-6/index');
const distance = id => {
  const point = allPositions.get(id);
  return Math.hypot(point.x - owner.x, point.y - owner.y, point.z - owner.z);
};
for (const [index, page] of pages.entries()) {
  const point = allPositions.get(page.id);
  assert.equal(point.armIndex, owner.armIndex);
  assert.equal(point.progress, owner.progress);
  assert.equal(point.ownerSpaceId, 'nested-6');
  const radius = 20 + Math.floor(index / 24) * 12;
  const flattenedDistance = Math.hypot(point.x - owner.x, point.y - owner.y, (point.z - owner.z) / 0.4);
  assert(Math.abs(flattenedDistance - radius) < 0.001);
  assert(distance(page.id) <= radius + 0.001);
}
assert(distance(pages[49].id) > distance(pages[0].id));
assert.deepEqual(stableEntries(hierarchyNodePositions3D([...allNodes].reverse())), stableEntries(allPositions));
// Custom industries form additional arms instead of becoming unowned satellites.
const customNodes = [...fullNodes, hub('aerospace', 'central', 1, '航空'),
  hub('aerospace-flight', 'aerospace', 2, '飞行')];
const customPositions = hierarchyPositions3D(customNodes);
assert.equal(customPositions.get('aerospace').armCount, 5);
assert.equal(customPositions.get('aerospace').armIndex, 0);
assert.equal(customPositions.get('aerospace-flight').armIndex, 0);
assert(customPositions.get('aerospace-flight').progress > customPositions.get('aerospace').progress);
assert.equal(new Set([...customPositions.values()].map(point => `${point.x},${point.y},${point.z}`)).size, customPositions.size);
assert.deepEqual(stableEntries(hierarchyPositions3D([...customNodes].reverse())), stableEntries(customPositions));
console.log('Hierarchy layout: 2D compatibility, curved galaxy arms, deterministic ownership, thin 3D disk, six levels, custom industries, and knowledge satellites passed.');
