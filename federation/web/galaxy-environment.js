/* Procedural Milky Way environment. Decorations never own Agent interactions. */
import * as THREE from 'three';
import { GALAXY_RADIUS, galaxyArmPoint } from './hierarchy-layout.js';

const TAU = Math.PI * 2;
const noop = () => {};
const clamp = (value, low = 0, high = 1) => Math.max(low, Math.min(high, value));
const WARM = new THREE.Color('#ffd39a');
const IVORY = new THREE.Color('#fff1d2');
const PALE_BLUE = new THREE.Color('#b9d8ff');
const BLUE = new THREE.Color('#709ce8');
const LILAC = new THREE.Color('#b3a0df');

function seededRandom(seed) {
  let state = seed >>> 0;
  return () => {
    state += 0x6d2b79f5;
    let value = state;
    value = Math.imul(value ^ value >>> 15, value | 1);
    value ^= value + Math.imul(value ^ value >>> 7, value | 61);
    return ((value ^ value >>> 14) >>> 0) / 4294967296;
  };
}

function gaussian(random) {
  return Math.sqrt(-2 * Math.log(Math.max(random(), 0.000001))) * Math.cos(TAU * random());
}

function attributes() {
  return { position: [], color: [], size: [], opacity: [], seed: [] };
}

function append(target, x, y, z, color, size, opacity, seed) {
  target.position.push(x, y, z);
  target.color.push(color.r, color.g, color.b);
  target.size.push(size);
  target.opacity.push(opacity);
  target.seed.push(seed);
}

function colorBetween(first, second, amount) {
  return first.clone().lerp(second, clamp(amount));
}

const VERTEX_SHADER = `
  attribute float aSize;
  attribute float aOpacity;
  attribute float aSeed;
  varying vec3 vColor;
  varying float vOpacity;
  varying float vSeed;
  uniform float uProjectionScale;
  void main() {
    vec4 cameraPosition = modelViewMatrix * vec4(position, 1.0);
    gl_Position = projectionMatrix * cameraPosition;
    gl_PointSize = clamp(aSize * uProjectionScale / max(1.0, -cameraPosition.z), 0.7, 140.0);
    vColor = color;
    vOpacity = aOpacity;
    vSeed = aSeed;
  }
`;

const FRAGMENT_SHADER = `
  varying vec3 vColor;
  varying float vOpacity;
  varying float vSeed;
  uniform float uIntensity;
  uniform float uMist;
  float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7)) + vSeed * 103.9) * 43758.5453);
  }
  float noise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), f.x),
               mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0)), f.x), f.y);
  }
  void main() {
    vec2 p = gl_PointCoord * 2.0 - 1.0;
    float radius2 = dot(p, p);
    if (radius2 > 1.0) discard;
    float rim = 1.0 - smoothstep(0.62, 1.0, radius2);
    float star = exp(-radius2 * 7.0) + 0.24 * exp(-radius2 * 30.0);
    float cloud = exp(-radius2 * 3.2) * (0.56 + 0.44 * noise(p * 4.0));
    float alpha = mix(star, cloud, uMist) * rim * vOpacity * uIntensity;
    if (alpha < 0.001) discard;
    gl_FragColor = vec4(vColor, alpha);
    #include <colorspace_fragment>
  }
`;

function makeLayer(data, mist, projectionSize) {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(data.position, 3));
  geometry.setAttribute('color', new THREE.Float32BufferAttribute(data.color, 3));
  geometry.setAttribute('aSize', new THREE.Float32BufferAttribute(data.size, 1));
  geometry.setAttribute('aOpacity', new THREE.Float32BufferAttribute(data.opacity, 1));
  geometry.setAttribute('aSeed', new THREE.Float32BufferAttribute(data.seed, 1));
  geometry.computeBoundingSphere();
  const material = new THREE.ShaderMaterial({
    vertexShader: VERTEX_SHADER,
    fragmentShader: FRAGMENT_SHADER,
    uniforms: {
      uProjectionScale: { value: 800 },
      uIntensity: { value: 1 },
      uMist: { value: mist ? 1 : 0 },
    },
    vertexColors: true,
    transparent: true,
    depthWrite: false,
    depthTest: true,
    blending: THREE.AdditiveBlending,
    toneMapped: false,
  });
  const points = new THREE.Points(geometry, material);
  points.name = mist ? 'Galaxy stellar mist' : 'Galaxy stars';
  points.raycast = noop;
  points.renderOrder = mist ? -40 : -30;
  points.frustumCulled = false;
  points.userData.federationDecoration = true;
  points.userData.ignoreBounds = true;
  // Perspective-correct world sizes also stay crisp on Retina displays.
  points.onBeforeRender = (renderer, _scene, camera) => {
    renderer.getDrawingBufferSize(projectionSize);
    material.uniforms.uProjectionScale.value = projectionSize.y * 0.5 * camera.projectionMatrix.elements[5];
  };
  return points;
}

