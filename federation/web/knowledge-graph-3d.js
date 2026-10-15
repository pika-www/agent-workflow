/* Local 3d-force-graph / Three.js adapter. OpenWiki owns data and selection. */
import ForceGraph3D from '3d-force-graph';
import * as THREE from 'three';
import { createGalaxyEnvironment } from './galaxy-environment.js';
import { GALAXY_RADIUS } from './hierarchy-layout.js';

const FONT = '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif';
const finite = (value, fallback = 0) => Number.isFinite(value) ? value : fallback;
const endpoint = value => typeof value === 'object' ? value : null;

function roundedRect(ctx, x, y, width, height, radius) {
  ctx.beginPath();
  ctx.moveTo(x + radius, y);
  ctx.arcTo(x + width, y, x + width, y + height, radius);
  ctx.arcTo(x + width, y + height, x, y + height, radius);
  ctx.arcTo(x, y + height, x, y, radius);
  ctx.arcTo(x, y, x + width, y, radius);
  ctx.closePath();
}

function labelTexture(node, theme, selected) {
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');
  const title = String(node.title || node.id);
  const chars = Array.from(title);
  const lines = chars.length > 18 ? [chars.slice(0, 18).join(''), chars.slice(18, 34).join('') + (chars.length > 34 ? '…' : '')] : [title];
  const fontSize = node.spaceId === 'central' ? 29 : 26;
  const font = `${selected || node.spaceDepth < 2 ? 650 : 500} ${fontSize}px ${FONT}`;
  ctx.font = font;
  const width = Math.ceil(Math.max(...lines.map(line => ctx.measureText(line).width)) + 26);
  const height = lines.length * 35 + 13;
  canvas.width = width * 2;
  canvas.height = height * 2;
  ctx.scale(2, 2);
  ctx.font = font;
  roundedRect(ctx, 1, 1, width - 2, height - 2, 10);
  ctx.fillStyle = theme.dark ? 'rgba(3, 8, 20, .64)' : 'rgba(251, 252, 253, .91)';
  ctx.fill();
  if (selected) {
    ctx.strokeStyle = theme.accent;
    ctx.lineWidth = 1.5;
    ctx.stroke();
  }
  ctx.fillStyle = selected ? (theme.dark ? '#ffffff' : '#17252c') : theme.text;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  lines.forEach((line, i) => ctx.fillText(line, width / 2, 24 + i * 35));
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.minFilter = THREE.LinearFilter;
  texture.generateMipmaps = false;
  return { texture, width, height };
}

function glowTexture() {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 128;
  const ctx = canvas.getContext('2d');
  const gradient = ctx.createRadialGradient(64, 64, 6, 64, 64, 64);
  gradient.addColorStop(0, 'rgba(255,255,255,.65)');
  gradient.addColorStop(.4, 'rgba(255,255,255,.21)');
  gradient.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, 128, 128);
  return new THREE.CanvasTexture(canvas);
}

/** Disposes only resources owned by this adapter, never the graph's resources. */
function disposeNode(entry) {
  entry.group.removeFromParent();
  entry.sphere.geometry.dispose();
  entry.sphere.material.dispose();
  entry.halo.material.dispose();
  entry.label.material.map?.dispose();
  entry.label.material.dispose();
  entry.orbits.forEach(ring => { ring.geometry.dispose(); ring.material.dispose(); });
}

