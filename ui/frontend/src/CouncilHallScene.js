import * as THREE from "three";
    import { OrbitControls } from "three/addons/controls/OrbitControls.js";
    import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
    import { MeshoptDecoder } from "three/addons/libs/meshopt_decoder.module.js";

    export const COUNCIL_ROLE_MODEL_URLS = [
      "/livehall-assets/models/villager.glb",
      "/livehall-assets/models/werewolf.glb",
      "/livehall-assets/models/white-wolf-king.glb",
      "/livehall-assets/models/nvwu.glb",
      "/livehall-assets/models/guard.glb",
      "/livehall-assets/models/seer.glb",
      "/livehall-assets/models/hunter.glb"
    ];

    const sharedModelCache = new Map();

    function createCouncilGltfLoader() {
      const loader = new GLTFLoader();
      loader.setMeshoptDecoder(MeshoptDecoder);
      return loader;
    }

    function loadSharedCouncilModel(file, loaderFactory = createCouncilGltfLoader) {
      if (!file) return Promise.reject(new Error("Missing model file"));
      if (sharedModelCache.has(file)) return sharedModelCache.get(file);
      const loader = loaderFactory();
      const promise = loader.loadAsync(file)
        .then((gltf) => gltf.scene)
        .catch((error) => {
          sharedModelCache.delete(file);
          throw error;
        });
      sharedModelCache.set(file, promise);
      return promise;
    }

    export function preloadCouncilRoleModels(urls = COUNCIL_ROLE_MODEL_URLS) {
      THREE.Cache.enabled = true;
      if (typeof window === "undefined") return Promise.resolve();
      const uniqueUrls = [...new Set(urls.filter(Boolean))];
      return Promise.allSettled(uniqueUrls.map((file) => loadSharedCouncilModel(file))).then(() => {});
    }

    export function createCouncilHallScene(container) {
    THREE.Cache.enabled = true;
    const app = container;
    const loading = { style: {}, remove() {} };
    let animationFrameId = 0;
    let slowFrameTimer = 0;
    let sceneDisposed = false;
    let loadProgressHandler = null;
    let modelLoadTotal = 0;
    let modelLoadLoaded = 0;
    const trackedTimeouts = new Set();
    const trackedIdleCallbacks = new Set();
    const loadProgress = {
      phase: "scene",
      label: "搭建议事厅",
      loaded: 0,
      total: 1,
      progress: 0.08,
      ready: false
    };

    function setTrackedTimeout(callback, delay = 0) {
      const timer = window.setTimeout(() => {
        trackedTimeouts.delete(timer);
        callback();
      }, delay);
      trackedTimeouts.add(timer);
      return timer;
    }

    function clearTrackedTimeout(timer) {
      if (!timer) return;
      window.clearTimeout(timer);
      trackedTimeouts.delete(timer);
    }

    function requestTrackedIdleCallback(callback) {
      if (typeof window.requestIdleCallback === "function") {
        const id = window.requestIdleCallback((deadline) => {
          trackedIdleCallbacks.delete(id);
          callback(deadline);
        });
        trackedIdleCallbacks.add(id);
        return { type: "idle", id };
      }
      return { type: "timeout", id: setTrackedTimeout(callback, 0) };
    }

    function clearTrackedIdleCallback(handle) {
      if (!handle?.id) return;
      if (handle.type === "idle") {
        window.cancelIdleCallback?.(handle.id);
        trackedIdleCallbacks.delete(handle.id);
        return;
      }
      clearTrackedTimeout(handle.id);
    }

    function clearTrackedTimers() {
      trackedTimeouts.forEach((timer) => window.clearTimeout(timer));
      trackedTimeouts.clear();
      trackedIdleCallbacks.forEach((id) => window.cancelIdleCallback?.(id));
      trackedIdleCallbacks.clear();
    }

    function emitLoadProgress(patch = {}) {
      Object.assign(loadProgress, patch);
      loadProgress.loaded = Math.max(0, Number(loadProgress.loaded) || 0);
      loadProgress.total = Math.max(1, Number(loadProgress.total) || 1);
      loadProgress.progress = THREE.MathUtils.clamp(Number(loadProgress.progress) || 0, 0, 1);
      loadProgressHandler?.({ ...loadProgress });
    }

    function reportModelLoadProgress(label = "加载角色模型") {
      const total = Math.max(1, modelLoadTotal);
      const loaded = Math.min(modelLoadLoaded, total);
      emitLoadProgress({
        phase: "models",
        label: modelLoadTotal ? `${label} ${loaded}/${modelLoadTotal}` : "角色模型就绪",
        loaded,
        total,
        progress: modelLoadTotal ? 0.38 + (loaded / total) * 0.5 : 0.88,
        ready: false
      });
    }

    function resetModelLoadProgress(total = 0) {
      modelLoadTotal = Math.max(0, Number(total) || 0);
      modelLoadLoaded = 0;
      emitLoadProgress({
        phase: modelLoadTotal ? "models" : "scene",
        label: modelLoadTotal ? `准备角色模型 0/${modelLoadTotal}` : "搭建议事厅",
        loaded: 0,
        total: Math.max(1, modelLoadTotal),
        progress: modelLoadTotal ? 0.28 : 0.16,
        ready: false
      });
    }

    function markStandeeModelLoaded(standee) {
      if (!standee?.userData?.modelRequired || standee.userData.modelProgressReported) return;
      standee.userData.modelProgressReported = true;
      modelLoadLoaded += 1;
      reportModelLoadProgress();
    }

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x010104);
    scene.fog = new THREE.FogExp2(0x05040a, 0.028);

    const camera = new THREE.PerspectiveCamera(
      50,
      app.clientWidth / app.clientHeight,
      0.1,
      200
    );
    camera.position.set(0, 3.08, 7.2);

    const renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: false,
      powerPreference: "high-performance"
    });
    const MAX_RENDER_PIXEL_RATIO = 1.15;
    const MAX_TEXTURE_ANISOTROPY = Math.min(4, renderer.capabilities.getMaxAnisotropy?.() || 1);
    function applyRendererSize(width, height) {
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, MAX_RENDER_PIXEL_RATIO));
      renderer.setSize(width, height);
    }
    applyRendererSize(app.clientWidth, app.clientHeight);
    renderer.shadowMap.enabled = false;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.32;
    app.appendChild(renderer.domElement);
    const bubbleLayer = document.createElement("div");
    bubbleLayer.className = "scene-bubble-layer";
    document.body.appendChild(bubbleLayer);
    const sceneEventLayer = document.createElement("div");
    sceneEventLayer.className = "scene-event-layer";
    document.body.appendChild(sceneEventLayer);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0, 2.05, -5.35);
    controls.enableRotate = false;
    controls.enableZoom = false;
    controls.enablePan = false;
    controls.enableDamping = true;
    controls.dampingFactor = 0.06;
    controls.minDistance = 6;
    controls.maxDistance = 22;
    controls.maxPolarAngle = Math.PI * 0.49;
    controls.update();

    const clock = new THREE.Clock();

    // ── Render state (declared early so markDirty is available to all init code) ──
    let needsRender = true;
    let lastSlowAnimTime = 0;
    const SLOW_ANIM_INTERVAL = 100;
    let cachedBubblePositions = null;
    let idleFrameCount = 0;
    const IDLE_STOP_THRESHOLD = 90;
    let hasAmbientAnimation = false;
    const _prevCamPos = new THREE.Vector3();
    const _prevCamQuat = new THREE.Quaternion();

    function markDirty() {
      if (sceneDisposed) return;
      needsRender = true;
      cachedBubblePositions = null;
      idleFrameCount = 0;
      if (slowFrameTimer) {
        clearTrackedTimeout(slowFrameTimer);
        slowFrameTimer = 0;
      }
      if (!animationFrameId) {
        animationFrameId = requestAnimationFrame(renderFrame);
      }
    }

    function scheduleRenderFrame(delay = 0) {
      if (sceneDisposed || animationFrameId || slowFrameTimer) return;
      if (delay > 0) {
        slowFrameTimer = setTrackedTimeout(() => {
          slowFrameTimer = 0;
          if (!sceneDisposed && !animationFrameId) {
            animationFrameId = requestAnimationFrame(renderFrame);
          }
        }, delay);
        return;
      }
      animationFrameId = requestAnimationFrame(renderFrame);
    }

    function checkCameraMoved() {
      if (!camera.position.equals(_prevCamPos) || !camera.quaternion.equals(_prevCamQuat)) {
        _prevCamPos.copy(camera.position);
        _prevCamQuat.copy(camera.quaternion);
        return true;
      }
      return false;
    }

    function updateBubblePositions() {
      if (cachedBubblePositions) return;
      cachedBubblePositions = true;
      const viewport = app.getBoundingClientRect();
      const clampBubblePosition = (element, x, y, { minWidth = 220, minHeight = 76 } = {}) => {
        const width = Math.max(minWidth, element.offsetWidth || minWidth);
        const height = Math.max(minHeight, element.offsetHeight || minHeight);
        const safeX = THREE.MathUtils.clamp(x, width / 2 + 18, window.innerWidth - width / 2 - 18);
        const safeY = THREE.MathUtils.clamp(y, height + 18, window.innerHeight - 18);
        return { x: safeX, y: safeY };
      };
      playerStandeeGroup.children.forEach((standee) => {
        const bubble = standee.userData.bubble;
        const voteBadge = standee.userData.voteBadge;
        if (!bubble && !voteBadge) return;
        const pos = new THREE.Vector3();
        standee.getWorldPosition(pos);
        if (bubble) {
          const bubblePos = pos.clone();
          bubblePos.y += 2.54 * standee.scale.y;
          bubblePos.project(camera);
          const x = viewport.left + (bubblePos.x * 0.5 + 0.5) * viewport.width;
          const y = viewport.top + (-bubblePos.y * 0.5 + 0.5) * viewport.height;
          const safe = clampBubblePosition(bubble, x, y);
          const hasSpeech = bubble.classList.contains("speaking") || Boolean(standee.userData.speechText?.textContent);
          bubble.classList.toggle("hidden", standee.userData.dead === true || (!standee.visible && !hasSpeech));
          bubble.style.transform = `translate(-50%, -100%) translate(${safe.x}px, ${safe.y}px)`;
        }
        if (voteBadge) {
          const votePos = pos.clone();
          votePos.y += 2.82 * standee.scale.y;
          votePos.project(camera);
          const vx = viewport.left + (votePos.x * 0.5 + 0.5) * viewport.width;
          const vy = viewport.top + (-votePos.y * 0.5 + 0.5) * viewport.height;
          const safe = clampBubblePosition(voteBadge, vx, vy, { minWidth: 120, minHeight: 48 });
          voteBadge.style.transform = `translate(-50%, -100%) translate(${safe.x}px, ${safe.y}px)`;
        }
      });
      activeSceneEffects.forEach(updateSceneEffectOverlayPosition);
    }

    const textureLoader = new THREE.TextureLoader();
    const gltfLoader = new GLTFLoader();
    gltfLoader.setMeshoptDecoder(MeshoptDecoder);

    let seatCardImage = null;
    const seatNumberPlates = []; // track all plate meshes for texture refresh
    textureLoader.load('/seat-card-bg.png', (tex) => {
      seatCardImage = tex.image;
      // Regenerate textures for all existing seat number plates
      for (const { mesh, label } of seatNumberPlates) {
        const oldMap = mesh.material.map;
        const newTex = makeSeatNumberTexture(label);
        mesh.material.map = newTex;
        mesh.material.needsUpdate = true;
        oldMap?.dispose?.();
      }
    });

    const POSTERS = [
      { name: "野孩子", file: "/livehall-assets/posters/01-yehaizi.png", fallback: "witch", angle: -78, accent: "#ff45d8", bgA: "#68134e", bgB: "#160411" },
      { name: "猎人", file: "/livehall-assets/posters/02-hunter.png", fallback: "hunter", angle: -56, accent: "#ff9a48", bgA: "#6b3518", bgB: "#14090a" },
      { name: "守卫", file: "/livehall-assets/posters/03-guard.png", fallback: "guard", angle: -34, accent: "#ffc04d", bgA: "#694420", bgB: "#110908" },
      { name: "预言家", file: "/livehall-assets/posters/04-seer.png", fallback: "seer", angle: -12, accent: "#7ab1ff", bgA: "#1e1b56", bgB: "#05040b" },
      { name: "法官", file: "/livehall-assets/posters/05-judge.png", fallback: "judge", angle: 12, accent: "#ffd196", bgA: "#704f23", bgB: "#110907" },
      { name: "狼人", file: "/livehall-assets/posters/06-wolf.png", fallback: "wolf", angle: 34, accent: "#ff405a", bgA: "#651018", bgB: "#120305" },
      { name: "狼王", file: "/livehall-assets/posters/07-wolf-king.png", fallback: "wolfKing", angle: 56, accent: "#ff784a", bgA: "#68120c", bgB: "#150307" },
      { name: "女巫", file: "/livehall-assets/posters/08-witch.png", fallback: "witch", angle: 78, accent: "#ff67d6", bgA: "#5f174e", bgB: "#13040e" }
    ];

    function makeCanvasTexture(draw, width = 1024, height = 1024) {
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;

      const ctx = canvas.getContext("2d");
      draw(ctx, width, height);

      const texture = new THREE.CanvasTexture(canvas);
      texture.colorSpace = THREE.SRGBColorSpace;
      texture.anisotropy = MAX_TEXTURE_ANISOTROPY;
      texture.needsUpdate = true;
      return texture;
    }

    const EFFECT_GLOW_TEXTURE = makeCanvasTexture((ctx, w, h) => {
      const centerX = w / 2;
      const centerY = h / 2;
      const glow = ctx.createRadialGradient(centerX, centerY, 0, centerX, centerY, w * 0.5);
      glow.addColorStop(0, "rgba(255,255,255,1)");
      glow.addColorStop(0.16, "rgba(255,255,255,0.76)");
      glow.addColorStop(0.38, "rgba(255,255,255,0.32)");
      glow.addColorStop(0.72, "rgba(255,255,255,0.08)");
      glow.addColorStop(1, "rgba(255,255,255,0)");
      ctx.fillStyle = glow;
      ctx.fillRect(0, 0, w, h);
    }, 256, 256);

    function makeStarTexture(width = 1024, height = 1024) {
      return makeCanvasTexture((ctx, w, h) => {
        const g = ctx.createRadialGradient(w * 0.5, h * 0.52, 0, w * 0.5, h * 0.52, w * 0.75);
        g.addColorStop(0, "#17132a");
        g.addColorStop(0.42, "#080711");
        g.addColorStop(1, "#020205");
        ctx.fillStyle = g;
        ctx.fillRect(0, 0, w, h);

        for (let i = 0; i < 2200; i++) {
          const x = Math.random() * w;
          const y = Math.random() * h;
          const s = Math.random() * 1.8 + 0.15;
          const a = Math.random() * 0.95;
          ctx.fillStyle = `rgba(255,236,190,${a})`;
          ctx.fillRect(x, y, s, s);
        }

        for (let i = 0; i < 180; i++) {
          const x = Math.random() * w;
          const y = Math.random() * h;
          const r = Math.random() * 22 + 6;
          const glow = ctx.createRadialGradient(x, y, 0, x, y, r);
          glow.addColorStop(0, "rgba(98,75,210,.25)");
          glow.addColorStop(1, "rgba(98,75,210,0)");
          ctx.fillStyle = glow;
          ctx.beginPath();
          ctx.arc(x, y, r, 0, Math.PI * 2);
          ctx.fill();
        }
      }, width, height);
    }

    const starTexture = makeStarTexture();
    const SHARED_TEXTURES = new Set([EFFECT_GLOW_TEXTURE]);

    const MAT_BLACK = new THREE.MeshStandardMaterial({
      color: 0x060607,
      roughness: 0.78,
      metalness: 0.12
    });

    const MAT_DARK = new THREE.MeshStandardMaterial({
      color: 0x121018,
      roughness: 0.82,
      metalness: 0.05
    });

    const MAT_GOLD = new THREE.MeshStandardMaterial({
      color: 0xc79246,
      roughness: 0.34,
      metalness: 0.62
    });

    const MAT_DIM_GOLD = new THREE.MeshStandardMaterial({
      color: 0x8e6334,
      roughness: 0.5,
      metalness: 0.3
    });

    const MAT_WOOD = new THREE.MeshStandardMaterial({
      color: 0x5b2b18,
      roughness: 0.56,
      metalness: 0.08
    });

    const MAT_CHAIR = new THREE.MeshStandardMaterial({
      color: 0x18151b,
      roughness: 0.86,
      metalness: 0.04
    });

    // Shared geometry & material for all player standees (avoids per-standee GPU allocation)
    const SHARED_PLANE_GEO = new THREE.PlaneGeometry(1, 1);
    const SHARED_OUTLINE_MATERIAL = new THREE.MeshBasicMaterial({
      color: 0xdfe8ff,
      transparent: true,
      opacity: 0.2,
      depthWrite: false,
      side: THREE.BackSide,
      toneMapped: false
    });
    const SHARED_FOOT_GEO = new THREE.CylinderGeometry(0.25, 0.34, 0.08, 32);
    const SHARED_FOOT_MAT = new THREE.MeshStandardMaterial({
      color: 0x21130d,
      roughness: 0.42,
      metalness: 0.22
    });
    const SHARED_RING_GEO = new THREE.RingGeometry(0.44, 0.62, 48);
    const SHARED_RING_MAT = new THREE.MeshBasicMaterial({
      color: 0xdfe8ff,
      transparent: true,
      opacity: 0.34,
      depthWrite: false,
      side: THREE.DoubleSide,
      toneMapped: false
    });
    const SHARED_HALO_GEO = new THREE.PlaneGeometry(1.7, 2.05);
    const SHARED_HALO_MAT = new THREE.MeshBasicMaterial({
      color: 0xdfe8ff,
      transparent: true,
      opacity: 0.08,
      depthWrite: false,
      side: THREE.DoubleSide,
      toneMapped: false
    });
    const SHARED_DEAD_MATERIAL = new THREE.MeshBasicMaterial({
      color: 0x020202,
      transparent: false,
      toneMapped: false,
      side: THREE.DoubleSide
    });
    const EFFECT_RING_GEO = new THREE.RingGeometry(0.46, 0.72, 64);
    const EFFECT_DISC_GEO = new THREE.CircleGeometry(0.72, 64);
    const EFFECT_SLASH_GEO = new THREE.PlaneGeometry(0.2, 1.5);
    const EFFECT_SHARD_GEO = new THREE.BoxGeometry(0.035, 0.35, 0.035);
    const EFFECT_ORB_GEO = new THREE.SphereGeometry(0.07, 10, 8);
    const SHARED_GEOMETRIES = new Set([
      SHARED_PLANE_GEO,
      SHARED_FOOT_GEO,
      SHARED_RING_GEO,
      SHARED_HALO_GEO,
      EFFECT_RING_GEO,
      EFFECT_DISC_GEO,
      EFFECT_SLASH_GEO,
      EFFECT_SHARD_GEO,
      EFFECT_ORB_GEO
    ]);
    const SHARED_MATERIALS = new Set([SHARED_OUTLINE_MATERIAL, SHARED_FOOT_MAT, SHARED_RING_MAT, SHARED_HALO_MAT, SHARED_DEAD_MATERIAL]);
    const EFFECT_COLORS = {
      wolf: 0xff2848,
      guarded: 0x8fc7ff,
      save: 0xa8ffb8,
      poison: 0x8d55ff,
      poisonCore: 0x77ff8a,
      vote: 0xffc45c,
      death: 0xff4b3e
    };

    const ambientLight = new THREE.AmbientLight(0x4b3a58, 0.72);
    scene.add(ambientLight);

    const mainLight = new THREE.PointLight(0xffd7a0, 2.85, 22, 1.42);
    mainLight.position.set(0, 5.0, 0);
    mainLight.castShadow = false;
    scene.add(mainLight);

    const frontSpot = new THREE.SpotLight(0xffc27b, 2.25, 32, Math.PI * 0.23, 0.45, 1.1);
    frontSpot.position.set(0, 6.1, 9.4);
    frontSpot.target.position.set(0, 1.2, 0);
    frontSpot.castShadow = false;
    scene.add(frontSpot, frontSpot.target);

    const leftRed = new THREE.PointLight(0xff204f, 1.45, 13, 2.0);
    leftRed.position.set(-6.6, 2.8, 1.4);
    scene.add(leftRed);

    const rightPurple = new THREE.PointLight(0x8e4dff, 1.15, 13, 2.0);
    rightPurple.position.set(6.5, 2.8, 1.4);
    scene.add(rightPurple);

    const backBlue = new THREE.PointLight(0x3764ff, 0.9, 12, 2.1);
    backBlue.position.set(0, 2.7, -6.8);
    scene.add(backBlue);

    const floor = new THREE.Mesh(
      new THREE.CircleGeometry(9.0, 96),
      new THREE.MeshStandardMaterial({
        map: starTexture,
        color: 0x11101a,
        roughness: 0.75,
        metalness: 0.05
      })
    );
    floor.rotation.x = -Math.PI / 2;
    floor.receiveShadow = true;
    scene.add(floor);

    const wall = new THREE.Mesh(
      new THREE.CylinderGeometry(8.55, 8.55, 5.25, 96, 1, true, Math.PI * 0.06, Math.PI * 0.88),
      new THREE.MeshStandardMaterial({
        map: starTexture,
        color: 0x110d16,
        roughness: 0.82,
        metalness: 0.04,
        side: THREE.DoubleSide
      })
    );
    wall.position.y = 2.62;
    wall.rotation.y = Math.PI * 1.03;
    wall.receiveShadow = true;
    scene.add(wall);

    const baseRail = new THREE.Mesh(
      new THREE.CylinderGeometry(8.57, 8.57, 0.28, 96, 1, true, Math.PI * 0.06, Math.PI * 0.88),
      MAT_BLACK
    );
    baseRail.position.y = 0.55;
    baseRail.rotation.y = Math.PI * 1.03;
    scene.add(baseRail);

    const fanBarrier = new THREE.Group();
    scene.add(fanBarrier);

    function addPillarInstance(template, angleDeg) {
      const theta = THREE.MathUtils.degToRad(angleDeg);
      const x = Math.sin(theta) * 7.42;
      const z = -Math.cos(theta) * 7.42;
      const pillar = template.clone(true);
      pillar.position.set(x, 0.08, z);
      pillar.scale.set(3.7, 5.15, 3.7);
      pillar.lookAt(0, pillar.position.y, 0);

      fanBarrier.add(pillar);
    }

    function preparePillarTemplate(template) {
      template.traverse((child) => {
        if (!child.isMesh) return;
        child.castShadow = true;
        child.receiveShadow = true;
        if (child.material) {
          child.material = child.material.clone();
          child.material.emissive = new THREE.Color(0x000000);
          child.material.emissiveIntensity = 0;
          child.material.roughness = 0.5;
          child.material.needsUpdate = true;
        }
      });
    }

    let fanBarrierStarted = false;
    let fanBarrierTimer = null;

    async function createFanBarrier() {
      const [redPillar, bluePillar] = await Promise.all([
        gltfLoader.loadAsync("/livehall-assets/models/red-pillar.glb"),
        gltfLoader.loadAsync("/livehall-assets/models/blue-pillar.glb")
      ]);
      if (sceneDisposed) return;
      const pillarTemplates = [redPillar.scene, bluePillar.scene];
      pillarTemplates.forEach(preparePillarTemplate);

      for (let i = 0; i < 15; i++) {
        if (sceneDisposed) return;
        addPillarInstance(pillarTemplates[i % pillarTemplates.length], -84 + i * (168 / 14));
      }
    }

    function scheduleFanBarrier(delay = 1400) {
      if (sceneDisposed || fanBarrierStarted || fanBarrierTimer) return;
      fanBarrierTimer = setTrackedTimeout(() => {
        fanBarrierTimer = null;
        if (sceneDisposed || fanBarrierStarted) return;
        fanBarrierStarted = true;
        createFanBarrier().then(() => markDirty()).catch(() => {});
      }, delay);
    }

    function makeFallbackPosterTexture(cfg) {
      return makeCanvasTexture((ctx, w, h) => {
        const g = ctx.createLinearGradient(0, 0, 0, h);
        g.addColorStop(0, cfg.bgA);
        g.addColorStop(1, cfg.bgB);
        ctx.fillStyle = g;
        ctx.fillRect(0, 0, w, h);

        for (let i = 0; i < 1200; i++) {
          ctx.globalAlpha = Math.random() * 0.09;
          ctx.fillStyle = "#fff";
          ctx.fillRect(Math.random() * w, Math.random() * h, 2, 2);
        }

        ctx.globalAlpha = 1;
        ctx.strokeStyle = "rgba(255,230,190,.38)";
        ctx.lineWidth = 7;
        ctx.strokeRect(28, 28, w - 56, h - 56);

        const accent = cfg.accent;

        ctx.save();
        ctx.translate(w / 2, h * 0.42);
        ctx.strokeStyle = accent;
        ctx.fillStyle = accent;
        ctx.lineWidth = 10;
        ctx.lineJoin = "round";
        ctx.lineCap = "round";
        ctx.shadowColor = accent;
        ctx.shadowBlur = 22;

        function wolf(crown = false) {
          if (crown) {
            ctx.fillStyle = "#e0a642";
            ctx.beginPath();
            ctx.moveTo(-70, -210);
            ctx.lineTo(-32, -150);
            ctx.lineTo(0, -230);
            ctx.lineTo(32, -150);
            ctx.lineTo(70, -210);
            ctx.lineTo(55, -130);
            ctx.lineTo(-55, -130);
            ctx.closePath();
            ctx.fill();
            ctx.fillStyle = accent;
          }

          ctx.beginPath();
          ctx.moveTo(-150, 0);
          ctx.lineTo(-45, -90);
          ctx.lineTo(25, -160);
          ctx.lineTo(75, -68);
          ctx.lineTo(150, -20);
          ctx.lineTo(88, 32);
          ctx.lineTo(105, 175);
          ctx.lineTo(-35, 120);
          ctx.lineTo(-72, 25);
          ctx.closePath();
          ctx.stroke();

          ctx.beginPath();
          ctx.moveTo(-15, -45);
          ctx.lineTo(48, -62);
          ctx.lineTo(22, -28);
          ctx.stroke();
        }

        function seer() {
          ctx.beginPath();
          ctx.arc(0, -50, 82, 0, Math.PI * 2);
          ctx.stroke();

          ctx.beginPath();
          ctx.moveTo(-88, 48);
          ctx.lineTo(88, 48);
          ctx.lineTo(0, 210);
          ctx.closePath();
          ctx.stroke();

          ctx.beginPath();
          ctx.arc(0, 72, 44, 0, Math.PI * 2);
          ctx.stroke();
        }

        function guard() {
          ctx.beginPath();
          ctx.moveTo(95, -165);
          ctx.lineTo(95, 180);
          ctx.stroke();

          ctx.beginPath();
          ctx.moveTo(-90, -96);
          ctx.lineTo(90, -96);
          ctx.lineTo(62, 60);
          ctx.lineTo(0, 145);
          ctx.lineTo(-62, 60);
          ctx.closePath();
          ctx.stroke();
        }

        function hunter() {
          ctx.beginPath();
          ctx.rect(-76, -98, 152, 166);
          ctx.stroke();

          ctx.beginPath();
          ctx.arc(-8, -145, 58, 0, Math.PI * 2);
          ctx.stroke();

          ctx.beginPath();
          ctx.moveTo(-115, 142);
          ctx.lineTo(132, -78);
          ctx.stroke();
        }

        function witch() {
          ctx.beginPath();
          ctx.moveTo(-120, -70);
          ctx.lineTo(0, -200);
          ctx.lineTo(110, -70);
          ctx.closePath();
          ctx.stroke();

          ctx.strokeRect(-72, -34, 144, 220);

          ctx.beginPath();
          ctx.arc(125, -30, 35, 0, Math.PI * 2);
          ctx.stroke();
        }

        function judge() {
          ctx.beginPath();
          ctx.arc(0, -90, 70, 0, Math.PI * 2);
          ctx.stroke();

          ctx.strokeRect(-90, 0, 180, 190);

          ctx.beginPath();
          ctx.moveTo(-120, 90);
          ctx.lineTo(-55, 5);
          ctx.stroke();

          ctx.strokeRect(50, 20, 90, 120);
        }

        if (cfg.fallback === "wolf") wolf(false);
        else if (cfg.fallback === "wolfKing") wolf(true);
        else if (cfg.fallback === "seer") seer();
        else if (cfg.fallback === "guard") guard();
        else if (cfg.fallback === "hunter") hunter();
        else if (cfg.fallback === "judge") judge();
        else witch();

        ctx.restore();

        ctx.font = "900 72px Microsoft YaHei";
        ctx.textAlign = "center";
        ctx.fillStyle = "rgba(255,240,220,.93)";
        ctx.shadowColor = "rgba(0,0,0,.5)";
        ctx.shadowBlur = 10;
        ctx.fillText(cfg.name, w / 2, h - 80);
      }, 768, 1536);
    }

    async function loadTextureOrFallback(cfg) {
      return new Promise((resolve) => {
        textureLoader.load(
          cfg.file,
          (texture) => {
            texture.colorSpace = THREE.SRGBColorSpace;
            texture.anisotropy = MAX_TEXTURE_ANISOTROPY;
            resolve(texture);
          },
          undefined,
          () => {
            resolve(makeFallbackPosterTexture(cfg));
          }
        );
      });
    }

    const posterGroup = new THREE.Group();
    scene.add(posterGroup);

    async function createPosterWall() {
      const textures = await Promise.all(POSTERS.map(loadTextureOrFallback));

      POSTERS.forEach((cfg, index) => {
        const radius = 8.02;
        const theta = THREE.MathUtils.degToRad(cfg.angle);
        const x = Math.sin(theta) * radius;
        const z = -Math.cos(theta) * radius;

        const panelHeight = 3.55;
        const panelWidth = 1.18;

        const frame = new THREE.Mesh(
          new THREE.BoxGeometry(panelWidth + 0.13, panelHeight + 0.16, 0.07),
          new THREE.MeshStandardMaterial({
            color: 0x130b0b,
            roughness: 0.7,
            metalness: 0.18
          })
        );
        frame.position.set(x, 2.42, z + 0.012);
        frame.lookAt(0, 2.42, 0);
        frame.rotateY(Math.PI);
        frame.castShadow = true;
        posterGroup.add(frame);

        const poster = new THREE.Mesh(
          new THREE.PlaneGeometry(panelWidth, panelHeight),
          new THREE.MeshStandardMaterial({
            map: textures[index],
            roughness: 0.52,
            metalness: 0.04
          })
        );
        poster.position.set(x, 2.42, z + 0.055);
        poster.lookAt(0, 2.42, 0);
        poster.rotateY(Math.PI);
        poster.castShadow = true;
        posterGroup.add(poster);

        const glow = new THREE.Mesh(
          new THREE.PlaneGeometry(panelWidth + 0.35, panelHeight + 0.45),
          new THREE.MeshBasicMaterial({
            color: new THREE.Color(cfg.accent),
            transparent: true,
            opacity: 0.12,
            side: THREE.DoubleSide
          })
        );
        glow.position.set(x, 2.42, z + 0.03);
        glow.lookAt(0, 2.42, 0);
        glow.rotateY(Math.PI);
        posterGroup.add(glow);

        const lampY = 4.36;

        const lamp = new THREE.PointLight(new THREE.Color(cfg.accent), 0.58, 3.2, 1.8);
        lamp.position.set(x * 0.99, lampY, z * 0.99);
        posterGroup.add(lamp);

        const warmLamp = new THREE.PointLight(0xffc58f, 0.58, 2.7, 1.8);
        warmLamp.position.set(x * 0.988, lampY + 0.05, z * 0.988);
        posterGroup.add(warmLamp);

        const lampBody = new THREE.Mesh(
          new THREE.CylinderGeometry(0.08, 0.13, 0.28, 18),
          new THREE.MeshStandardMaterial({
            color: 0xffd9a6,
            emissive: 0xffb36a,
            emissiveIntensity: 0,
            roughness: 0.3
          })
        );
        lampBody.position.copy(warmLamp.position);
        posterGroup.add(lampBody);

        [-0.69, 0.69].forEach((offset) => {
          const localX = x + Math.cos(theta) * offset;
          const localZ = z + Math.sin(theta) * offset;

          const bar = new THREE.Mesh(
            new THREE.BoxGeometry(0.045, 3.72, 0.06),
            new THREE.MeshStandardMaterial({
              color: 0xd8c7a7,
              emissive: 0xd3a66b,
              emissiveIntensity: 0,
              roughness: 0.38
            })
          );
          bar.position.set(localX, 2.43, localZ + 0.045);
          bar.lookAt(0, 2.43, 0);
          bar.rotateY(Math.PI);
          posterGroup.add(bar);
        });
      });

      loading.style.opacity = "0";
      setTrackedTimeout(() => loading.remove(), 450);
      markDirty();
    }

    loading.style.opacity = "0";
    setTrackedTimeout(() => loading.remove(), 450);

    function createOvalTable() {
      const group = new THREE.Group();

      const top = new THREE.Mesh(
        new THREE.CylinderGeometry(2.42, 2.42, 0.23, 96),
        MAT_WOOD
      );
      top.scale.set(1.58, 1, 1);
      top.position.y = 1.05;
      top.castShadow = true;
      top.receiveShadow = true;
      group.add(top);

      const bevel = new THREE.Mesh(
        new THREE.TorusGeometry(2.43, 0.045, 10, 150),
        MAT_GOLD
      );
      bevel.scale.set(1.58, 1, 1);
      bevel.rotation.x = Math.PI / 2;
      bevel.position.y = 1.17;
      group.add(bevel);

      const inner = new THREE.Mesh(
        new THREE.CylinderGeometry(1.12, 1.12, 0.075, 64),
        new THREE.MeshStandardMaterial({
          color: 0x432016,
          roughness: 0.5,
          metalness: 0.05
        })
      );
      inner.scale.set(1.22, 1, 1);
      inner.position.y = 1.19;
      group.add(inner);

      const base = new THREE.Mesh(
        new THREE.CylinderGeometry(0.72, 1.03, 0.86, 42),
        MAT_WOOD
      );
      base.position.y = 0.57;
      base.castShadow = true;
      group.add(base);

      return group;
    }

    scene.add(createOvalTable());

    const tableSeatNumberGroup = new THREE.Group();
    scene.add(tableSeatNumberGroup);

    function makeSeatNumberTexture(label) {
      return makeCanvasTexture((ctx, w, h) => {
        ctx.clearRect(0, 0, w, h);

        if (seatCardImage) {
          ctx.save();
          ctx.translate(0, h);
          ctx.scale(1, -1);
          ctx.drawImage(seatCardImage, 0, 0, w, h);
          ctx.restore();
        } else {
          const grad = ctx.createLinearGradient(0, 0, 0, h);
          grad.addColorStop(0, '#ead8b8');
          grad.addColorStop(0.48, '#d5b889');
          grad.addColorStop(1, '#a77742');
          ctx.fillStyle = grad;
          ctx.fillRect(0, 0, w, h);
          ctx.strokeStyle = '#5f3518';
          ctx.lineWidth = 18;
          ctx.strokeRect(10, 10, w - 20, h - 20);
          ctx.strokeStyle = '#9a6c2c';
          ctx.lineWidth = 5;
          ctx.strokeRect(30, 30, w - 60, h - 60);
        }

        const vignette = ctx.createRadialGradient(w * 0.5, h * 0.42, h * 0.08, w * 0.5, h * 0.52, h * 0.62);
        vignette.addColorStop(0, 'rgba(255, 246, 211, 0.28)');
        vignette.addColorStop(0.72, 'rgba(73, 36, 10, 0.08)');
        vignette.addColorStop(1, 'rgba(40, 20, 8, 0.32)');
        ctx.fillStyle = vignette;
        ctx.fillRect(0, 0, w, h);

        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.shadowColor = 'rgba(32, 15, 5, 0.5)';
        ctx.shadowBlur = 12;
        ctx.fillStyle = 'rgba(56, 31, 13, 0.94)';
        const compactSeat = Number(label) >= 1 && Number(label) <= 12;
        const fontSize = String(label).length > 1
          ? (compactSeat ? 205 : 260)
          : (compactSeat ? 270 : 340);
        ctx.font = `900 ${fontSize}px Microsoft YaHei, Arial, sans-serif`;
        ctx.fillText(label, w / 2, h * 0.52);
      }, 384, 510);
    }

    function disposeSceneObject(object, { disposeShared = false } = {}) {
      const disposedGeometries = new Set();
      const disposedMaterials = new Set();
      const disposedTextures = new Set();
      object.traverse((child) => {
        const fromCachedModel = child.userData.fromCachedModel === true;
        const geometry = child.geometry;
        if (
          geometry &&
          !fromCachedModel &&
          (disposeShared || !SHARED_GEOMETRIES.has(geometry)) &&
          !disposedGeometries.has(geometry)
        ) {
          geometry.dispose?.();
          disposedGeometries.add(geometry);
        }
        const materials = Array.isArray(child.material) ? child.material : [child.material];
        const liveMaterials = Array.isArray(child.userData.liveMaterial)
          ? child.userData.liveMaterial
          : [child.userData.liveMaterial];
        liveMaterials.filter(Boolean).forEach((material) => {
          if (materials.includes(material)) return;
          materials.push(material);
        });
        materials.filter(Boolean).forEach((material) => {
          if (!fromCachedModel) {
            Object.values(material).forEach((value) => {
              if (value?.isTexture && !SHARED_TEXTURES.has(value) && !disposedTextures.has(value)) {
                value.dispose();
                disposedTextures.add(value);
              }
            });
          }
          if ((disposeShared || !SHARED_MATERIALS.has(material)) && !disposedMaterials.has(material)) {
            material.dispose?.();
            disposedMaterials.add(material);
          }
        });
      });
    }

    function clearTableSeatNumbers() {
      while (tableSeatNumberGroup.children.length) {
        const child = tableSeatNumberGroup.children[0];
        tableSeatNumberGroup.remove(child);
        disposeSceneObject(child);
      }
      seatNumberPlates.length = 0;
    }

    function createTableSeatNumber(label, seatPosition, playerId = null) {
      const direction = new THREE.Vector2(seatPosition.x, seatPosition.z);
      if (direction.lengthSq() < 0.0001) direction.set(0, -1);
      direction.normalize();

      const radiusX = 2.42 * 1.58;
      const radiusZ = 2.42;
      const edgeScale = 1 / Math.sqrt((direction.x * direction.x) / (radiusX * radiusX) + (direction.y * direction.y) / (radiusZ * radiusZ));
      const number = Number(label);
      const inset = [3, 4, 9, 10].includes(number) ? 0.82 : [2, 11].includes(number) ? 0.88 : 0.96;
      const sideOffset = number === 3 || number === 4 ? -0.36 : number === 9 || number === 10 ? 0.46 : number === 5 ? -0.18 : number === 8 ? 0.18 : 0;
      const x = direction.x * edgeScale * inset + sideOffset;
      const z = direction.y * edgeScale * inset;

      const group = new THREE.Group();
      const tableContactY = THREE.MathUtils.lerp(1.15, 1.252, THREE.MathUtils.clamp((z + 3.2) / 5.7, 0, 1));
      group.position.set(x, tableContactY, z);
      group.rotation.y = 0;
      group.userData.seatLabel = String(label);
      group.userData.playerId = playerId == null ? null : Number(playerId);
      group.userData.active = false;
      group.userData.selected = false;
      group.userData.activeStartedAt = 0;

      const shadow = new THREE.Mesh(
        new THREE.PlaneGeometry(0.24, 0.12),
        new THREE.MeshBasicMaterial({
          color: 0x120805,
          transparent: true,
          opacity: 0.3,
          depthTest: true,
          depthWrite: false,
          toneMapped: false,
          side: THREE.DoubleSide
        })
      );
      shadow.position.set(0.012, 0.004, -0.045);
      shadow.rotation.x = -Math.PI / 2;
      shadow.renderOrder = 28;
      group.add(shadow);

      const activeGlow = new THREE.Mesh(
        new THREE.PlaneGeometry(0.31, 0.4),
        new THREE.MeshBasicMaterial({
          color: 0xf2ca50,
          transparent: true,
          opacity: 0.28,
          depthTest: true,
          depthWrite: false,
          toneMapped: false,
          side: THREE.DoubleSide
        })
      );
      activeGlow.position.y = 0.142;
      activeGlow.rotation.x = THREE.MathUtils.degToRad(-3);
      activeGlow.renderOrder = 29;
      activeGlow.visible = false;
      group.add(activeGlow);

      const plate = new THREE.Mesh(
        new THREE.PlaneGeometry(0.22, 0.3),
        new THREE.MeshStandardMaterial({
          map: makeSeatNumberTexture(label),
          transparent: true,
          roughness: 0.78,
          metalness: 0.02,
          depthTest: true,
          depthWrite: true,
          toneMapped: false,
          side: THREE.DoubleSide
        })
      );
      plate.position.y = 0.15;
      plate.rotation.x = THREE.MathUtils.degToRad(-3);
      plate.renderOrder = 30;
      group.add(plate);
      seatNumberPlates.push({ mesh: plate, label });
      group.userData.activeSeatRefs = { activeGlow, plate, shadow };
      group.userData.setSeatStates = ({ active = false, selected = false } = {}) => {
        const nextActive = Boolean(active);
        const nextSelected = Boolean(selected);
        if (group.userData.active !== nextActive || group.userData.selected !== nextSelected) {
          group.userData.activeStartedAt = clock.getElapsedTime();
        }
        group.userData.active = nextActive;
        group.userData.selected = nextSelected;
        activeGlow.visible = nextActive || nextSelected;
        activeGlow.material.color.set(nextSelected && !nextActive ? 0xffffff : 0xf2ca50);
        if (!nextActive && !nextSelected) {
          activeGlow.material.opacity = 0.28;
          activeGlow.scale.setScalar(1);
          plate.scale.setScalar(1);
          shadow.material.opacity = 0.3;
          group.userData.seatNumberAnimating = false;
        } else {
          plate.scale.setScalar(nextActive ? 1.08 : 1.05);
          shadow.material.opacity = nextActive ? 0.42 : 0.38;
        }
      };
      group.userData.setActiveSeat = (active) => {
        group.userData.setSeatStates?.({ active, selected: group.userData.selected });
      };

      return group;
    }

    // 玩家模式：在桌子对面放自己的序号牌，正对视角
    function createHumanSeatPlate(label, referencePosition) {
      // 和其他人一样的牌
      const group = createTableSeatNumber(label, referencePosition);

      // 居中并往自己方向（相机方向）移
      group.position.set(0, group.position.y, 2.2);

      // 旋转180度面向自己，但牌子本身要再翻回来避免数字镜像
      group.rotation.y = Math.PI;
      group.children.forEach((child) => {
        if (child.isMesh && child.renderOrder === 30) {
          child.rotation.y = Math.PI;
        }
      });

      // 面前桌面区域加一盏聚光灯照亮（无灯体，只照亮桌面）
      const spotLight = new THREE.SpotLight(0xffe8c0, 3.0, 6, Math.PI / 5, 0.5, 1.5);
      spotLight.position.set(0, 4.0, 3.0);
      spotLight.target.position.set(0, 1.05, 2.2);
      scene.add(spotLight);
      scene.add(spotLight.target);

      // 保存灯的引用，清理时一起移除
      group.userData.humanLamps = [spotLight, spotLight.target];

      return group;
    }

    const flowers = new THREE.Group();

    for (let i = 0; i < 18; i++) {
      const a = (i / 18) * Math.PI * 2;

      const petal = new THREE.Mesh(
        new THREE.SphereGeometry(0.075, 12, 12),
        new THREE.MeshStandardMaterial({
          color: i % 3 === 0 ? 0xe9c8b4 : i % 3 === 1 ? 0xc98b9b : 0xf1dfb6,
          roughness: 0.5
        })
      );

      petal.position.set(
        Math.cos(a) * 0.22,
        1.31 + Math.random() * 0.08,
        Math.sin(a) * 0.15
      );
      flowers.add(petal);
    }

    scene.add(flowers);

    const PLAYER_CUTOUTS = [
      { name: "狼人", file: "/livehall-assets/player-cutouts/wolf.png", height: 1.42 },
      { name: "白狼王", file: "/livehall-assets/player-cutouts/white-wolf-king.png", height: 1.52 },
      { name: "女巫", file: "/livehall-assets/player-cutouts/witch.png", height: 1.52 },
      { name: "守卫", file: "/livehall-assets/player-cutouts/guard.png", height: 1.5 },
      { name: "预言家", file: "/livehall-assets/player-cutouts/seer.png", height: 1.54 },
      { name: "猎人", file: "/livehall-assets/player-cutouts/hunter.png", height: 1.48 },
      { name: "村民", file: "/livehall-assets/player-cutouts/villager.png", height: 1.42 },
      { name: "狼王", file: "/livehall-assets/player-cutouts/wolf-king.png", height: 1.46 }
    ];

    const playerStandeeGroup = new THREE.Group();
    scene.add(playerStandeeGroup);
    const sceneEffectGroup = new THREE.Group();
    scene.add(sceneEffectGroup);
    const textureCache = new Map();
    const cutoutAspectCache = new Map();
    const cutoutAspectWaiters = new Map();
    const modelCache = new Map();
    const modelMaterialCache = new WeakMap();
    let playerRosterSignature = "";
    let queuedModelLoaders = [];
    let modelQueueTimer = null;
    let modelQueueGeneration = 0;
    let speechByPlayer = {};
    let activeSpeakerId = null;
    let activeSeatLabel = null;
    let nightMode = false;
    let playersRevealed = true;
    let humanPlayerId = null;
    let humanSeatLabel = null;
    let humanSeatMesh = null;
    let selectableIds = new Set();
    let selectedTargetId = null;
    let hoveredTargetId = null;
    let onPlayerSelect = null;
    let voteTallyByTarget = new Map();
    let hoveredStandee = null;
    let sceneEffectKey = "";
    let initialEffectsPrimed = false;
    const seenSceneEffectIds = new Set();
    const pendingSceneEffects = new Map();
    const activeSceneEffects = [];
    let sceneEffectRetryTimer = 0;
    const SCENE_EFFECT_RETRY_DELAY = 90;
    const SCENE_EFFECT_MAX_WAIT = 2400;
    const typewriterTimers = new Set();
    const typewriterReducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches === true;
    let instantSpeechText = false;
    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    const seatShuffleSalt = Math.random().toString(36).slice(2);

    function seatHash(value) {
      let hash = 2166136261;
      for (let i = 0; i < value.length; i++) {
        hash ^= value.charCodeAt(i);
        hash = Math.imul(hash, 16777619);
      }
      return hash >>> 0;
    }

    function shufflePlayersForSeats(players) {
      const signature = players.map((player, index) => `${player?.id ?? index}:${player?.role_hint ?? ""}`).join("|");
      return players
        .map((player, index) => ({
          player,
          index,
          order: seatHash(`${seatShuffleSalt}:${signature}:${player?.id ?? index}`)
        }))
        .sort((a, b) => a.order - b.order || a.index - b.index)
        .map((item) => item.player);
    }

    function cutoutForPlayer(player, index = 0) {
      const hint = player?.role_hint || "";
      // 玩家模式下身份未知，统一用平民模型
      if (!hint || hint.includes("未知")) return { ...PLAYER_CUTOUTS[6], playerId: player.id, model: "/livehall-assets/models/villager.glb" };
      if (hint.includes("白狼王")) return { ...PLAYER_CUTOUTS[1], playerId: player.id, model: "/livehall-assets/models/white-wolf-king.glb", modelSize: 1.04 };
      if (hint.includes("狼王")) return { ...PLAYER_CUTOUTS[7], playerId: player.id, model: "/livehall-assets/models/white-wolf-king.glb", modelSize: 1.02 };
      if (hint.includes("狼人")) return { ...PLAYER_CUTOUTS[0], playerId: player.id, model: "/livehall-assets/models/werewolf.glb" };
      if (hint.includes("女巫")) return { ...PLAYER_CUTOUTS[2], playerId: player.id, model: "/livehall-assets/models/nvwu.glb" };
      if (hint.includes("守卫")) return { ...PLAYER_CUTOUTS[3], playerId: player.id, model: "/livehall-assets/models/guard.glb" };
      if (hint.includes("预言")) return { ...PLAYER_CUTOUTS[4], playerId: player.id, model: "/livehall-assets/models/seer.glb" };
      if (hint.includes("猎人")) return { ...PLAYER_CUTOUTS[5], playerId: player.id, model: "/livehall-assets/models/hunter.glb" };
      if (hint.includes("村民") || hint.includes("平民")) return { ...PLAYER_CUTOUTS[6], playerId: player.id, model: "/livehall-assets/models/villager.glb" };
      return { ...PLAYER_CUTOUTS[6], playerId: player?.id, model: "/livehall-assets/models/villager.glb" };
    }

    function getCutoutTexture(file) {
      if (textureCache.has(file)) {
        const texture = textureCache.get(file);
        cacheCutoutAspect(file, texture?.image);
        return texture;
      }
      const texture = textureLoader.load(file, (tex) => {
        tex.colorSpace = THREE.SRGBColorSpace;
        tex.anisotropy = MAX_TEXTURE_ANISOTROPY;
        cacheCutoutAspect(file, tex.image);
      });
      texture.colorSpace = THREE.SRGBColorSpace;
      texture.anisotropy = MAX_TEXTURE_ANISOTROPY;
      textureCache.set(file, texture);
      return texture;
    }

    function cacheCutoutAspect(file, image) {
      const width = Number(image?.naturalWidth || image?.width || 0);
      const height = Number(image?.naturalHeight || image?.height || 0);
      if (!file || width <= 0 || height <= 0) return;
      const aspect = width / height;
      cutoutAspectCache.set(file, aspect);
      const waiters = cutoutAspectWaiters.get(file);
      if (!waiters) return;
      cutoutAspectWaiters.delete(file);
      waiters.forEach((callback) => callback(aspect));
    }

    function onCutoutAspectReady(file, callback) {
      const cachedAspect = cutoutAspectCache.get(file);
      if (cachedAspect) {
        callback(cachedAspect);
        return;
      }
      cacheCutoutAspect(file, textureCache.get(file)?.image);
      const resolvedAspect = cutoutAspectCache.get(file);
      if (resolvedAspect) {
        callback(resolvedAspect);
        return;
      }
      const waiters = cutoutAspectWaiters.get(file) || [];
      waiters.push(callback);
      cutoutAspectWaiters.set(file, waiters);
    }

    function loadModel(file) {
      if (modelCache.has(file)) return modelCache.get(file);
      const promise = loadSharedCouncilModel(file, () => gltfLoader).catch((error) => {
        modelCache.delete(file);
        throw error;
      });
      modelCache.set(file, promise);
      return promise;
    }

    function primeRoleModelRequests(cutouts = []) {
      const roleModels = [...new Set(cutouts.map((cfg) => cfg.model).filter(Boolean))];
      roleModels.forEach((file) => loadModel(file).catch(() => {}));
    }

    function fitModelToStandee(model, targetHeight) {
      model.updateMatrixWorld(true);
      const box = new THREE.Box3().setFromObject(model);
      const size = box.getSize(new THREE.Vector3());
      if (size.y > 0) model.scale.multiplyScalar(targetHeight / size.y);
      model.updateMatrixWorld(true);
      const fittedBox = new THREE.Box3().setFromObject(model);
      const center = fittedBox.getCenter(new THREE.Vector3());
      model.position.x -= center.x;
      model.position.z -= center.z;
      model.position.y += 0.48 - fittedBox.min.y;
      model.position.z += 0.18;
    }

    function prepareLiveModelMaterial(sourceMaterial) {
      if (Array.isArray(sourceMaterial)) return sourceMaterial.map((material) => prepareLiveModelMaterial(material));
      if (!sourceMaterial) return sourceMaterial;
      if (modelMaterialCache.has(sourceMaterial)) return modelMaterialCache.get(sourceMaterial);
      const material = sourceMaterial.clone?.() || sourceMaterial;
      material.side = THREE.DoubleSide;
      material.toneMapped = false;
      material.transparent = false;
      material.opacity = 1;
      material.alphaTest = 0;
      if ("emissive" in material) {
        material.emissive = new THREE.Color(0x241a12);
        material.emissiveIntensity = 0.2;
      }
      if ("metalness" in material) material.metalness = 0.02;
      if ("roughness" in material) material.roughness = Math.min(material.roughness ?? 0.65, 0.72);
      material.depthWrite = true;
      material.needsUpdate = true;
      modelMaterialCache.set(sourceMaterial, material);
      return material;
    }

    function prepareModelClone(source, targetHeight, asOutline = false, rotationY = 0) {
      const model = source.clone(true);
      model.rotation.y = rotationY;
      fitModelToStandee(model, targetHeight);
      model.traverse((object) => {
        if (!object.isMesh) return;
        object.userData.fromCachedModel = true;
        object.castShadow = false;
        object.receiveShadow = false;
        object.frustumCulled = true;
        if (asOutline) {
          // Use shared material for all outline meshes (avoids per-mesh GPU program compilation)
          object.material = SHARED_OUTLINE_MATERIAL;
          object.renderOrder = 14;
        } else {
          object.material = prepareLiveModelMaterial(object.material);
          object.renderOrder = 19;
        }
      });
      return model;
    }

    function createPlayerStandee(cfg, index, total) {
      const group = new THREE.Group();
      const useModelOnlyPlayers = true;
      const safeTotal = Math.max(1, Math.min(12, total));
      const t = safeTotal === 1 ? 0.5 : index / (safeTotal - 1);
      const layout =
        safeTotal <= 6
          ? { angles: null, start: -72, span: 144, radiusX: 3.9, radiusZ: 2.88, zOffset: -0.78, y: 0.2, scale: 0.92, lookZ: 0.22 }
          : safeTotal === 9
            ? { angles: [-142, -78, -50, -25, 0, 25, 50, 78, 142], radiusX: 4.98, radiusZ: 3.34, zOffset: -0.36, y: 0.16, scale: 0.86, lookZ: 0.42 }
          : safeTotal === 10
              ? { angles: [-142, -82, -58, -36, -12, 12, 36, 58, 82, 142], radiusX: 4.98, radiusZ: 3.34, zOffset: -0.36, y: 0.16, scale: 0.86, lookZ: 0.42 }
              : safeTotal === 12
                ? {
                    seats: SEATS_12,
                    radiusX: 4.98,
                    radiusZ: 3.34,
                    zOffset: -0.36,
                    y: 0.38,
                    scale: 0.84,
                    lookZ: 0.42
                  }
                : { angles: null, start: -142, span: 284, radiusX: 4.98, radiusZ: 3.34, zOffset: -0.36, y: 0.16, scale: 0.86, lookZ: 0.42 };
      const seat = layout.seats?.[index];
      const angle = layout.angles?.[index] ?? (layout.start + t * layout.span);
      const theta = THREE.MathUtils.degToRad(angle);
      const seatScale = seat?.scale ?? layout.scale;

      group.position.set(
        seat?.x ?? Math.sin(theta) * layout.radiusX,
        layout.y,
        seat?.z ?? -Math.cos(theta) * layout.radiusZ + layout.zOffset
      );
      group.lookAt(0, 1.18, layout.lookZ);
      group.scale.setScalar(seatScale);
      group.userData.playerId = cfg.playerId;
      group.userData.seatLabel = String(cfg.seatLabel || index + 1);
      group.userData.modelRequired = Boolean(cfg.model);
      group.userData.modelReady = !cfg.model;
      group.userData.modelProgressReported = false;
      group.userData.modelFailed = false;
      const callout = document.createElement("div");
      callout.className = "scene-player-callout";
      const namebar = document.createElement("div");
      namebar.className = "scene-player-namebar";
      const seatLabel = document.createElement("b");
      seatLabel.textContent = cfg.seatLabel || String(index + 1);
      const nameLabel = document.createElement("span");
      nameLabel.textContent = cfg.nameLabel || "玩家";
      const speechPaper = document.createElement("div");
      speechPaper.className = "scene-speech-paper";
      const speechScroll = document.createElement("div");
      speechScroll.className = "scene-speech-scroll";
      const speechText = document.createElement("p");
      speechScroll.appendChild(speechText);
      speechPaper.appendChild(speechScroll);
      namebar.append(seatLabel, nameLabel);
      callout.append(namebar, speechPaper);
      bubbleLayer.appendChild(callout);
      const voteBadge = document.createElement("div");
      voteBadge.className = "scene-vote-badge hidden";
      bubbleLayer.appendChild(voteBadge);
      group.userData.bubble = callout;
      group.userData.voteBadge = voteBadge;
      group.userData.speechPaper = speechPaper;
      group.userData.speechScroll = speechScroll;
      group.userData.speechText = speechText;
      group.userData.speechState = { fullText: "", visibleText: "", tone: "", timer: null };

      const texture = getCutoutTexture(cfg.file);

      const outline = new THREE.Mesh(
        SHARED_PLANE_GEO,
        new THREE.MeshBasicMaterial({
          map: texture,
          color: 0xffffff,
          transparent: true,
          opacity: 1,
          alphaTest: 0.04,
          depthWrite: false,
          depthTest: true,
          side: THREE.DoubleSide,
          toneMapped: false
        })
      );
      outline.position.set(0, 1.34, -0.055);
      outline.rotation.x = THREE.MathUtils.degToRad(-2);
      outline.visible = false;
      outline.renderOrder = 16;
      group.add(outline);

      const figure = new THREE.Mesh(
        SHARED_PLANE_GEO,
        new THREE.MeshBasicMaterial({
          map: texture,
          transparent: true,
          alphaTest: 0.04,
          depthWrite: false,
          depthTest: true,
          side: THREE.DoubleSide,
          toneMapped: false
        })
      );
      figure.position.y = 1.34;
      figure.rotation.x = THREE.MathUtils.degToRad(-2);
      figure.visible = false;
      figure.renderOrder = 18;
      group.add(figure);

      onCutoutAspectReady(cfg.file, (aspect) => {
        if (!group.parent) return; // standee was removed
        figure.scale.set(cfg.height * aspect, cfg.height, 1);
        outline.scale.set(cfg.height * aspect * 1.1, cfg.height * 1.1, 1);
        markDirty();
      });

      const backPlate = new THREE.Mesh(
        new THREE.BoxGeometry(0.82, cfg.height * 0.92, 0.055),
        new THREE.MeshStandardMaterial({
          color: 0x070609,
          roughness: 0.56,
          metalness: 0.18,
          transparent: true,
          opacity: 0.48
        })
      );
      backPlate.position.y = 1.22;
      backPlate.position.z = -0.035;
      backPlate.rotation.x = figure.rotation.x;
      backPlate.visible = false;
      group.add(backPlate);

      const foot = new THREE.Mesh(
        SHARED_FOOT_GEO,
        SHARED_FOOT_MAT
      );
      foot.position.y = 0.46;
      foot.scale.set(1.28, 0.45, 0.78);
      foot.visible = !useModelOnlyPlayers && !cfg.model;
      group.add(foot);

      const activeRing = new THREE.Mesh(
        SHARED_RING_GEO,
        SHARED_RING_MAT
      );
      activeRing.position.y = 0.505;
      activeRing.rotation.x = -Math.PI / 2;
      activeRing.visible = false;
      activeRing.renderOrder = 21;
      group.add(activeRing);

      const activeHalo = new THREE.Mesh(
        SHARED_HALO_GEO,
        SHARED_HALO_MAT
      );
      activeHalo.position.set(0, 1.34, -0.08);
      activeHalo.rotation.x = THREE.MathUtils.degToRad(-2);
      activeHalo.visible = false;
      activeHalo.renderOrder = 15;
      group.add(activeHalo);

      let activeModel = null;
      let modelOutline = null;
      let modelLoading = false;
      let modelMountPromise = null;
      let mountModel = () => Promise.resolve();
      const setObjectDead = (object, dead) => {
        object.traverse((child) => {
          if (!child.isMesh || child === modelOutline) return;
          if (!child.userData.liveMaterial) child.userData.liveMaterial = child.material;
          child.material = dead ? SHARED_DEAD_MATERIAL : child.userData.liveMaterial;
        });
      };
      const applyDeadState = (dead) => {
        group.userData.dead = dead;
        group.visible = playersRevealed && !dead;
        setObjectDead(figure, dead);
        setObjectDead(backPlate, dead);
        setObjectDead(foot, dead);
        if (activeModel) setObjectDead(activeModel, dead);
        if (dead) {
          group.userData.pointerHovered = false;
          group.userData.externalHovered = false;
          group.userData.hovered = false;
          group.userData.selectable = false;
          updateStandeeSpeech(group, "", "");
          callout.classList.remove("speaking");
          outline.visible = false;
          activeRing.visible = false;
          activeHalo.visible = false;
          if (modelOutline) modelOutline.visible = false;
          glow.intensity = 0;
          glow.visible = false;
        }
      };
      if (cfg.model) {
        mountModel = () => {
          if (sceneDisposed) return Promise.resolve();
          if (modelOutline) return Promise.resolve();
          if (modelLoading && modelMountPromise) return modelMountPromise;
          modelLoading = true;
          group.userData.modelReady = false;
          group.userData.modelFailed = false;
          modelMountPromise = loadModel(cfg.model).then((source) => {
            if (sceneDisposed || !group.parent) return;
            const size = cfg.modelSize || 1;
            const model = prepareModelClone(source, cfg.height * 1.24 * size, false, cfg.modelRotationY || 0);
            activeModel = model;
            modelOutline = prepareModelClone(source, cfg.height * 1.28 * size, true, cfg.modelRotationY || 0);
            modelOutline.visible = false;
            group.add(modelOutline);
            group.add(model);
            const modelLight = new THREE.PointLight(0xffdfc5, 2.1, 3.0, 1.4);
            modelLight.position.set(0, 1.62, 0.82);
            group.add(modelLight);
            figure.visible = false;
            backPlate.visible = false;
            foot.visible = false;
            outline.visible = false;
            activeHalo.visible = false;
            applyDeadState(group.userData.dead === true);
            group.userData.setActive?.(group.userData.active === true);
            group.userData.modelReady = true;
            markStandeeModelLoaded(group);
            markDirty();
          }).catch(() => {
            if (sceneDisposed) return;
            cfg.model = "";
            group.userData.modelFailed = true;
            group.userData.modelReady = true;
            markStandeeModelLoaded(group);
          }).finally(() => {
            modelLoading = false;
          });
          return modelMountPromise;
        };
        queuedModelLoaders.push(mountModel);
      }

      const glow = new THREE.PointLight(0xffc07a, 0.18, 2.6, 2);
      glow.position.set(0, 1.2, 0.35);
      group.add(glow);
      group.userData.activeStartedAt = 0;
      group.userData.speakerAnimating = false;
      group.userData.activeRefs = {
        activeRing,
        activeHalo,
        glow,
        figure,
        outline,
        getActiveModel: () => activeModel,
        getModelOutline: () => modelOutline
      };
      figure.visible = false;
      backPlate.visible = false;
      outline.visible = false;
      activeHalo.visible = false;
      group.userData.setActive = (active) => {
        if (group.userData.dead) active = false;
        const nextActive = Boolean(active);
        if (group.userData.active !== nextActive) {
          group.userData.activeStartedAt = clock.getElapsedTime();
        }
        group.userData.active = nextActive;
        callout.classList.toggle("active-speaker", nextActive);
        if (nextActive && cfg.model && !modelOutline) mountModel();
        const speech = group.userData.dead ? "" : (speechByPlayer[group.userData.playerId] || "");
        const text = typeof speech === "string" ? speech : speech.text || "";
        const tone = typeof speech === "string" ? "" : speech.tone || "";
        updateStandeeSpeech(group, text, tone);
        const selected = group.userData.selectedTarget === true;
        const outlined = selected || group.userData.hovered === true;
        outline.visible = !useModelOnlyPlayers && outlined && !modelOutline;
        if (modelOutline) modelOutline.visible = outlined;
        activeRing.visible = nextActive;
        activeHalo.visible = !useModelOnlyPlayers && outlined && !modelOutline;
        glow.color.set(selected ? 0xf2ca50 : outlined ? 0xffffff : 0xffc07a);
        if (!nextActive) resetStandeeSpeakerAnimation(group);
        glow.intensity = nextActive ? 1.0 : selected ? 0.5 : group.userData.hovered ? 0.48 : group.userData.selectable ? 0.32 : 0.18;
        glow.visible = true;
        markDirty();
      };
      group.userData.setHover = (hovered) => {
        group.userData.pointerHovered = !group.userData.dead && Boolean(hovered);
        group.userData.hovered = group.userData.pointerHovered || group.userData.externalHovered === true;
        group.userData.setActive?.(group.userData.active === true);
      };
      group.userData.setExternalHover = (hovered) => {
        group.userData.externalHovered = !group.userData.dead && Boolean(hovered);
        group.userData.hovered = group.userData.pointerHovered === true || group.userData.externalHovered;
        group.userData.setActive?.(group.userData.active === true);
      };
      group.userData.setSelectable = (selectable) => {
        if (group.userData.dead) selectable = false;
        group.userData.selectable = selectable;
        group.userData.setActive?.(group.userData.active === true);
      };
      group.userData.setSelectedTarget = (selected) => {
        if (group.userData.dead) selected = false;
        group.userData.selectedTarget = Boolean(selected);
        callout.classList.toggle("selected-target", group.userData.selectedTarget);
        group.userData.setActive?.(group.userData.active === true);
      };
      group.userData.setDead = applyDeadState;
      applyDeadState(cfg.dead === true);

      return group;
    }

    function updateActiveSpeaker(currentSpeakerId = null) {
      activeSpeakerId = currentSpeakerId;
      const speakerId = currentSpeakerId == null ? null : Number(currentSpeakerId);
      activeSeatLabel = null;
      playerStandeeGroup.children.forEach((standee) => {
        const active = speakerId != null && Number(standee.userData.playerId) === speakerId;
        if (active) activeSeatLabel = standee.userData.seatLabel || null;
        standee.userData.setActive?.(active);
      });
      if (
        !activeSeatLabel &&
        speakerId != null &&
        humanPlayerId != null &&
        Number(humanPlayerId) === speakerId &&
        humanSeatLabel
      ) {
        activeSeatLabel = humanSeatLabel;
      }
      updateActiveSeatNumbers();
    }

    function updateActiveSeatNumbers() {
      tableSeatNumberGroup.children.forEach((seat) => {
        seat.userData.setSeatStates?.({
          active: false,
          selected: playersRevealed && Boolean(selectedTargetId) && seat.userData.playerId === selectedTargetId
        });
      });
    }

    function updateSpeechBubbles() {
      updateActiveSpeaker(activeSpeakerId);
    }

    function clearTypewriterTimer(standee) {
      const state = standee.userData.speechState;
      if (!state?.timer) return;
      clearTrackedTimeout(state.timer);
      typewriterTimers.delete(state.timer);
      state.timer = null;
    }

    function scrollSpeechToLatest(standee) {
      const scroll = standee.userData.speechScroll;
      const speechText = standee.userData.speechText;
      if (!scroll) return;
      requestAnimationFrame(() => {
        const lineHeight = 24;
        const contentHeight = Math.max(lineHeight, speechText?.scrollHeight || lineHeight);
        const visibleHeight = Math.min(lineHeight * 5, Math.ceil(contentHeight / lineHeight) * lineHeight);
        scroll.style.height = `${visibleHeight}px`;
        scroll.scrollTop = Math.max(0, scroll.scrollHeight - scroll.clientHeight);
      });
    }

    function updateStandeeSpeech(standee, nextText = "", nextTone = "") {
      const text = String(nextText || "");
      const tone = String(nextTone || "");
      const callout = standee.userData.bubble;
      const speechText = standee.userData.speechText;
      const state = standee.userData.speechState;
      if (!callout || !speechText || !state) return;

      callout.classList.toggle("speaking", Boolean(text));
      callout.classList.toggle("night-speaking", tone === "night" && Boolean(text));
      callout.classList.toggle("typing", Boolean(text) && state.visibleText !== text);

      if (state.fullText === text && state.tone === tone) {
        scrollSpeechToLatest(standee);
        return;
      }

      const previousFullText = String(state.fullText || "");
      const previousVisibleText = String(state.visibleText || speechText.textContent || "");
      const shouldContinueStream =
        tone === state.tone &&
        text.startsWith(previousFullText) &&
        previousVisibleText.length <= text.length;

      clearTypewriterTimer(standee);
      state.tone = tone;

      if (!text) {
        state.fullText = "";
        state.visibleText = "";
        speechText.textContent = "";
        standee.userData.speechScroll?.style.removeProperty("height");
        callout.classList.remove("typing");
        return;
      }

      if (typewriterReducedMotion || instantSpeechText) {
        state.fullText = text;
        state.visibleText = text;
        speechText.textContent = text;
        callout.classList.remove("typing");
        scrollSpeechToLatest(standee);
        return;
      }

      const characters = Array.from(text);
      let index = shouldContinueStream ? Array.from(previousVisibleText).length : 0;
      speechText.textContent = shouldContinueStream ? previousVisibleText : "";
      callout.classList.add("typing");
      const punctuationDelay = new Set(["，", "。", "？", "！", "；", "、", ",", ".", "?", "!", ";", ":"]);
      state.fullText = text;
      state.visibleText = speechText.textContent;
      const typeNextCharacter = () => {
        typewriterTimers.delete(state.timer);
        index = Math.min(characters.length, index + 1);
        state.visibleText = characters.slice(0, index).join("");
        speechText.textContent = state.visibleText;
        scrollSpeechToLatest(standee);
        if (index >= characters.length) {
          clearTypewriterTimer(standee);
          callout.classList.remove("typing");
          return;
        }
        const current = characters[index - 1];
        const delay = punctuationDelay.has(current) ? 210 : 86;
        state.timer = setTrackedTimeout(typeNextCharacter, delay);
        typewriterTimers.add(state.timer);
      };
      state.timer = setTrackedTimeout(typeNextCharacter, 180);
      typewriterTimers.add(state.timer);
    }

    function updatePlayerReveal() {
      playerStandeeGroup.children.forEach((standee) => {
        standee.visible = playersRevealed && standee.userData.dead !== true;
      });
      tableSeatNumberGroup.visible = playersRevealed;
    }

    function updateDeadStates(players = []) {
      const deadById = new Map(players.map((player) => [player.id, player.alive === false]));
      playerStandeeGroup.children.forEach((standee) => {
        standee.userData.setDead?.(deadById.get(standee.userData.playerId) === true);
      });
      updateActiveSpeaker(activeSpeakerId);
    }

    function updateSelectableStandeeState() {
      playerStandeeGroup.children.forEach((standee) => {
        const playerId = standee.userData.playerId;
        const selectable = selectableIds.has(playerId);
        standee.userData.setSelectable?.(selectable);
        standee.userData.setSelectedTarget?.(selectedTargetId != null && Number(playerId) === selectedTargetId);
        standee.userData.setExternalHover?.(selectable && hoveredTargetId != null && Number(playerId) === hoveredTargetId);
      });
      if (hoveredStandee && !selectableIds.has(hoveredStandee.userData.playerId)) {
        hoveredStandee.userData.setHover?.(false);
        hoveredStandee = null;
      }
      renderer.domElement.style.cursor = selectableIds.size ? "pointer" : "";
      updateActiveSeatNumbers();
    }

    function updateVoteBadges() {
      playerStandeeGroup.children.forEach((standee) => {
        const badge = standee.userData.voteBadge;
        if (!badge) return;
        const row = voteTallyByTarget.get(standee.userData.playerId);
        const count = Number(row?.count) || 0;
        const hidden = !count || !standee.visible || standee.userData.dead === true;
        badge.classList.toggle("hidden", hidden);
        if (hidden) {
          badge.innerHTML = "";
          return;
        }
        const voters = Array.isArray(row?.voters) ? row.voters.filter(Boolean) : [];
        badge.innerHTML = voters.length
          ? `<b>${count}票</b><span>${voters.join("、")}</span>`
          : `<b>${count}票</b>`;
      });
      updateAmbientAnimationState();
    }

    function updateAmbientAnimationState() {
      const hasActiveStandee = playerStandeeGroup.children.some((standee) =>
        standee.visible
        && standee.userData.dead !== true
        && (
          standee.userData.active
          || standee.userData.selectedTarget
          || standee.userData.hovered
          || standee.userData.selectable
        )
      );
      const hasActiveSeat = tableSeatNumberGroup.children.some((seat) => seat.userData.active || seat.userData.selected);
      const hasVisibleVoteBadge = playerStandeeGroup.children.some((standee) =>
        standee.userData.voteBadge && !standee.userData.voteBadge.classList.contains("hidden")
      );
      const next = hasActiveStandee || hasActiveSeat || hasVisibleVoteBadge || activeSceneEffects.length > 0;
      if (hasAmbientAnimation !== next) {
        hasAmbientAnimation = next;
        if (next) markDirty();
      }
    }

    function resetStandeeSpeakerAnimation(standee) {
      const refs = standee?.userData?.activeRefs;
      if (!refs) return;
      refs.activeRing?.scale.setScalar(1);
      refs.activeHalo?.scale.setScalar(1);
      const figureBaseY = refs.figure?.userData?.speakerBaseY;
      const outlineBaseY = refs.outline?.userData?.speakerBaseY;
      if (typeof figureBaseY === "number") refs.figure.position.y = figureBaseY;
      if (typeof outlineBaseY === "number") refs.outline.position.y = outlineBaseY;
      const model = refs.getActiveModel?.();
      const modelOutline = refs.getModelOutline?.();
      if (model && typeof model.userData.speakerBaseY === "number") model.position.y = model.userData.speakerBaseY;
      if (modelOutline && typeof modelOutline.userData.speakerBaseY === "number") {
        modelOutline.position.y = modelOutline.userData.speakerBaseY;
      }
      standee.userData.speakerAnimating = false;
    }

    function updateStandeeSpeakerAnimations(t) {
      playerStandeeGroup.children.forEach((standee) => {
        if (!standee.userData.active || standee.userData.dead === true || !standee.visible) {
          resetStandeeSpeakerAnimation(standee);
          return;
        }
        const refs = standee.userData.activeRefs;
        if (!refs) return;
        const elapsed = Math.max(0, t - (standee.userData.activeStartedAt || t));
        const inEase = THREE.MathUtils.smoothstep(Math.min(elapsed / 0.45, 1), 0, 1);
        const pulse = (Math.sin(t * 4.4) + 1) * 0.5;
        const bob = Math.sin(t * 3.1) * 0.018 * inEase;
        const ringScale = 1.03 + pulse * 0.11 * inEase;
        refs.activeRing.scale.setScalar(ringScale);
        refs.activeHalo.scale.setScalar(1 + pulse * 0.035 * inEase);
        refs.glow.intensity = 0.5 + pulse * 0.34 * inEase;
        refs.glow.visible = true;

        const figure = refs.figure;
        const outline = refs.outline;
        if (figure && typeof figure.userData.speakerBaseY !== "number") figure.userData.speakerBaseY = figure.position.y;
        if (outline && typeof outline.userData.speakerBaseY !== "number") outline.userData.speakerBaseY = outline.position.y;
        if (figure) figure.position.y = figure.userData.speakerBaseY + bob;
        if (outline) outline.position.y = outline.userData.speakerBaseY + bob;

        const model = refs.getActiveModel?.();
        const modelOutline = refs.getModelOutline?.();
        if (model && typeof model.userData.speakerBaseY !== "number") model.userData.speakerBaseY = model.position.y;
        if (modelOutline && typeof modelOutline.userData.speakerBaseY !== "number") {
          modelOutline.userData.speakerBaseY = modelOutline.position.y;
        }
        if (model) model.position.y = model.userData.speakerBaseY + bob;
        if (modelOutline) modelOutline.position.y = modelOutline.userData.speakerBaseY + bob;
        standee.userData.speakerAnimating = true;
      });
    }

    function updateActiveSeatNumberAnimations(t) {
      tableSeatNumberGroup.children.forEach((seat) => {
        const refs = seat.userData.activeSeatRefs;
        if (!refs) return;
        const animated = seat.userData.active || seat.userData.selected;
        if (!animated) {
          refs.plate.scale.setScalar(1);
          refs.activeGlow.scale.setScalar(1);
          refs.activeGlow.material.opacity = 0.28;
          refs.shadow.material.opacity = 0.3;
          seat.userData.seatNumberAnimating = false;
          return;
        }
        const elapsed = Math.max(0, t - (seat.userData.activeStartedAt || t));
        const inEase = THREE.MathUtils.smoothstep(Math.min(elapsed / 0.4, 1), 0, 1);
        const pulse = (Math.sin(t * 5.2) + 1) * 0.5;
        const intensity = seat.userData.active ? 1 : 0.58;
        refs.plate.scale.setScalar((seat.userData.active ? 1.07 : 1.04) + pulse * 0.045 * inEase * intensity);
        refs.activeGlow.scale.setScalar(1.02 + pulse * 0.12 * inEase * intensity);
        refs.activeGlow.material.opacity = 0.18 + pulse * 0.24 * inEase * intensity;
        refs.shadow.material.opacity = 0.34 + pulse * 0.1 * inEase * intensity;
        seat.userData.seatNumberAnimating = true;
      });
    }

    function clamp01(value) {
      return THREE.MathUtils.clamp(value, 0, 1);
    }

    function easeOutCubic(value) {
      const t = clamp01(value);
      return 1 - Math.pow(1 - t, 3);
    }

    function easePulse(value) {
      const t = clamp01(value);
      return Math.sin(t * Math.PI);
    }

    function standeeByPlayerId(id) {
      const playerId = Number(id);
      if (!Number.isFinite(playerId)) return null;
      return playerStandeeGroup.children.find((standee) => Number(standee.userData.playerId) === playerId) || null;
    }

    function seatByPlayerId(id) {
      const playerId = Number(id);
      if (!Number.isFinite(playerId)) return null;
      return tableSeatNumberGroup.children.find((seat) => Number(seat.userData.playerId) === playerId) || null;
    }

    function standeeWorldPosition(standee) {
      const pos = new THREE.Vector3();
      standee?.getWorldPosition?.(pos);
      const isStandee = standee?.parent === playerStandeeGroup;
      pos.y += (isStandee ? 1.32 : 0.24) * (standee?.scale?.y || 1);
      return pos;
    }

    function sceneEffectWorldPosition(target) {
      const pos = standeeWorldPosition(target);
      const isStandee = target?.parent === playerStandeeGroup;
      const toCamera = camera.position.clone().sub(pos);
      toCamera.y = 0;
      if (toCamera.lengthSq() > 0.001) {
        pos.add(toCamera.normalize().multiplyScalar(isStandee ? 0.26 : 0.08));
      }
      if (isStandee) pos.y += 0.08;
      return pos;
    }

    function makeEffectMaterial(color, opacity = 1, additive = true) {
      return new THREE.MeshBasicMaterial({
        color,
        transparent: true,
        opacity,
        depthWrite: false,
        depthTest: false,
        side: THREE.DoubleSide,
        toneMapped: false,
        blending: additive ? THREE.AdditiveBlending : THREE.NormalBlending
      });
    }

    function setEffectOpacity(object, opacity) {
      const materials = Array.isArray(object?.material) ? object.material : [object?.material];
      materials.filter(Boolean).forEach((material) => {
        material.opacity = THREE.MathUtils.clamp(opacity, 0, 1);
        material.needsUpdate = true;
      });
      object.visible = opacity > 0.01;
    }

    function setEffectScale(object, x, y = x, z = x) {
      object.scale.set(Math.max(0.001, x), Math.max(0.001, y), Math.max(0.001, z));
    }

    function updateEffectGlow(sprite, progress, {
      delay = 0,
      duration = 1,
      opacity = 1,
      scaleBoost = 0.45,
      sustain = 0
    } = {}) {
      if (!sprite?.userData?.baseScale) return;
      const q = clamp01((progress - delay) / Math.max(0.001, duration));
      const pulse = sustain
        ? Math.max(easePulse(q), sustain * (1 - q))
        : easePulse(q);
      const base = sprite.userData.baseScale;
      const grow = 1 + easeOutCubic(q) * scaleBoost;
      setEffectScale(sprite, base.x * grow, base.y * grow, base.z);
      setEffectOpacity(sprite, (sprite.userData.baseOpacity || 1) * opacity * pulse);
    }

    function orientBillboard(object) {
      object.quaternion.copy(camera.quaternion);
      object.rotateZ(object.userData.billboardZ || 0);
    }

    function addEffectMesh(effect, name, geometry, color, opacity, {
      position = [0, 0, 0],
      scale = [1, 1, 1],
      rotation = [0, 0, 0],
      billboard = false,
      additive = true
    } = {}) {
      const mesh = new THREE.Mesh(geometry, makeEffectMaterial(color, opacity, additive));
      mesh.position.set(position[0], position[1], position[2]);
      mesh.scale.set(scale[0], scale[1], scale[2]);
      mesh.rotation.set(rotation[0], rotation[1], rotation[2]);
      mesh.renderOrder = 120;
      mesh.frustumCulled = false;
      mesh.userData.baseOpacity = opacity;
      mesh.userData.billboard = billboard;
      mesh.userData.billboardZ = rotation[2] || 0;
      effect.group.add(mesh);
      effect.parts[name] = mesh;
      return mesh;
    }

    function addEffectGlow(effect, name, color, opacity, {
      position = [0, 0, 0],
      scale = [1.4, 1.4, 1]
    } = {}) {
      const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
        map: EFFECT_GLOW_TEXTURE,
        color,
        transparent: true,
        opacity,
        depthWrite: false,
        depthTest: false,
        toneMapped: false,
        blending: THREE.AdditiveBlending
      }));
      sprite.position.set(position[0], position[1], position[2]);
      sprite.scale.set(scale[0], scale[1], scale[2]);
      sprite.renderOrder = 130;
      sprite.frustumCulled = false;
      sprite.userData.baseOpacity = opacity;
      sprite.userData.baseScale = new THREE.Vector3(scale[0], scale[1], scale[2]);
      effect.group.add(sprite);
      effect.parts[name] = sprite;
      return sprite;
    }

    function addEffectLight(effect, color, intensity = 1.2, distance = 2.8) {
      const light = new THREE.PointLight(color, intensity, distance, 2);
      light.position.set(0, 0.12, 0.16);
      light.userData.baseIntensity = intensity;
      effect.group.add(light);
      effect.parts.light = light;
      return light;
    }

    function addVoteOrbs(effect, count = 8, color = EFFECT_COLORS.vote) {
      const orbs = [];
      for (let i = 0; i < count; i++) {
        const orb = addEffectMesh(effect, `voteOrb${i}`, EFFECT_ORB_GEO, color, 0.92, { billboard: false });
        orb.userData.orbIndex = i;
        orbs.push(orb);
      }
      effect.parts.voteOrbs = orbs;
      return orbs;
    }

    function addRisingOrbs(effect, count = 9, color = EFFECT_COLORS.save) {
      const orbs = [];
      for (let i = 0; i < count; i++) {
        const orb = addEffectMesh(effect, `risingOrb${i}`, EFFECT_ORB_GEO, color, 0.82, { billboard: false });
        orb.userData.orbIndex = i;
        orbs.push(orb);
      }
      effect.parts.risingOrbs = orbs;
      return orbs;
    }

    function applySceneEffectTargetOffset(target) {
      const base = target?.userData?.sceneEffectBasePosition;
      const offsets = target?.userData?.sceneEffectOffsets;
      if (!target || !base || !offsets) return;
      const next = base.clone();
      Object.values(offsets).forEach((offset) => {
        next.x += offset.x || 0;
        next.y += offset.y || 0;
        next.z += offset.z || 0;
      });
      target.position.copy(next);
    }

    function setSceneEffectTargetOffset(effect, x = 0, y = 0, z = 0) {
      const target = effect?.target;
      if (!target) return;
      if (!target.userData.sceneEffectBasePosition) {
        target.userData.sceneEffectBasePosition = target.position.clone();
      }
      const offsets = target.userData.sceneEffectOffsets || {};
      offsets[effect.id] = { x, y, z };
      target.userData.sceneEffectOffsets = offsets;
      applySceneEffectTargetOffset(target);
    }

    function clearSceneEffectTargetOffset(effect) {
      const target = effect?.target;
      if (!target?.userData?.sceneEffectOffsets) return;
      delete target.userData.sceneEffectOffsets[effect.id];
      if (Object.keys(target.userData.sceneEffectOffsets).length) {
        applySceneEffectTargetOffset(target);
        return;
      }
      if (target.userData.sceneEffectBasePosition) {
        target.position.copy(target.userData.sceneEffectBasePosition);
      }
      delete target.userData.sceneEffectBasePosition;
      delete target.userData.sceneEffectOffsets;
    }

    function setSceneEffectDead(effect, dead) {
      if (!effect?.target || effect.target.parent !== playerStandeeGroup) return;
      effect.target.userData.setDead?.(dead);
      updateVoteBadges();
    }

    function sceneEffectChangesDeathState(type) {
      return ["wolf_kill", "night_death", "poison_kill", "exile_out"].includes(String(type || ""));
    }

    function sceneEffectOverlayClass(type) {
      if (type === "wolf_guarded") return "guarded";
      if (["wolf_saved", "witch_save"].includes(type)) return "saved";
      if (type === "poison_kill") return "poison";
      if (["vote_mark", "exile_out"].includes(type)) return type === "exile_out" ? "exile" : "vote";
      return "attack";
    }

    function createSceneEffectOverlay(effect) {
      const overlay = document.createElement("div");
      overlay.className = `scene-event-effect ${sceneEffectOverlayClass(effect.type)}`;
      overlay.setAttribute("aria-hidden", "true");
      overlay.style.animation = "none";

      const glow = document.createElement("i");
      glow.className = "scene-event-glow";
      const ring = document.createElement("i");
      ring.className = "scene-event-ring";
      const markA = document.createElement("i");
      markA.className = "scene-event-mark mark-a";
      const markB = document.createElement("i");
      markB.className = "scene-event-mark mark-b";
      const sparks = document.createElement("i");
      sparks.className = "scene-event-sparks";
      overlay.append(glow, ring, markA, markB, sparks);
      [glow, ring, markA, markB, sparks].forEach((node) => {
        node.style.animation = "none";
      });

      sceneEventLayer.appendChild(overlay);
      return overlay;
    }

    function updateSceneEffectOverlayVisuals(effect, progress = 0) {
      const overlay = effect?.overlay;
      if (!overlay) return;
      const rawProgress = clamp01(progress);
      const p = rawProgress <= 0 ? 0.12 : rawProgress;
      const shellIn = easeOutCubic(clamp01(p / 0.12));
      const shellOut = easeOutCubic(clamp01((1 - p) / 0.22));
      const shellOpacity = shellIn * shellOut;
      const overlayScale = 0.82 + easeOutCubic(clamp01(p / 0.22)) * 0.24;
      overlay.style.opacity = String(Math.min(1, shellOpacity));
      overlay.style.transform = `translate(-50%, -50%) scale(${overlayScale.toFixed(3)})`;

      const glow = overlay.querySelector(".scene-event-glow");
      const ring = overlay.querySelector(".scene-event-ring");
      const markA = overlay.querySelector(".mark-a");
      const markB = overlay.querySelector(".mark-b");
      const sparks = overlay.querySelector(".scene-event-sparks");
      const glowQ = clamp01(p / 0.78);
      const ringQ = clamp01((p - 0.04) / 0.72);
      const sparkQ = clamp01((p - 0.08) / 0.78);
      const strikeQ = clamp01(p / 0.58);
      const lateFade = 1 - clamp01((p - 0.76) / 0.2);

      if (glow) {
        glow.style.opacity = String(shellOpacity * (0.18 + easePulse(glowQ) * 0.78));
        glow.style.transform = `scale(${(0.48 + easeOutCubic(glowQ) * 0.96).toFixed(3)})`;
      }
      if (ring) {
        ring.style.opacity = String(shellOpacity * 0.9 * (1 - ringQ));
        ring.style.transform = `scale(${(0.42 + easeOutCubic(ringQ) * 1.18).toFixed(3)})`;
      }
      if (sparks) {
        sparks.style.opacity = String(shellOpacity * easePulse(sparkQ));
        sparks.style.transform = `scale(${(0.45 + sparkQ * 1.28).toFixed(3)}) rotate(${Math.round(sparkQ * 28)}deg)`;
      }

      if (effect.type === "wolf_guarded") {
        if (markA) {
          markA.style.opacity = String(shellOpacity * 0.96 * easePulse(clamp01((p - 0.04) / 0.72)));
          markA.style.transform = `rotate(90deg) scaleX(${(0.58 + easeOutCubic(strikeQ) * 1.08).toFixed(3)})`;
        }
        if (markB) {
          markB.style.opacity = String(shellOpacity * 0.86 * easePulse(clamp01((p - 0.08) / 0.7)));
          markB.style.transform = `scaleY(${(0.56 + easeOutCubic(strikeQ) * 0.88).toFixed(3)})`;
        }
        return;
      }

      if (["wolf_saved", "witch_save"].includes(effect.type)) {
        const rise = easeOutCubic(clamp01((p - 0.08) / 0.68));
        if (markA) {
          markA.style.opacity = String(shellOpacity * 0.92 * easePulse(clamp01((p - 0.02) / 0.8)));
          markA.style.transform = `translateY(${(22 - rise * 48).toFixed(1)}%) scaleY(${(0.38 + rise * 0.96).toFixed(3)})`;
        }
        if (markB) {
          markB.style.opacity = String(shellOpacity * 0.72 * easePulse(clamp01((p - 0.12) / 0.75)));
          markB.style.transform = `translateY(${(28 - rise * 52).toFixed(1)}%) scaleY(${(0.34 + rise * 0.9).toFixed(3)})`;
        }
        return;
      }

      if (effect.type === "poison_kill") {
        const poisonQ = easeOutCubic(clamp01(p / 0.68));
        if (markA) {
          markA.style.opacity = String(shellOpacity * 0.9 * easePulse(clamp01(p / 0.9)));
          markA.style.transform = `translateY(${(-10 + poisonQ * 24).toFixed(1)}%) rotate(${-10 + poisonQ * 18}deg) scaleY(${(0.38 + poisonQ * 0.96).toFixed(3)})`;
        }
        if (markB) {
          markB.style.opacity = String(shellOpacity * 0.62 * easePulse(clamp01((p - 0.08) / 0.8)));
          markB.style.transform = `translateY(${(-16 + poisonQ * 30).toFixed(1)}%) rotate(${10 - poisonQ * 18}deg) scaleY(${(0.32 + poisonQ * 0.82).toFixed(3)})`;
        }
        return;
      }

      if (["vote_mark", "exile_out"].includes(effect.type)) {
        const voteQ = easeOutCubic(clamp01(p / 0.62));
        if (markA) {
          markA.style.opacity = String(shellOpacity * 0.92 * lateFade);
          markA.style.transform = `rotate(-8deg) scaleY(${(0.38 + voteQ * 1.04).toFixed(3)})`;
        }
        if (markB) {
          markB.style.opacity = String(shellOpacity * (effect.type === "exile_out" ? 0.82 : 0.56) * lateFade);
          markB.style.transform = `rotate(8deg) scaleY(${(0.34 + voteQ * 0.92).toFixed(3)})`;
        }
        return;
      }

      if (markA) {
        markA.style.opacity = String(shellOpacity * 0.96 * lateFade);
        markA.style.transform = `rotate(-42deg) scaleY(${(0.36 + easeOutCubic(strikeQ) * 0.98).toFixed(3)})`;
      }
      if (markB) {
        markB.style.opacity = String(shellOpacity * 0.84 * lateFade);
        markB.style.transform = `rotate(43deg) scaleY(${(0.32 + easeOutCubic(strikeQ) * 0.86).toFixed(3)})`;
      }
    }

    function updateSceneEffectOverlayPosition(effect, progress = null) {
      if (!effect?.overlay || !effect.target?.parent) return;
      const visualProgress = progress == null
        ? clamp01((clock.getElapsedTime() - effect.start) / effect.duration)
        : progress;
      const viewport = app.getBoundingClientRect();
      const projected = sceneEffectWorldPosition(effect.target).project(camera);
      const x = viewport.left + (projected.x * 0.5 + 0.5) * viewport.width;
      const y = viewport.top + (-projected.y * 0.5 + 0.5) * viewport.height;
      const visible = projected.z > -1 && projected.z < 1;
      const overlaySize = effect.overlay.offsetWidth || 132;
      const edgePadding = Math.min(
        Math.max(64, overlaySize * 0.6),
        Math.max(48, Math.min(viewport.width, viewport.height) / 2 - 6)
      );
      const minX = Math.min(viewport.left + edgePadding, viewport.left + viewport.width / 2);
      const maxX = Math.max(viewport.left + viewport.width - edgePadding, viewport.left + viewport.width / 2);
      const minY = Math.min(viewport.top + edgePadding, viewport.top + viewport.height / 2);
      const maxY = Math.max(viewport.top + viewport.height - edgePadding, viewport.top + viewport.height / 2);
      const safeX = THREE.MathUtils.clamp(x, minX, maxX);
      const safeY = THREE.MathUtils.clamp(y, minY, maxY);
      effect.overlay.classList.toggle("hidden", !visible);
      effect.overlay.classList.toggle("edge", visible && (Math.abs(safeX - x) > 1 || Math.abs(safeY - y) > 1));
      effect.overlay.style.left = `${safeX}px`;
      effect.overlay.style.top = `${safeY}px`;
      updateSceneEffectOverlayVisuals(effect, visualProgress);
    }

    function disposeEffect(effect) {
      if (!effect) return;
      clearSceneEffectTargetOffset(effect);
      effect.overlay?.remove?.();
      if (effect.group?.parent) effect.group.parent.remove(effect.group);
      disposeSceneObject(effect.group);
    }

    function clearActiveSceneEffects() {
      while (activeSceneEffects.length) {
        disposeEffect(activeSceneEffects.pop());
      }
      while (sceneEffectGroup.children.length) {
        const child = sceneEffectGroup.children[0];
        sceneEffectGroup.remove(child);
        disposeSceneObject(child);
      }
      pendingSceneEffects.clear();
      if (sceneEffectRetryTimer) {
        clearTrackedTimeout(sceneEffectRetryTimer);
        sceneEffectRetryTimer = 0;
      }
      updateAmbientAnimationState();
      markDirty();
    }

    function buildSceneEffectVisuals(effect) {
      const type = effect.type;
      if (["wolf_kill", "wolf_saved", "wolf_guarded", "night_death"].includes(type)) {
        addEffectGlow(effect, "attackGlow", EFFECT_COLORS.wolf, 1, {
          position: [0, 0.08, 0.24],
          scale: [2.45, 2.55, 1]
        });
        addEffectMesh(effect, "impactRing", EFFECT_RING_GEO, EFFECT_COLORS.death, 0.74, {
          position: [0, -0.86, 0],
          scale: [0.34, 0.34, 0.34],
          rotation: [-Math.PI / 2, 0, 0]
        });
        addEffectMesh(effect, "impactDisc", EFFECT_DISC_GEO, EFFECT_COLORS.death, 0.68, {
          position: [0, 0.05, 0.18],
          scale: [1.05, 1.05, 1.05],
          billboard: true
        });
        addEffectMesh(effect, "slashA", EFFECT_SLASH_GEO, EFFECT_COLORS.wolf, 0.96, {
          position: [-0.12, 0.06, 0.26],
          scale: [2.45, 1.88, 1],
          rotation: [0, 0, THREE.MathUtils.degToRad(-48)],
          billboard: true
        });
        addEffectMesh(effect, "slashB", EFFECT_SLASH_GEO, 0xff7a4f, 0.9, {
          position: [0.14, 0.04, 0.27],
          scale: [1.9, 1.68, 1],
          rotation: [0, 0, THREE.MathUtils.degToRad(42)],
          billboard: true
        });
        addEffectLight(effect, EFFECT_COLORS.wolf, 1.65, 3.2);
      }

      if (type === "wolf_guarded") {
        addEffectGlow(effect, "shieldGlow", EFFECT_COLORS.guarded, 1, {
          position: [0, 0.08, 0.3],
          scale: [2.7, 2.95, 1]
        });
        addEffectMesh(effect, "shieldDisc", EFFECT_DISC_GEO, EFFECT_COLORS.guarded, 0.68, {
          position: [0, 0.05, 0.26],
          scale: [1.18, 1.48, 1],
          billboard: true
        });
        addEffectMesh(effect, "shieldRing", EFFECT_RING_GEO, EFFECT_COLORS.guarded, 1, {
          position: [0, 0.05, 0.27],
          scale: [1.36, 1.72, 1],
          billboard: true
        });
        addRisingOrbs(effect, 7, EFFECT_COLORS.guarded);
      }

      if (["wolf_saved", "witch_save"].includes(type)) {
        addEffectGlow(effect, "saveGlow", EFFECT_COLORS.save, 1, {
          position: [0, 0.08, 0.28],
          scale: [2.35, 2.45, 1]
        });
        addEffectMesh(effect, "saveRingA", EFFECT_RING_GEO, EFFECT_COLORS.save, 0.9, {
          position: [0, -0.82, 0],
          scale: [0.28, 0.28, 0.28],
          rotation: [-Math.PI / 2, 0, 0]
        });
        addEffectMesh(effect, "saveRingB", EFFECT_RING_GEO, 0xfff0a5, 0.72, {
          position: [0, -0.68, 0],
          scale: [0.24, 0.24, 0.24],
          rotation: [-Math.PI / 2, 0, 0]
        });
        addEffectMesh(effect, "saveDisc", EFFECT_DISC_GEO, EFFECT_COLORS.save, 0.58, {
          position: [0, 0.04, 0.2],
          scale: [1.0, 1.0, 1],
          billboard: true
        });
        addRisingOrbs(effect, 10, EFFECT_COLORS.save);
        addEffectLight(effect, EFFECT_COLORS.save, 1.75, 3.4);
      }

      if (type === "poison_kill") {
        addEffectGlow(effect, "poisonGlow", EFFECT_COLORS.poison, 0.9, {
          position: [0, 0.02, 0.18],
          scale: [1.9, 1.9, 1]
        });
        addEffectMesh(effect, "poisonRing", EFFECT_RING_GEO, EFFECT_COLORS.poison, 0.86, {
          position: [0, -0.84, 0],
          scale: [0.36, 0.36, 0.36],
          rotation: [-Math.PI / 2, 0, 0]
        });
        addEffectMesh(effect, "poisonCore", EFFECT_DISC_GEO, EFFECT_COLORS.poisonCore, 0.58, {
          position: [0, -0.1, 0.12],
          scale: [0.9, 0.9, 0.9],
          billboard: true
        });
        addRisingOrbs(effect, 12, EFFECT_COLORS.poison);
        addEffectLight(effect, EFFECT_COLORS.poison, 1.2, 2.8);
      }

      if (["vote_mark", "exile_out"].includes(type)) {
        addEffectGlow(effect, "voteGlow", type === "exile_out" ? EFFECT_COLORS.death : EFFECT_COLORS.vote, type === "exile_out" ? 0.86 : 0.62, {
          position: [0, 0, 0.16],
          scale: type === "exile_out" ? [1.9, 1.9, 1] : [1.2, 1.2, 1]
        });
        addEffectMesh(effect, "voteRing", EFFECT_RING_GEO, EFFECT_COLORS.vote, type === "exile_out" ? 0.9 : 0.72, {
          position: [0, -0.86, 0],
          scale: [0.28, 0.28, 0.28],
          rotation: [-Math.PI / 2, 0, 0]
        });
        if (type === "exile_out") {
          addEffectMesh(effect, "exileDisc", EFFECT_DISC_GEO, EFFECT_COLORS.death, 0.42, {
            scale: [0.9, 0.9, 0.9],
            billboard: true
          });
          addEffectLight(effect, EFFECT_COLORS.vote, 1.15, 2.8);
        }
        addVoteOrbs(effect, type === "exile_out" ? 10 : 6, EFFECT_COLORS.vote);
      }
    }

    function sceneEffectDuration(type) {
      if (type === "vote_mark") return 0.72;
      if (type === "wolf_saved") return 1.62;
      if (type === "wolf_guarded") return 1.32;
      if (type === "poison_kill") return 1.28;
      if (type === "witch_save") return 1.32;
      if (type === "exile_out") return 1.32;
      return 1.08;
    }

    function sceneEffectDataId(effectData = {}) {
      const type = String(effectData.type || "");
      if (effectData.id) return String(effectData.id);
      if (!type) return "";
      return `${type}:${effectData.targetId}:${effectData.day || ""}:${effectData.sequence || ""}`;
    }

    function sceneEffectTarget(effectData = {}) {
      return standeeByPlayerId(effectData.targetId) || seatByPlayerId(effectData.targetId);
    }

    function spawnSceneEffect(effectData = {}) {
      const target = sceneEffectTarget(effectData);
      const type = String(effectData.type || "");
      if (!target) return false;
      if (target.visible === false && !sceneEffectChangesDeathState(type)) return false;
      const id = sceneEffectDataId(effectData);
      if (!type || !id) return false;
      const duration = sceneEffectDuration(type);

      const effect = {
        id,
        type,
        data: effectData,
        target,
        group: new THREE.Group(),
        parts: {},
        start: clock.getElapsedTime() - duration * 0.08,
        duration,
        deadApplied: false,
        overlay: null
      };
      effect.group.position.copy(sceneEffectWorldPosition(target));
      effect.group.renderOrder = 70;
      sceneEffectGroup.add(effect.group);
      buildSceneEffectVisuals(effect);
      effect.overlay = createSceneEffectOverlay(effect);
      updateSceneEffectOverlayPosition(effect, 0.12);
      activeSceneEffects.push(effect);
      updateAmbientAnimationState();
      markDirty();
      return true;
    }

    function updateSlashEffect(effect, p) {
      const strike = clamp01(p / 0.46);
      const fade = easePulse(strike);
      const scale = 0.6 + easeOutCubic(strike) * 1.46;
      updateEffectGlow(effect.parts.attackGlow, p, {
        delay: 0,
        duration: effect.type === "wolf_guarded" ? 0.72 : 0.82,
        opacity: effect.type === "night_death" ? 0.86 : 1.16,
        scaleBoost: effect.type === "wolf_guarded" ? 0.5 : 0.64,
        sustain: effect.type === "wolf_kill" ? 0.28 : 0.18
      });
      ["slashA", "slashB"].forEach((key, index) => {
        const mesh = effect.parts[key];
        if (!mesh) return;
        const side = index ? 1 : -1;
        mesh.position.x = side * THREE.MathUtils.lerp(0.32, 0.03, strike);
        setEffectScale(mesh, scale * (index ? 0.86 : 1), scale, 1);
        setEffectOpacity(mesh, (mesh.userData.baseOpacity || 1) * fade);
      });
      const ring = effect.parts.impactRing;
      if (ring) {
        const q = clamp01((p - 0.16) / 0.72);
        setEffectScale(ring, 0.34 + q * 1.9);
        setEffectOpacity(ring, 0.78 * (1 - q));
      }
      const disc = effect.parts.impactDisc;
      if (disc) {
        const q = clamp01((p - 0.08) / 0.72);
        setEffectScale(disc, 0.56 + q * 1.24);
        setEffectOpacity(disc, 0.52 * easePulse(q));
      }
    }

    function updateShieldEffect(effect, p, t) {
      const q = clamp01((p - 0.16) / 0.7);
      const pulse = 0.92 + Math.sin(t * 22) * 0.04;
      updateEffectGlow(effect.parts.shieldGlow, p, {
        delay: 0.18,
        duration: 0.76,
        opacity: 1.18,
        scaleBoost: 0.42,
        sustain: 0.36
      });
      const ring = effect.parts.shieldRing;
      const disc = effect.parts.shieldDisc;
      if (ring) {
        setEffectScale(ring, (0.72 + q * 0.34) * pulse, (0.9 + q * 0.42) * pulse, 1);
        setEffectOpacity(ring, 0.96 * easePulse(q));
      }
      if (disc) {
        setEffectScale(disc, (0.62 + q * 0.2) * pulse, (0.84 + q * 0.24) * pulse, 1);
        setEffectOpacity(disc, 0.34 * easePulse(q));
      }
    }

    function updateSaveEffect(effect, p, t) {
      const q = effect.type === "wolf_saved" ? clamp01((p - 0.24) / 0.62) : clamp01(p / 0.8);
      updateEffectGlow(effect.parts.saveGlow, effect.type === "wolf_saved" ? clamp01((p - 0.18) / 0.78) : p, {
        delay: 0,
        duration: 0.9,
        opacity: effect.type === "wolf_saved" ? 1.18 : 1.02,
        scaleBoost: 0.54,
        sustain: 0.3
      });
      const ringA = effect.parts.saveRingA;
      const ringB = effect.parts.saveRingB;
      const disc = effect.parts.saveDisc;
      if (ringA) {
        ringA.position.y = THREE.MathUtils.lerp(-0.84, 0.18, q);
        setEffectScale(ringA, 0.34 + q * 1.35);
        setEffectOpacity(ringA, 0.9 * easePulse(q));
      }
      if (ringB) {
        ringB.position.y = THREE.MathUtils.lerp(-0.7, 0.42, q);
        setEffectScale(ringB, 0.28 + q * 1.1);
        setEffectOpacity(ringB, 0.72 * easePulse(clamp01(q * 1.05)));
      }
      if (disc) {
        setEffectScale(disc, 0.5 + q * 0.74);
        setEffectOpacity(disc, 0.38 * easePulse(q));
      }
      (effect.parts.risingOrbs || []).forEach((orb) => {
        const index = orb.userData.orbIndex || 0;
        const phase = (q + index / 10) % 1;
        const angle = index * 2.25 + t * 3.4;
        const radius = 0.16 + phase * 0.55;
        orb.position.set(Math.cos(angle) * radius, -0.78 + phase * 1.54, Math.sin(angle) * radius * 0.34 + 0.08);
        const orbScale = 0.9 + phase * 0.9;
        setEffectScale(orb, orbScale);
        setEffectOpacity(orb, 0.72 * easePulse(phase) * easePulse(q));
      });
    }

    function updatePoisonEffect(effect, p, t) {
      updateEffectGlow(effect.parts.poisonGlow, p, {
        delay: 0,
        duration: 0.86,
        opacity: 1.08,
        scaleBoost: 0.5,
        sustain: 0.32
      });
      const ring = effect.parts.poisonRing;
      const core = effect.parts.poisonCore;
      if (ring) {
        setEffectScale(ring, 0.38 + easeOutCubic(p) * 1.8);
        setEffectOpacity(ring, 0.86 * (1 - p));
      }
      if (core) {
        const pulse = (Math.sin(t * 16) + 1) * 0.5;
        setEffectScale(core, 0.48 + pulse * 0.12 + p * 0.36);
        setEffectOpacity(core, 0.26 * easePulse(p));
      }
      (effect.parts.risingOrbs || []).forEach((orb) => {
        const index = orb.userData.orbIndex || 0;
        const phase = clamp01((p * 1.15 + index * 0.07) % 1);
        const angle = index * 1.73 - t * 2.6;
        const radius = 0.18 + phase * 0.62;
        orb.position.set(Math.cos(angle) * radius, -0.74 + phase * 1.38, Math.sin(angle) * radius * 0.46 + 0.08);
        setEffectScale(orb, 0.82 + phase * 0.7);
        setEffectOpacity(orb, 0.7 * easePulse(phase) * (1 - p * 0.35));
      });
    }

    function updateVoteEffect(effect, p, t) {
      const strong = effect.type === "exile_out";
      updateEffectGlow(effect.parts.voteGlow, p, {
        delay: strong ? 0.08 : 0,
        duration: strong ? 0.86 : 0.58,
        opacity: strong ? 1.05 : 0.72,
        scaleBoost: strong ? 0.48 : 0.28,
        sustain: strong ? 0.14 : 0
      });
      const ring = effect.parts.voteRing;
      if (ring) {
        const q = strong ? clamp01(p / 0.86) : p;
        setEffectScale(ring, 0.3 + easeOutCubic(q) * (strong ? 1.7 : 0.95));
        setEffectOpacity(ring, (strong ? 0.92 : 0.7) * (1 - q));
      }
      const disc = effect.parts.exileDisc;
      if (disc) {
        const q = clamp01((p - 0.28) / 0.58);
        setEffectScale(disc, 0.42 + q * 0.9);
        setEffectOpacity(disc, 0.22 * easePulse(q));
      }
      (effect.parts.voteOrbs || []).forEach((orb) => {
        const index = orb.userData.orbIndex || 0;
        const baseAngle = (index / Math.max(1, effect.parts.voteOrbs.length)) * Math.PI * 2;
        const collapse = strong ? easeOutCubic(clamp01((p - 0.18) / 0.68)) : 0;
        const radius = strong ? THREE.MathUtils.lerp(0.88, 0.14, collapse) : 0.48 + Math.sin(t * 5 + index) * 0.04;
        const y = strong ? THREE.MathUtils.lerp(0.54, -0.08, collapse) : 0.04 + Math.sin(t * 5.5 + index) * 0.05;
        orb.position.set(Math.cos(baseAngle + t * 1.2) * radius, y, Math.sin(baseAngle + t * 1.2) * radius * 0.38 + 0.08);
        setEffectScale(orb, strong ? 1.05 + collapse * 0.7 : 0.88);
        setEffectOpacity(orb, (strong ? 0.88 : 0.72) * easePulse(p));
      });
    }

    function updateSceneEffectDeathState(effect, p) {
      if (["wolf_kill", "night_death"].includes(effect.type) && p >= 0.58 && !effect.deadApplied) {
        effect.deadApplied = true;
        setSceneEffectDead(effect, true);
      }
      if (effect.type === "poison_kill" && p >= 0.7 && !effect.deadApplied) {
        effect.deadApplied = true;
        setSceneEffectDead(effect, true);
      }
      if (effect.type === "exile_out" && p >= 0.68 && !effect.deadApplied) {
        effect.deadApplied = true;
        setSceneEffectDead(effect, true);
      }
    }

    function updateSceneEffectShake(effect, p, t) {
      const shakeTypes = new Set(["wolf_kill", "wolf_saved", "wolf_guarded", "poison_kill", "night_death", "exile_out"]);
      if (!shakeTypes.has(effect.type)) {
        clearSceneEffectTargetOffset(effect);
        return;
      }
      const amplitude = {
        wolf_kill: 0.09,
        wolf_saved: 0.07,
        wolf_guarded: 0.045,
        poison_kill: 0.048,
        night_death: 0.075,
        exile_out: 0.065
      }[effect.type] || 0.04;
      const envelope = effect.type === "exile_out"
        ? easePulse(clamp01((p - 0.08) / 0.78))
        : Math.max(0, 1 - p) * easePulse(clamp01(p / 0.62));
      const x = Math.sin(t * 48 + effect.id.length) * amplitude * envelope;
      const z = Math.cos(t * 38 + effect.id.length) * amplitude * 0.38 * envelope;
      setSceneEffectTargetOffset(effect, x, 0, z);
    }

    function updateSceneEffect(effect, t) {
      const p = clamp01((t - effect.start) / effect.duration);
      effect.group.position.copy(sceneEffectWorldPosition(effect.target));
      Object.values(effect.parts).flat().forEach((part) => {
        if (part?.userData?.billboard) orientBillboard(part);
      });
      if (["wolf_kill", "wolf_saved", "wolf_guarded", "night_death"].includes(effect.type)) {
        updateSlashEffect(effect, p);
      }
      if (effect.type === "wolf_guarded") updateShieldEffect(effect, p, t);
      if (["wolf_saved", "witch_save"].includes(effect.type)) updateSaveEffect(effect, p, t);
      if (effect.type === "poison_kill") updatePoisonEffect(effect, p, t);
      if (["vote_mark", "exile_out"].includes(effect.type)) updateVoteEffect(effect, p, t);
      updateSceneEffectDeathState(effect, p);
      updateSceneEffectShake(effect, p, t);
      updateSceneEffectOverlayPosition(effect);
      if (effect.parts.light) effect.parts.light.intensity = (effect.parts.light.userData.baseIntensity || 1) * (1 - p);
      return p >= 1;
    }

    function updateSceneEffects(t) {
      if (!activeSceneEffects.length) return;
      for (let index = activeSceneEffects.length - 1; index >= 0; index--) {
        const effect = activeSceneEffects[index];
        if (!effect.target?.parent || updateSceneEffect(effect, t)) {
          disposeEffect(effect);
          activeSceneEffects.splice(index, 1);
        }
      }
      if (!activeSceneEffects.length) updateAmbientAnimationState();
    }

    function scheduleSceneEffectRetry() {
      if (sceneEffectRetryTimer || !pendingSceneEffects.size || sceneDisposed) return;
      sceneEffectRetryTimer = setTrackedTimeout(() => {
        sceneEffectRetryTimer = 0;
        flushPendingSceneEffects();
      }, SCENE_EFFECT_RETRY_DELAY);
    }

    function enqueueSceneEffect(effectData = {}) {
      const id = sceneEffectDataId(effectData);
      if (!id || pendingSceneEffects.has(id)) return;
      pendingSceneEffects.set(id, { effectData, queuedAt: clock.getElapsedTime() });
      scheduleSceneEffectRetry();
    }

    function tryPlaySceneEffect(effectData = {}) {
      const id = sceneEffectDataId(effectData);
      const type = String(effectData.type || "");
      if (!id || !type) return true;
      if (sceneEffectChangesDeathState(type)) {
        const target = sceneEffectTarget(effectData);
        if (target) setSceneEffectDead({ target }, true);
        return true;
      }
      if (spawnSceneEffect(effectData)) return true;
      enqueueSceneEffect(effectData);
      return false;
    }

    function flushPendingSceneEffects() {
      if (!pendingSceneEffects.size || sceneDisposed) return;
      const now = clock.getElapsedTime();
      pendingSceneEffects.forEach((entry, id) => {
        if (spawnSceneEffect(entry.effectData) || now - entry.queuedAt > SCENE_EFFECT_MAX_WAIT / 1000) {
          pendingSceneEffects.delete(id);
        }
      });
      if (pendingSceneEffects.size) scheduleSceneEffectRetry();
    }

    function latestSceneEffectBatch(effects = []) {
      if (!effects.length) return [];
      const ranked = effects
        .map((effect, index) => ({
          effect,
          index,
          day: Number(effect?.day) || 0,
          sequence: Number(effect?.sequence) || 0
        }))
        .sort((a, b) => (a.day - b.day) || (a.sequence - b.sequence) || (a.index - b.index));
      const latest = ranked.at(-1);
      if (!latest) return [];
      return ranked
        .filter((row) => row.day === latest.day && Math.abs(row.sequence - latest.sequence) <= 0.12)
        .map((row) => row.effect);
    }

    function syncSceneEffects(sceneEffects = [], nextSceneKey = "", { playInitial = false } = {}) {
      const nextKey = String(nextSceneKey || "");
      if (nextKey !== sceneEffectKey) {
        sceneEffectKey = nextKey;
        initialEffectsPrimed = false;
        seenSceneEffectIds.clear();
        clearActiveSceneEffects();
      }
      const effects = Array.isArray(sceneEffects) ? sceneEffects : [];
      if (!initialEffectsPrimed) {
        const initialPlayable = new Set(latestSceneEffectBatch(playInitial ? effects : []).map(sceneEffectDataId));
        effects.forEach((effect) => {
          const id = sceneEffectDataId(effect);
          if (!id) return;
          seenSceneEffectIds.add(id);
          if (initialPlayable.has(id)) tryPlaySceneEffect(effect);
        });
        initialEffectsPrimed = true;
        flushPendingSceneEffects();
        return;
      }
      effects.forEach((effect) => {
        const id = sceneEffectDataId(effect);
        if (!id || seenSceneEffectIds.has(id)) return;
        seenSceneEffectIds.add(id);
        tryPlaySceneEffect(effect);
      });
      flushPendingSceneEffects();
    }

    function standeeFromObject(object) {
      let cursor = object;
      while (cursor && cursor.parent) {
        if (cursor.parent === playerStandeeGroup) return cursor;
        cursor = cursor.parent;
      }
      return null;
    }

    function updatePointer(event) {
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    }

    function pickSelectable(event) {
      if (!selectableIds.size) return null;
      updatePointer(event);
      raycaster.setFromCamera(pointer, camera);
      const hits = raycaster.intersectObjects(playerStandeeGroup.children, true);
      for (const hit of hits) {
        const standee = standeeFromObject(hit.object);
        if (standee && selectableIds.has(standee.userData.playerId) && standee.userData.dead !== true) return standee;
      }
      return null;
    }

    function handlePointerMove(event) {
      const next = pickSelectable(event);
      if (next === hoveredStandee) return;
      hoveredStandee?.userData.setHover?.(false);
      hoveredStandee = next;
      hoveredStandee?.userData.setHover?.(true);
      renderer.domElement.style.cursor = hoveredStandee ? "pointer" : selectableIds.size ? "pointer" : "";
    }

    function handleClick(event) {
      const standee = pickSelectable(event);
      if (standee) onPlayerSelect?.(standee.userData.playerId);
    }

    renderer.domElement.addEventListener("pointermove", handlePointerMove);
    renderer.domElement.addEventListener("click", handleClick);

    // 12-seat layout constant (moved out of setScenePlayers to avoid re-creation every call)
    const SEATS_12 = [
      { x: -2.58, z: 2.48, scale: 0.62 },
      { x: -3.95, z: 0.92, scale: 0.7 },
      { x: -4.36, z: -0.95, scale: 0.77 },
      { x: -3.35, z: -2.25, scale: 0.82 },
      { x: -2.05, z: -2.95, scale: 0.86 },
      { x: -0.68, z: -3.25, scale: 0.88 },
      { x: 0.68, z: -3.25, scale: 0.88 },
      { x: 2.05, z: -2.95, scale: 0.86 },
      { x: 3.35, z: -2.25, scale: 0.82 },
      { x: 4.36, z: -0.95, scale: 0.77 },
      { x: 3.95, z: 0.92, scale: 0.7 },
      { x: 2.58, z: 2.48, scale: 0.62 }
    ];

    function setScenePlayers(players = [], currentSpeakerId = null) {
      const orderedPlayers = players.slice(0, 12);

      // 玩家模式：过滤掉自己，只看到其他 11 人
      const humanPlayer = humanPlayerId != null ? orderedPlayers.find((p) => p.id === humanPlayerId) : null;
      const displayPlayers = humanPlayer ? orderedPlayers.filter((p) => p.id !== humanPlayerId) : orderedPlayers;
      const humanVisualIndex = humanPlayer ? orderedPlayers.indexOf(humanPlayer) : -1;

      const nextSignature = displayPlayers
        .map((player, index) => `${player?.id ?? index}:${player?.role_hint ?? ""}`)
        .join("|");

      if (nextSignature === playerRosterSignature) {
        updateDeadStates(displayPlayers);
        updateActiveSpeaker(currentSpeakerId);
        updateSelectableStandeeState();
        if (playersRevealed) scheduleModelQueue();
        markDirty();
        return;
      }

      playerRosterSignature = nextSignature;
      queuedModelLoaders = [];
      modelQueueGeneration += 1;
      if (modelQueueTimer) {
        clearTrackedTimeout(modelQueueTimer);
        modelQueueTimer = null;
      }
      // Shared resource sets for safe teardown (created once, used per child)
      const _sharedGeos = new Set([SHARED_PLANE_GEO, SHARED_FOOT_GEO, SHARED_RING_GEO, SHARED_HALO_GEO]);
      const _sharedMats = new Set([SHARED_OUTLINE_MATERIAL, SHARED_FOOT_MAT, SHARED_RING_MAT, SHARED_HALO_MAT, SHARED_DEAD_MATERIAL]);
      while (playerStandeeGroup.children.length) {
        const child = playerStandeeGroup.children[0];
        playerStandeeGroup.remove(child);
        child.userData.bubble?.remove?.();
        child.userData.voteBadge?.remove?.();
        child.traverse((object) => {
          if (object.userData.fromCachedModel) return;
          // Don't dispose shared geometry/materials (reused across all standees)
          if (object.geometry && !_sharedGeos.has(object.geometry)) {
            object.geometry.dispose();
          }
          const materials = Array.isArray(object.material) ? object.material : [object.material];
          const liveMaterials = Array.isArray(object.userData.liveMaterial)
            ? object.userData.liveMaterial
            : [object.userData.liveMaterial];
          liveMaterials.filter(Boolean).forEach((material) => {
            if (materials.includes(material)) return;
            materials.push(material);
          });
          materials.filter(Boolean).forEach((material) => {
            if (!_sharedMats.has(material)) material.dispose?.();
          });
        });
      }
      clearTableSeatNumbers();

      // Remove old human seat mesh and its lamps
      if (humanSeatMesh) {
        tableSeatNumberGroup.remove(humanSeatMesh);
        if (humanSeatMesh.userData.humanLamps) {
          humanSeatMesh.userData.humanLamps.forEach((obj) => scene.remove(obj));
        }
        humanSeatMesh = null;
      }

      // 12-seat layout is now the module-level SEATS_12 constant
      const playerModeSeatShift = -0.45;
      const shiftedSeat = (index, shift = 0) => {
        const base = ((index % SEATS_12.length) + SEATS_12.length) % SEATS_12.length;
        const next = (Math.floor(base + shift) + SEATS_12.length) % SEATS_12.length;
        const following = (next + 1) % SEATS_12.length;
        const t = ((base + shift) % 1 + 1) % 1;
        const a = SEATS_12[next];
        const b = SEATS_12[following];
        return {
          x: THREE.MathUtils.lerp(a.x, b.x, t),
          z: THREE.MathUtils.lerp(a.z, b.z, t),
          scale: THREE.MathUtils.lerp(a.scale, b.scale, t)
        };
      };

      const cutouts = displayPlayers
        .map((player, index) => {
          // 在 12 人布局中找到该玩家对应的视觉位置
          const visualIndex = humanPlayer
            ? (index < humanVisualIndex ? index : index + 1)
            : index;
          return {
            ...cutoutForPlayer(player, index),
            seatLabel: String(visualIndex + 1),
            nameLabel: player?.name || player?.role_hint || "玩家",
            roleIcon: player?.roleIcon || "",
            dead: player?.alive === false,
            _visualIndex: visualIndex
          };
        });

      resetModelLoadProgress(cutouts.filter((cfg) => cfg.model).length);
      primeRoleModelRequests(cutouts);

      cutouts.forEach((cfg, index) => {
        cfg.loadModelNow = cfg.playerId === currentSpeakerId;
        // 使用原始 12 人布局中的位置
        const seatIdx = cfg._visualIndex;
        const standee = createPlayerStandee(cfg, seatIdx, 12);
        if (humanPlayer) {
          const seat = shiftedSeat(seatIdx, playerModeSeatShift);
          standee.position.x = seat.x;
          standee.position.z = seat.z;
          standee.scale.setScalar(seat.scale);
          standee.lookAt(0, 1.18, 0.42);
        }
        standee.userData.setActive?.(cfg.playerId === currentSpeakerId);
        standee.visible = playersRevealed && standee.userData.dead !== true;
        playerStandeeGroup.add(standee);
        tableSeatNumberGroup.add(createTableSeatNumber(cfg.seatLabel, standee.position, cfg.playerId));
      });

      // 玩家模式：在桌子对面（靠近相机侧）放自己的序号牌
      if (humanPlayer && humanVisualIndex >= 0) {
        const humanSeatPos = new THREE.Vector3(
          SEATS_12[humanVisualIndex].x,
          0.2,
          SEATS_12[humanVisualIndex].z
        );
        const humanLabel = String(humanVisualIndex + 1);
        humanSeatLabel = humanLabel;
        humanSeatMesh = createHumanSeatPlate(humanLabel, humanSeatPos);
        tableSeatNumberGroup.add(humanSeatMesh);
      }

      tableSeatNumberGroup.visible = playersRevealed;
      updateActiveSpeaker(currentSpeakerId);
      updateSelectableStandeeState();
      updateVoteBadges();
      if (playersRevealed) scheduleModelQueue();
      markDirty();
    }

    function scheduleModelQueue() {
      if (sceneDisposed || modelQueueTimer || !queuedModelLoaders.length) return;
      reportModelLoadProgress();
      const queueGeneration = modelQueueGeneration;
      // Keep model loading parallel, with a short gap so the first visible render stays responsive.
      const batchSize = 6;
      modelQueueTimer = setTrackedTimeout(() => {
        modelQueueTimer = null;
        if (sceneDisposed || queueGeneration !== modelQueueGeneration) return;
        const batch = queuedModelLoaders.splice(0, batchSize);
        Promise.allSettled(batch.map((load) => load?.())).then(() => {
          if (sceneDisposed || queueGeneration !== modelQueueGeneration) return;
          reportModelLoadProgress();
          if (queuedModelLoaders.length) {
            scheduleModelQueue();
          } else {
            scheduleFanBarrier();
          }
        });
      }, 40);
    }

    function preloadQueuedModels() {
      if (modelQueueTimer) {
        clearTrackedTimeout(modelQueueTimer);
        modelQueueTimer = null;
      }
      const loaders = queuedModelLoaders.splice(0);
      const queueGeneration = modelQueueGeneration;
      reportModelLoadProgress(loaders.length ? "加载角色模型" : "角色模型就绪");
      const waitForMountedModels = () => new Promise((resolve) => {
        const startedAt = performance.now();
        const check = () => {
          if (sceneDisposed) {
            resolve();
            return;
          }
          const pending = playerStandeeGroup.children.filter((standee) =>
            standee.userData.modelRequired && !standee.userData.modelReady
          );
          if (!pending.length || performance.now() - startedAt > 20000) {
            resolve();
            return;
          }
          setTrackedTimeout(check, 80);
        };
        check();
      });
      const warmRenderModels = () => {
        return new Promise((resolve) => {
          requestTrackedIdleCallback(() => {
            if (sceneDisposed || queueGeneration !== modelQueueGeneration) {
              resolve();
              return;
            }
            emitLoadProgress({
              phase: "compile",
              label: "编译议事厅光影",
              loaded: Math.min(modelLoadLoaded, Math.max(1, modelLoadTotal)),
              total: Math.max(1, modelLoadTotal),
              progress: 0.93,
              ready: false
            });
            const previous = playerStandeeGroup.children.map((standee) => standee.visible);
            playerStandeeGroup.children.forEach((standee) => {
              if (standee.userData.modelRequired && standee.userData.modelReady && standee.userData.dead !== true) standee.visible = true;
            });
            // Single warm-up render compiles shaders in one pass
            renderer.render(scene, camera);
            playerStandeeGroup.children.forEach((standee, index) => {
              standee.visible = previous[index];
            });
            markDirty();
            resolve();
          });
        });
      };
      const runLoaders = loaders.length
        ? Promise.allSettled(loaders.map((load) => load?.())).then(() => {})
        : Promise.resolve();
      return runLoaders.then(waitForMountedModels).then(warmRenderModels).then(() => {
        if (sceneDisposed || queueGeneration !== modelQueueGeneration) return;
        emitLoadProgress({
          phase: "ready",
          label: "议事厅就绪",
          loaded: Math.max(modelLoadLoaded, modelLoadTotal, 1),
          total: Math.max(1, modelLoadTotal),
          progress: 1,
          ready: true
        });
        scheduleFanBarrier(350);
      });
    }

    setScenePlayers([]);

    function createChair() {
      const group = new THREE.Group();

      const seat = new THREE.Mesh(
        new THREE.BoxGeometry(0.92, 0.22, 0.94),
        MAT_CHAIR
      );
      seat.position.y = 0.62;
      seat.castShadow = true;
      group.add(seat);

      const cushion = new THREE.Mesh(
        new THREE.BoxGeometry(0.78, 0.055, 0.72),
        new THREE.MeshStandardMaterial({
          color: 0x26212a,
          roughness: 0.9
        })
      );
      cushion.position.y = 0.76;
      group.add(cushion);

      const back = new THREE.Mesh(
        new THREE.BoxGeometry(0.95, 1.08, 0.19),
        MAT_CHAIR
      );
      back.position.set(0, 1.1, 0.43);
      back.rotation.x = -0.22;
      back.castShadow = true;
      group.add(back);

      const backCushion = new THREE.Mesh(
        new THREE.BoxGeometry(0.78, 0.82, 0.055),
        new THREE.MeshStandardMaterial({
          color: 0x25212a,
          roughness: 0.9
        })
      );
      backCushion.position.set(0, 1.1, 0.32);
      backCushion.rotation.x = -0.22;
      group.add(backCushion);

      const armL = new THREE.Mesh(
        new THREE.BoxGeometry(0.13, 0.48, 0.72),
        MAT_CHAIR
      );
      armL.position.set(-0.47, 0.82, 0.02);
      armL.rotation.z = 0.1;
      group.add(armL);

      const armR = armL.clone();
      armR.position.x = 0.47;
      armR.rotation.z = -0.1;
      group.add(armR);

      const stem = new THREE.Mesh(
        new THREE.CylinderGeometry(0.07, 0.11, 0.62, 14),
        MAT_DARK
      );
      stem.position.y = 0.31;
      stem.castShadow = true;
      group.add(stem);

      for (let i = 0; i < 5; i++) {
        const a = (i / 5) * Math.PI * 2;

        const leg = new THREE.Mesh(
          new THREE.BoxGeometry(0.08, 0.08, 0.62),
          MAT_DARK
        );
        leg.position.set(
          Math.sin(a) * 0.3,
          0.08,
          Math.cos(a) * 0.3
        );
        leg.rotation.y = a;
        leg.rotation.x = 0.45;
        group.add(leg);
      }

      return group;
    }

    for (let i = 0; i < 0; i++) {
      const a = (i / 10) * Math.PI * 2;
      const chair = createChair();

      const rx = 4.65;
      const rz = 3.85;

      chair.position.set(Math.sin(a) * rx, 0, Math.cos(a) * rz);
      chair.lookAt(0, 0.9, 0);
      chair.rotation.y += Math.PI;
      scene.add(chair);
    }

    const ceilingGroup = new THREE.Group();
    ceilingGroup.position.y = 5.28;
    scene.add(ceilingGroup);

    const ceilingDisc = new THREE.Mesh(
      new THREE.CircleGeometry(5.85, 96),
      new THREE.MeshStandardMaterial({
        map: starTexture,
        color: 0x090911,
        roughness: 0.64,
        metalness: 0.08,
        side: THREE.DoubleSide
      })
    );
    ceilingDisc.rotation.x = Math.PI / 2;
    ceilingGroup.add(ceilingDisc);

    [1.05, 1.82, 2.55, 3.45, 4.62, 5.14].forEach((r, idx) => {
      const ring = new THREE.Mesh(
        new THREE.TorusGeometry(r, idx > 3 ? 0.065 : 0.03, 12, 190),
        idx > 3 ? MAT_GOLD : MAT_DIM_GOLD
      );
      ring.rotation.x = Math.PI / 2;
      ring.position.y = -0.02;
      ceilingGroup.add(ring);
    });

    function addAstroLine(x1, z1, x2, z2, thickness = 0.018, mat = MAT_DIM_GOLD) {
      const dx = x2 - x1;
      const dz = z2 - z1;
      const len = Math.hypot(dx, dz);

      const line = new THREE.Mesh(
        new THREE.BoxGeometry(thickness, thickness, len),
        mat
      );

      line.position.set((x1 + x2) / 2, -0.02, (z1 + z2) / 2);
      line.rotation.y = Math.atan2(dx, dz);
      ceilingGroup.add(line);
    }

    for (let i = 0; i < 20; i++) {
      const a = (i / 20) * Math.PI * 2;
      addAstroLine(
        Math.sin(a) * 0.45,
        Math.cos(a) * 0.45,
        Math.sin(a) * 4.95,
        Math.cos(a) * 4.95,
        0.016
      );
    }

    for (let i = 0; i < 10; i++) {
      const a1 = (i / 10) * Math.PI * 2;
      const a2 = a1 + Math.PI / 7;

      addAstroLine(
        Math.sin(a1) * 3.25,
        Math.cos(a1) * 3.25,
        Math.sin(a2) * 3.25,
        Math.cos(a2) * 3.25,
        0.018,
        MAT_GOLD
      );
    }

    const starShape = new THREE.Shape();
    const outer = 1.82;
    const inner = 0.62;

    for (let i = 0; i < 16; i++) {
      const r = i % 2 === 0 ? outer : inner;
      const a = -Math.PI / 2 + (i / 16) * Math.PI * 2;
      const x = Math.cos(a) * r;
      const y = Math.sin(a) * r;

      if (i === 0) starShape.moveTo(x, y);
      else starShape.lineTo(x, y);
    }

    starShape.closePath();

    const starMesh = new THREE.Mesh(
      new THREE.ShapeGeometry(starShape),
      MAT_GOLD
    );
    starMesh.rotation.x = Math.PI / 2;
    starMesh.position.y = -0.035;
    ceilingGroup.add(starMesh);

    const chandelier = new THREE.Group();
    chandelier.position.set(0, 4.24, 0);
    scene.add(chandelier);

    const chain = new THREE.Mesh(
      new THREE.CylinderGeometry(0.025, 0.025, 0.75, 12),
      MAT_GOLD
    );
    chain.position.y = 0.47;
    chandelier.add(chain);

    const lampCore = new THREE.Mesh(
      new THREE.SphereGeometry(0.34, 24, 16),
      new THREE.MeshStandardMaterial({
        color: 0xffe0b0,
        emissive: 0xffbb77,
        emissiveIntensity: 1.38,
        transparent: true,
        opacity: 0.76,
        roughness: 0.16
      })
    );
    chandelier.add(lampCore);

    const moonCanvas = document.createElement("canvas");
    moonCanvas.width = 256;
    moonCanvas.height = 256;
    const moonCtx = moonCanvas.getContext("2d");
    moonCtx.clearRect(0, 0, 256, 256);
    moonCtx.fillStyle = "#dfe7ff";
    moonCtx.beginPath();
    moonCtx.arc(128, 128, 96, 0, Math.PI * 2);
    moonCtx.fill();
    moonCtx.globalCompositeOperation = "destination-out";
    moonCtx.beginPath();
    moonCtx.arc(165, 116, 92, 0, Math.PI * 2);
    moonCtx.fill();
    moonCtx.globalCompositeOperation = "source-over";
    const moonTexture = new THREE.CanvasTexture(moonCanvas);
    moonTexture.colorSpace = THREE.SRGBColorSpace;
    const moonCrescent = new THREE.Mesh(
      new THREE.PlaneGeometry(0.78, 0.78),
      new THREE.MeshBasicMaterial({
        map: moonTexture,
        transparent: true,
        opacity: 0,
        depthWrite: false,
        toneMapped: false
      })
    );
    moonCrescent.position.set(0, 4.24, 0.24);
    moonCrescent.renderOrder = 40;
    scene.add(moonCrescent);

    const lampRing = new THREE.Mesh(
      new THREE.TorusGeometry(0.58, 0.03, 10, 60),
      MAT_GOLD
    );
    lampRing.rotation.x = Math.PI / 2;
    chandelier.add(lampRing);

    for (let i = 0; i < 8; i++) {
      const a = (i / 8) * Math.PI * 2;

      const arm = new THREE.Mesh(
        new THREE.BoxGeometry(0.026, 0.026, 0.64),
        MAT_GOLD
      );
      arm.position.set(Math.sin(a) * 0.22, 0, Math.cos(a) * 0.22);
      arm.rotation.y = a;
      chandelier.add(arm);
    }

    const particleCount = 360;
    const particleGeo = new THREE.BufferGeometry();
    const particlePos = new Float32Array(particleCount * 3);

    for (let i = 0; i < particleCount; i++) {
      const r = Math.random() * 8.2;
      const a = Math.random() * Math.PI * 2;

      particlePos[i * 3] = Math.sin(a) * r;
      particlePos[i * 3 + 1] = Math.random() * 5.3 + 0.18;
      particlePos[i * 3 + 2] = Math.cos(a) * r;
    }

    particleGeo.setAttribute("position", new THREE.BufferAttribute(particlePos, 3));

    const particles = new THREE.Points(
      particleGeo,
      new THREE.PointsMaterial({
        color: 0xffe6b8,
        size: 0.02,
        transparent: true,
        opacity: 0.55
      })
    );
    scene.add(particles);

    function applyTimeLighting() {
      const night = nightMode;
      renderer.toneMappingExposure = night ? 0.78 : 1.32;
      scene.fog.density = night ? 0.036 : 0.028;
      ambientLight.color.set(0x4b3a58);
      ambientLight.intensity = 0.72;
      mainLight.intensity = night ? 1.18 : 2.35;
      frontSpot.intensity = night ? 0.88 : 2.25;
      leftRed.intensity = night ? 0.72 : 1.45;
      rightPurple.intensity = night ? 0.58 : 1.15;
      backBlue.intensity = night ? 0.52 : 0.9;
      lampCore.material.color.set(night ? 0xe9efff : 0xffe0b0);
      lampCore.material.emissive.set(night ? 0x9eb7ff : 0xffbb77);
      lampCore.material.emissiveIntensity = night ? 0.76 : 1.38;
      lampCore.material.opacity = night ? 0.82 : 0.76;
      moonCrescent.material.opacity = 0;
      particles.material.opacity = night ? 0.38 : 0.55;
      markDirty();
    }

    // ── renderFrame is defined here because it references ceilingGroup,
    //    particles, moonCrescent which are declared just above ──────────
    function renderFrame(time = 0) {
      if (sceneDisposed) {
        animationFrameId = 0;
        return;
      }
      animationFrameId = 0;
      controls.update();
      const camMoved = checkCameraMoved();
      const hasActiveSceneEffect = activeSceneEffects.length > 0;
      if (hasActiveSceneEffect) {
        updateSceneEffects(clock.getElapsedTime());
      }

      // Slow ambient animations at ~10fps (ceiling rotation, particles, moon billboard)
      let ambientDirty = hasActiveSceneEffect;
      if (hasAmbientAnimation && time - lastSlowAnimTime >= SLOW_ANIM_INTERVAL) {
        lastSlowAnimTime = time;
        const t = clock.getElapsedTime();
        ceilingGroup.rotation.y = t * 0.016;
        particles.rotation.y = t * 0.011;
        moonCrescent.quaternion.copy(camera.quaternion);
        updateActiveSeatNumberAnimations(t);
        ambientDirty = true;
      }

      const shouldRender = needsRender || camMoved || ambientDirty;

      if (shouldRender) {
        renderer.render(scene, camera);
        if (camMoved || !cachedBubblePositions) {
          updateBubblePositions();
        }
        needsRender = false;
        idleFrameCount = 0;
      } else {
        idleFrameCount++;
      }

      if (sceneDisposed) return;
      if (activeSceneEffects.length > 0) {
        scheduleRenderFrame();
      } else if (hasAmbientAnimation) {
        scheduleRenderFrame(SLOW_ANIM_INTERVAL);
      } else if (idleFrameCount < IDLE_STOP_THRESHOLD) {
        scheduleRenderFrame();
      }
      // Otherwise the loop stops. markDirty() will restart it when needed.
    }

    // Start the render loop
    animationFrameId = requestAnimationFrame(renderFrame);

    const resizeObserver = new ResizeObserver(() => {
      const width = Math.max(1, app.clientWidth);
      const height = Math.max(1, app.clientHeight);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      applyRendererSize(width, height);
      cachedBubblePositions = null;
      markDirty();
    });
    resizeObserver.observe(app);

    return {
      setLoadProgressHandler(handler) {
        loadProgressHandler = typeof handler === "function" ? handler : null;
        loadProgressHandler?.({ ...loadProgress });
      },
      update({ players = [], currentSpeakerId = null, speechByPlayer: nextSpeechByPlayer = {}, isNight = false, revealPlayers = true, humanId = null, selectableIds: nextSelectableIds = [], selectedTargetId: nextSelectedTargetId = null, hoveredTargetId: nextHoveredTargetId = null, onPlayerSelect: nextOnPlayerSelect = null, voteTally: nextVoteTally = [], sceneEffects: nextSceneEffects = [], sceneKey: nextSceneKey = "", instantSpeech = false, playInitialSceneEffects = false } = {}) {
        speechByPlayer = nextSpeechByPlayer;
        instantSpeechText = Boolean(instantSpeech);
        bubbleLayer.classList.toggle("instant-speech", instantSpeechText);
        playersRevealed = revealPlayers;
        humanPlayerId = humanId;
        selectableIds = new Set(nextSelectableIds);
        selectedTargetId = nextSelectedTargetId == null || nextSelectedTargetId === "" ? null : Number(nextSelectedTargetId);
        hoveredTargetId = nextHoveredTargetId == null || nextHoveredTargetId === "" ? null : Number(nextHoveredTargetId);
        onPlayerSelect = nextOnPlayerSelect;
        voteTallyByTarget = new Map(
          nextVoteTally
            .map((row) => {
              const targetId = Number(row?.target_id ?? row?.targetId);
              if (!Number.isFinite(targetId) || targetId <= 0) return null;
              const voterLabels = Array.isArray(row?.voters)
                ? row.voters.filter(Boolean)
                : Array.isArray(row?.voter_ids)
                  ? row.voter_ids.map((id) => `${Number(id)}号`).filter((label) => !label.startsWith("NaN"))
                  : [];
              const count = Math.max(Number(row?.count) || 0, voterLabels.length);
              return [targetId, { ...row, target_id: targetId, count, voters: voterLabels }];
            })
            .filter(Boolean)
        );
        if (nightMode !== isNight) {
          nightMode = isNight;
          applyTimeLighting();
        }
        setScenePlayers(players, currentSpeakerId);
        updatePlayerReveal();
        updateSpeechBubbles();
        updateSelectableStandeeState();
        updateVoteBadges();
        syncSceneEffects(nextSceneEffects, nextSceneKey, { playInitial: Boolean(playInitialSceneEffects) });
        updateAmbientAnimationState();
        markDirty();
      },
      preloadModels() {
        return preloadQueuedModels();
      },
      dispose() {
        if (sceneDisposed) return;
        sceneDisposed = true;
        loadProgressHandler = null;
        queuedModelLoaders = [];
        modelQueueGeneration += 1;
        if (animationFrameId) {
          cancelAnimationFrame(animationFrameId);
          animationFrameId = 0;
        }
        if (slowFrameTimer) {
          clearTrackedTimeout(slowFrameTimer);
          slowFrameTimer = 0;
        }
        if (modelQueueTimer) {
          clearTrackedTimeout(modelQueueTimer);
          modelQueueTimer = null;
        }
        if (fanBarrierTimer) {
          clearTrackedTimeout(fanBarrierTimer);
          fanBarrierTimer = null;
        }
        typewriterTimers.forEach((timer) => clearTrackedTimeout(timer));
        typewriterTimers.clear();
        clearTrackedTimers();
        clearActiveSceneEffects();
        resizeObserver.disconnect();
        renderer.domElement.removeEventListener("pointermove", handlePointerMove);
        renderer.domElement.removeEventListener("click", handleClick);
        controls.dispose();
        disposeSceneObject(scene, { disposeShared: true });
        renderer.dispose();
        renderer.domElement.remove();
        bubbleLayer.remove();
        sceneEventLayer.remove();
      }
    };
  }