/**
 * A thin, genuinely three-dimensional star disk aligned with the Agent arms.
 * The two geometries contain 38,000 points and remain static between updates.
 * The caller owns the camera, rendering loop, background, and scene lifetime.
 */
export function createGalaxyEnvironment(scene) {
  const group = new THREE.Group();
  group.name = 'Agent galaxy environment';
  group.raycast = noop;
  group.userData.federationDecoration = true;
  group.userData.ignoreBounds = true;
  scene.add(group);
  const projectionSize = new THREE.Vector2();
  let lastArmCount = null;
  let intensity = 1;
  let disposed = false;

  function releaseLayers() {
    for (const layer of [...group.children]) {
      group.remove(layer);
      layer.geometry.dispose();
      layer.material.dispose();
      layer.onBeforeRender = noop;
    }
  }

  function rebuild(armCount) {
    releaseLayers();
    const stars = attributes();
    const mist = attributes();
    const random = seededRandom(0x718ac);
    const scale = GALAXY_RADIUS / 420;

    // Dense oblate bulge: warm stars and a compact luminous heart, not a white disk.
    for (let i = 0; i < 6000; i++) {
      const radius = Math.min(165, -Math.log(Math.max(0.00001, random())) * 39);
      const angle = random() * TAU;
      const color = colorBetween(IVORY, WARM, clamp(radius / 95) * 0.8 + random() * 0.15);
      const bright = random();
      append(stars,
        Math.cos(angle) * radius * scale,
        Math.sin(angle) * radius * 0.9 * scale,
        gaussian(random) * (4 + 15 * Math.exp(-radius / 55)) * scale,
        color, (1.0 + bright ** 5 * 4.2) * scale,
        0.28 + bright * 0.62, random());
    }

    // Spiral arm filaments share the exact curve used by the knowledge hierarchy.
    const armRandom = seededRandom(0xe613b ^ armCount);
    for (let i = 0; i < 19000; i++) {
      const arm = i % armCount;
      const progress = armRandom() ** 0.85;
      const center = galaxyArmPoint(arm, armCount, progress);
      const next = galaxyArmPoint(arm, armCount, Math.min(1, progress + 0.003));
      const before = galaxyArmPoint(arm, armCount, Math.max(0, progress - 0.003));
      const dx = next.x - before.x, dy = next.y - before.y;
      const length = Math.max(0.0001, Math.hypot(dx, dy));
      const tx = dx / length, ty = dy / length;
      const width = (15 + 37 * progress) * scale;
      const filament = Math.sin(progress * 34 + arm * 2.1) * width * 0.24;
      let cross = gaussian(armRandom) * width * 0.60 + filament;
      // Two adjacent filaments leave a narrow broken dark dust lane between them.
      const dust = (0.6 + 0.4 * Math.sin(progress * 44 + arm)) * width * 0.19;
      cross += cross < 0 ? -dust : dust;
      const along = gaussian(armRandom) * (3 + progress * 5) * scale;
      const outerColor = armRandom() < 0.095 ? LILAC : PALE_BLUE;
      const color = progress < 0.24
        ? colorBetween(WARM, outerColor, progress / 0.24)
        : colorBetween(outerColor, BLUE, armRandom() * 0.58);
      const bright = armRandom();
      const cluster = 0.54 + 0.46 * Math.sin(progress * 53 + arm * 1.8) ** 2;
      append(stars,
        center.x - ty * cross + tx * along,
        center.y + tx * cross + ty * along,
        center.z + gaussian(armRandom) * (3.2 + progress * 3.8) * scale,
        color, (1.05 + bright ** 5 * 4.6) * scale,
        (0.30 + bright * 0.70) * cluster, armRandom());
    }

    // The inter-arm disk is much fainter, with plenty of dark negative space.
    for (let i = 0; i < 7000; i++) {
      const radius = Math.sqrt(random()) * GALAXY_RADIUS * 1.03;
      const angle = random() * TAU;
      const inner = Math.exp(-radius / (GALAXY_RADIUS * 0.35));
      const color = colorBetween(BLUE, WARM, inner);
      append(stars,
        Math.cos(angle) * radius, Math.sin(angle) * radius,
        gaussian(random) * (7 + inner * 13) * scale,
        color, (0.8 + random() ** 4 * 2.3) * scale,
        0.13 + random() * 0.22, random());
    }

    // A sparse volume of distant stars provides parallax without enclosing a globe.
    for (let i = 0; i < 2000; i++) {
      const distance = (1.5 + random() * 4.3) * GALAXY_RADIUS;
      const azimuth = random() * TAU;
      const vertical = random() * 2 - 1;
      const ring = Math.sqrt(1 - vertical * vertical);
      const bright = random();
      const color = colorBetween(PALE_BLUE, IVORY, random());
      append(stars,
        Math.cos(azimuth) * ring * distance,
        Math.sin(azimuth) * ring * distance,
        vertical * distance,
        color, (1.6 + bright ** 6 * 4.5) * scale,
        0.12 + bright * 0.5, random());
    }

    // Low-alpha, soft clouds connect the fine stars into a continuous galaxy.
    for (let i = 0; i < 3000; i++) {
      const arm = i % armCount;
      const progress = random();
      const center = galaxyArmPoint(arm, armCount, progress);
      const angle = Math.atan2(center.y, center.x);
      const spread = gaussian(random) * (12 + progress * 21) * scale;
      const color = progress < 0.25
        ? colorBetween(WARM, BLUE, progress / 0.25)
        : colorBetween(BLUE, PALE_BLUE, random() * 0.25);
      const filament = 0.30 + 0.70 * Math.sin(progress * 41 + arm * 2.1) ** 2;
      append(mist,
        center.x + Math.cos(angle) * spread,
        center.y + Math.sin(angle) * spread,
        center.z + gaussian(random) * 3 * scale,
        color, (35 + random() * 60 + progress * 25) * scale,
        (0.025 + random() * 0.030) * filament, random());
    }
    for (let i = 0; i < 1000; i++) {
      const radius = Math.min(155, -Math.log(Math.max(0.00001, random())) * 39);
      const angle = random() * TAU;
      append(mist,
        Math.cos(angle) * radius * scale,
        Math.sin(angle) * radius * 0.90 * scale,
        gaussian(random) * 10 * scale,
        colorBetween(IVORY, WARM, Math.min(1, radius / 55)),
        (25 + random() * 52) * scale, 0.017 + random() * 0.022, random());
    }

    group.add(makeLayer(mist, true, projectionSize), makeLayer(stars, false, projectionSize));
    for (const layer of group.children) layer.material.uniforms.uIntensity.value = intensity;
    group.userData.particleCount = stars.size.length + mist.size.length;
    group.userData.armCount = armCount;
    lastArmCount = armCount;
  }

  const api = {
    update(nodes = []) {
      if (disposed) return api;
      const roots = nodes.filter(node => (node.isFederationHub || node.federationHub) && node.spaceId !== 'central'
        && (node.parentSpaceId === 'central' || node.spaceDepth === 1));
      const armCount = Math.max(1, roots.length || 4);
      if (armCount !== lastArmCount) rebuild(armCount);
      return api;
    },
    setTheme(theme) {
      if (disposed) return api;
      const dark = typeof theme === 'string' ? theme !== 'light' : theme?.dark !== false;
      // The enclosing graph keeps its astronomical backdrop in either UI theme.
      intensity = dark ? 1 : 0.88;
      for (const layer of group.children) layer.material.uniforms.uIntensity.value = intensity;
      return api;
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      releaseLayers();
      group.removeFromParent();
    },
  };
  api.update();
  return api;
}