export function createKnowledgeGraph3D(container, options = {}) {
  const { onNodeClick = () => {}, onNodeHover = () => {}, getTheme = () => ({}),
    isSelected = () => false, isHighlighted = () => false,
    isLinkHighlighted = () => false, isDimmed = () => false } = options;
  const objects = new Map();
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  let graph = null;
  let galaxy = null;
  let data = { nodes: [], links: [] };
  let disposed = false;
  let contextLost = false;
  let manuallyPaused = false;
  let observatoryHidden = document.body.classList.contains('ob-active') && !document.body.classList.contains('ob-native');
  let pendingFit = null;
  let spinning = false;
  let firstFrame = null;
  let theme = {};
  let background = null;
  let sharedGlow = null;
  let size = { width: Math.max(container.clientWidth, 1), height: Math.max(container.clientHeight, 1) };
  let observer = null;
  let expanded = false;
  const main = container.closest('#main');
  const graphToggle = document.getElementById('toggle-graph');

  container.classList.add('kg3d');
  const surface = document.createElement('div');
  surface.className = 'kg3d-surface';
  surface.setAttribute('aria-label', '智能体星系：银心是中央 Agent，旋臂承载行业与专业；也可通过左侧目录选择知识库');
  const controlsBar = document.createElement('div');
  controlsBar.className = 'kg3d-controls';
  controlsBar.setAttribute('aria-label', '三维图谱控制');
  controlsBar.innerHTML = '<span class="kg3d-badge"><svg viewBox="0 0 20 20" aria-hidden="true"><ellipse cx="10" cy="10" rx="8" ry="4" transform="rotate(-30 10 10)"/><circle cx="10" cy="10" r="2"/></svg>智能体星系</span>';
  const reset = document.createElement('button');
  reset.className = 'kg3d-button';
  reset.type = 'button';
  reset.textContent = '重置视角';
  reset.title = '恢复初始角度并显示全部节点';
  const rotate = document.createElement('button');
  rotate.className = 'kg3d-button';
  rotate.type = 'button';
  rotate.textContent = '自动旋转';
  rotate.setAttribute('aria-pressed', 'false');
  rotate.title = '缓慢环绕查看知识库分支';
  const panorama = document.createElement('button');
  panorama.className = 'kg3d-button';
  panorama.type = 'button';
  panorama.textContent = '星系全景';
  panorama.title = '展开整个星系；点击 Agent 后返回知识阅读区';
  panorama.setAttribute('aria-pressed', 'false');
  controlsBar.append(reset, rotate, panorama);
  const hint = document.createElement('div');
  hint.className = 'kg3d-hint';
  hint.textContent = '拖动环绕 · 滚轮缩放 · 点击星点阅读';
  const caption = document.createElement('div');
  caption.className = 'kg3d-galaxy-caption';
  caption.innerHTML = '<span>AGENT GALAXY</span><strong>中央银心 · 行业旋臂 · 专业星点</strong>';
  container.append(surface, controlsBar, hint, caption);

  const readTheme = () => {
    theme = {
      // Space stays dark while OpenWiki's reading panels retain their theme.
      dark: true,
      bg: '#02040b',
      text: '#d4e3fa',
      edge: '#30476d',
      accent: '#a8cfff',
    };
  };

  const setSpinning = value => {
    spinning = Boolean(value) && Boolean(graph);
    if (graph) graph.controls().autoRotate = spinning;
    rotate.setAttribute('aria-pressed', String(spinning));
    rotate.textContent = spinning ? '暂停旋转' : '自动旋转';
  };

  const fitToView = (duration = 650) => {
    if (!graph || !data.nodes.length || disposed) return api;
    // Initial data can arrive while the observatory home hides the whole graph.
    // Wait for real dimensions instead of fitting the galaxy into a 1px canvas.
    if (!container.clientWidth || !container.clientHeight) {
      pendingFit = duration;
      return api;
    }
    pendingFit = null;
    setSpinning(false);
    // Keep the galactic centre fixed even as branches are added or removed.
    const center = new THREE.Vector3();
    const direction = new THREE.Vector3(.18, -.96, 1).normalize();
    const forward = direction.clone().negate();
    const right = forward.clone().cross(new THREE.Vector3(0, 1, 0)).normalize();
    const up = right.clone().cross(forward).normalize();
    const camera = graph.camera();
    const tanY = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
    const tanX = tanY * Math.max(.1, size.width / size.height);
    let distance = 250;
    // Fit labels and nodes in camera space; narrow split panels need extra room.
    for (const node of data.nodes) {
      const local = new THREE.Vector3(finite(node.x, finite(node.fx)), finite(node.y, finite(node.fy)), finite(node.z, finite(node.fz))).sub(center);
      const label = objects.get(node.id)?.label;
      const padX = Math.max(finite(node.r, 8) + 18, (label?.scale.x || 60) / 2 + 8);
      const padY = finite(node.r, 8) + 40;
      const depth = local.dot(direction);
      distance = Math.max(distance, depth + (Math.abs(local.dot(right)) + padX) / tanX,
        depth + (Math.abs(local.dot(up)) + padY) / tanY);
    }
    for (let index = 0; index < 32; index++) {
      const angle = index * Math.PI / 16;
      const rim = new THREE.Vector3(Math.cos(angle) * GALAXY_RADIUS * 1.08, Math.sin(angle) * GALAXY_RADIUS * 1.08, 0);
      distance = Math.max(distance, rim.dot(direction) + (Math.abs(rim.dot(right)) + 25) / tanX,
        rim.dot(direction) + (Math.abs(rim.dot(up)) + 30) / tanY);
    }
    const position = center.clone().addScaledVector(direction, distance * 1.04);
    camera.near = .5;
    camera.far = Math.max(15000, distance * 20);
    camera.updateProjectionMatrix();
    graph.controls().maxDistance = Math.max(5000, distance * 5);
    graph.cameraPosition(position, center, reduceMotion.matches ? 0 : Math.max(0, finite(duration)));
    return api;
  };

  function nodeObject(node) {
    let entry = objects.get(node.id);
    if (!entry) {
      const group = new THREE.Group();
      const sphere = new THREE.Mesh(new THREE.SphereGeometry(1, 20, 16), new THREE.MeshBasicMaterial({
        transparent: true, toneMapped: false,
      }));
      const halo = new THREE.Sprite(new THREE.SpriteMaterial({ map: sharedGlow, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, toneMapped: false }));
      // The soft glow is decorative; its transparent square must not catch clicks.
      halo.raycast = () => {};
      const label = new THREE.Sprite(new THREE.SpriteMaterial({ transparent: true, depthTest: false, depthWrite: false, toneMapped: false }));
      const orbits = [];
      group.add(halo, sphere, label);
      entry = { group, sphere, halo, label, orbits, labelKey: null, node };
      objects.set(node.id, entry);
    }
    entry.node = node;
    updateNode(entry);
    return entry.group;
  }

  function updateNode(entry) {
    const { node, sphere, halo, label, orbits } = entry;
    const selected = isSelected(node);
    const hot = isHighlighted(node);
    const dim = isDimmed(node);
    const central = node.spaceId === 'central';
    const industry = node.federationHub && node.spaceDepth === 1;
    const radius = central ? 8 : industry ? 5 : node.federationHub ? 3 : 1.7;
    const color = central ? '#ffe3ac' : industry ? '#c1d6ff' : '#90c9ff';
    const material = sphere.material;
    material.color.set(selected ? '#fff4dc' : color);
    material.opacity = dim ? .15 : 1;
    sphere.scale.setScalar(radius * (selected ? 1.3 : 1));
    halo.material.color.set(color);
    halo.material.opacity = dim ? 0 : selected ? .95 : hot ? .7 : .5;
    halo.scale.setScalar(radius * (central ? 16 : selected ? 10 : 7));
    orbits.forEach((ring, index) => {
      ring.scale.setScalar(radius * (1.65 + index * .3));
      ring.material.color.set(theme.accent);
      ring.material.opacity = dim ? .03 : selected ? .4 : .22;
    });
    const key = JSON.stringify([node.title, node.spaceId, node.spaceDepth, theme.text, theme.accent, theme.dark, selected]);
    if (entry.labelKey !== key) {
      const next = labelTexture(node, theme, selected);
      label.material.map?.dispose();
      label.material.map = next.texture;
      label.material.needsUpdate = true;
      const scale = central ? .58 : .51;
      label.scale.set(next.width * scale, next.height * scale, 1);
      entry.labelKey = key;
    }
    label.position.set(0, -radius - label.scale.y / 2 - 7, 0);
    label.visible = Boolean(node.federationHub || node.isFederationHub || selected || hot);
    label.material.opacity = dim ? .2 : 1;
    label.renderOrder = selected ? 30 : hot ? 20 : 10;
  }

  const linkDimmed = link => {
    const source = endpoint(link.source), target = endpoint(link.target);
    return Boolean((source && isDimmed(source)) || (target && isDimmed(target)));
  };
  const linkColor = link => linkDimmed(link) ? '#0a142a' : isLinkHighlighted(link) ? '#9dbfe8' : '#253956';
  const linkWidth = link => linkDimmed(link) ? .05 : isLinkHighlighted(link) ? .55 : .08;

  const refreshPresentation = () => {
    if (disposed) return api;
    readTheme();
    objects.forEach(updateNode);
    if (graph) {
      graph.backgroundColor(theme.bg);
      // Accessor invalidation updates links without re-creating node objects.
      graph.linkColor(linkColor).linkWidth(linkWidth);
    }
    galaxy?.setTheme(theme);
    return api;
  };

  const resize = () => {
    if (disposed || !graph || contextLost) return;
    const width = container.clientWidth;
    const height = container.clientHeight;
    // Preserve the last useful dimensions while a parent is display:none.
    if (!width || !height) return;
    if (size.width !== width || size.height !== height) {
      size = { width, height };
      graph.width(width).height(height);
    }
    if (pendingFit !== null) fitToView(pendingFit);
  };

  const setExpanded = value => {
    expanded = Boolean(value);
    main?.classList.toggle('galaxy-panorama', expanded);
    panorama.textContent = expanded ? '退出全景' : '星系全景';
    panorama.setAttribute('aria-pressed', String(expanded));
    resize();
    fitToView(0);
  };

  function showUnavailable(message) {
    setSpinning(false);
    reset.disabled = rotate.disabled = panorama.disabled = true;
    hint.hidden = true;
    const notice = document.createElement('div');
    notice.className = 'kg3d-unavailable';
    notice.setAttribute('role', 'status');
    const title = document.createElement('strong');
    title.textContent = '三维图谱暂时无法显示';
    const detail = document.createElement('span');
    detail.textContent = message;
    const help = document.createElement('span');
    help.textContent = '你仍可通过左侧目录阅读知识库、使用 Agent 聊天。';
    notice.append(title, detail, help);
    surface.append(notice);
  }

  const api = {
    graphData(next) {
      if (!arguments.length) return data;
      if (disposed) return api;
      data = next;
      const agents = next.nodes.filter(node => node.federationHub || node.isFederationHub);
      const industries = agents.filter(node => node.spaceDepth === 1);
      caption.querySelector('strong').textContent = `${agents.length} 位 Agent · ${industries.length} 条行业旋臂 · 点击命名星点阅读`;
      const ids = new Set(next.nodes.map(node => node.id));
      for (const [id, entry] of objects) if (!ids.has(id)) {
        disposeNode(entry);
        objects.delete(id);
      }
      // Positions are supplied by the deterministic hierarchy layout.
      for (const node of next.nodes) {
        node.x = finite(node.fx, finite(node.x));
        node.y = finite(node.fy, finite(node.y));
        node.z = finite(node.fz, finite(node.z));
        node.fx = node.x; node.fy = node.y; node.fz = node.z;
        if (objects.has(node.id)) objects.get(node.id).node = node;
      }
      // OpenWiki selects the initial reader immediately after graphData().
      // Resolve endpoints now instead of waiting for the library's next frame.
      const byId = new Map(next.nodes.map(node => [node.id, node]));
      next.links.forEach(link => {
        link.source = byId.get(typeof link.source === 'object' ? link.source.id : link.source);
        link.target = byId.get(typeof link.target === 'object' ? link.target.id : link.target);
      });
      if (graph) graph.graphData(next);
      galaxy?.update(next.nodes);
      return refreshPresentation();
    },
    backgroundColor(value) {
      if (!arguments.length) return theme.bg;
      background = value;
      return refreshPresentation();
    },
    width(value) {
      if (!arguments.length) return size.width;
      size.width = Math.max(1, finite(value, 1));
      graph?.width(size.width);
      return api;
    },
    height(value) {
      if (!arguments.length) return size.height;
      size.height = Math.max(1, finite(value, 1));
      graph?.height(size.height);
      return api;
    },
    pauseAnimation() { manuallyPaused = true; graph?.pauseAnimation(); return api; },
    resumeAnimation() { manuallyPaused = false; syncAnimation(); return api; },
    fitToView,
    refreshPresentation,
    dispose() {
      if (disposed) return;
      disposed = true;
      observer?.disconnect();
      cancelAnimationFrame(firstFrame);
      surface.removeEventListener('pointerdown', stopOnInteraction);
      surface.removeEventListener('wheel', stopOnInteraction);
      document.removeEventListener('visibilitychange', visibilityChanged);
      document.removeEventListener('observatory:view', observatoryViewChanged);
      document.removeEventListener('keydown', exitPanorama);
      graphToggle?.removeEventListener('click', exitBeforeCollapse, true);
      const renderer = graph?.renderer();
      renderer?.domElement.removeEventListener('webglcontextlost', contextLostHandler);
      graph?.pauseAnimation();
      graph?.controls().dispose();
      graph?._destructor?.();
      galaxy?.dispose();
      objects.forEach(disposeNode);
      objects.clear();
      sharedGlow?.dispose();
      renderer?.dispose();
      renderer?.forceContextLoss();
      controlsBar.remove(); hint.remove(); caption.remove(); surface.remove();
      main?.classList.remove('galaxy-panorama');
      container.classList.remove('kg3d');
      graph = null;
    },
  };

  const stopOnInteraction = () => { if (spinning) setSpinning(false); };
  const syncAnimation = () => {
    if (!graph || disposed) return;
    if (document.hidden || observatoryHidden || contextLost || manuallyPaused) {
      graph.pauseAnimation();
    } else {
      resize();
      graph.resumeAnimation();
    }
  };
  const visibilityChanged = () => syncAnimation();
  const observatoryViewChanged = event => {
    if (typeof event.detail?.view !== 'string') return;
    observatoryHidden = event.detail.view !== 'atlas';
    syncAnimation();
  };
  const contextLostHandler = event => {
    if (disposed) return;
    event.preventDefault();
    contextLost = true;
    syncAnimation();
    showUnavailable('浏览器的图形加速已中断，刷新页面可重新尝试。');
  };
  const exitPanorama = event => {
    if (event.key === 'Escape' && expanded && !document.querySelector('dialog[open]')) setExpanded(false);
  };
  // Restore the reading columns before OpenWiki applies its graph-hide control.
  const exitBeforeCollapse = () => { if (expanded) setExpanded(false); };
  reset.addEventListener('click', () => fitToView());
  rotate.addEventListener('click', () => setSpinning(!spinning));
  panorama.addEventListener('click', () => setExpanded(!expanded));
  surface.addEventListener('pointerdown', stopOnInteraction, { passive: true });
  surface.addEventListener('wheel', stopOnInteraction, { passive: true });
  document.addEventListener('visibilitychange', visibilityChanged);
  document.addEventListener('observatory:view', observatoryViewChanged);
  document.addEventListener('keydown', exitPanorama);
  graphToggle?.addEventListener('click', exitBeforeCollapse, true);

  readTheme();
  try {
    graph = new ForceGraph3D(surface, { controlType: 'orbit', rendererConfig: { antialias: true, alpha: false, powerPreference: 'high-performance' } })
      .width(size.width).height(size.height).backgroundColor(theme.bg)
      .showNavInfo(false).enableNodeDrag(false).numDimensions(3)
      .nodeThreeObject(nodeObject).nodeLabel(() => '')
      .linkColor(linkColor).linkWidth(linkWidth).linkOpacity(.34).linkResolution(6).linkCurvature(.2)
      .cooldownTicks(0)
      .onNodeClick((node, event) => { if (expanded) setExpanded(false); onNodeClick(node, event); refreshPresentation(); })
      .onNodeHover(node => {
        surface.style.cursor = node ? 'pointer' : 'grab';
        onNodeHover(node);
        refreshPresentation();
      });
    sharedGlow = glowTexture();
    galaxy = createGalaxyEnvironment(graph.scene());
    const keyLight = new THREE.DirectionalLight('#e6f4ff', 2.5);
    keyLight.position.set(-180, 240, 400);
    const rimLight = new THREE.DirectionalLight('#91adc8', 1.1);
    rimLight.position.set(180, -50, -240);
    graph.lights([new THREE.AmbientLight('#ffffff', 1.1), keyLight, rimLight]);
    const orbit = graph.controls();
    orbit.enableDamping = true;
    orbit.dampingFactor = .12;
    orbit.rotateSpeed = .55;
    orbit.zoomSpeed = .75;
    orbit.panSpeed = .6;
    orbit.screenSpacePanning = true;
    orbit.minDistance = 65;
    orbit.maxDistance = 6000;
    orbit.autoRotate = false;
    orbit.autoRotateSpeed = .35;
    const renderer = graph.renderer();
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.1;
    renderer.domElement.addEventListener('webglcontextlost', contextLostHandler, { once: true });
    observer = new ResizeObserver(resize);
    observer.observe(container);
    firstFrame = requestAnimationFrame(resize);
    syncAnimation();
  } catch (error) {
    graph?.pauseAnimation();
    graph = null;
    surface.replaceChildren();
    const unavailable = /webgl|context|gpu/i.test(String(error?.message || error));
    showUnavailable(unavailable
      ? '浏览器未能初始化 WebGL 图形加速，请检查硬件加速后刷新。'
      : '星系渲染初始化未完成，请刷新页面重试。');
    console.warn('OpenWiki 3D graph unavailable:', error);
  }
  return api;
}
