import * as THREE from "three";
    import { OrbitControls } from "three/addons/controls/OrbitControls.js";
    import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
    import { MeshoptDecoder } from "three/addons/libs/meshopt_decoder.module.js";

    export function createCouncilHallScene(container) {
    const app = container;
    const loading = { style: {}, remove() {} };
    let animationFrameId = 0;

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
      alpha: false
    });
    renderer.setSize(app.clientWidth, app.clientHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.25));
    renderer.shadowMap.enabled = false;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.32;
    app.appendChild(renderer.domElement);
    const bubbleLayer = document.createElement("div");
    bubbleLayer.className = "scene-bubble-layer";
    app.appendChild(bubbleLayer);

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
    const textureLoader = new THREE.TextureLoader();
    const gltfLoader = new GLTFLoader();
    gltfLoader.setMeshoptDecoder(MeshoptDecoder);

    let seatCardImage = null;
    const seatNumberPlates = []; // track all plate meshes for texture refresh
    textureLoader.load('/seat-card-bg.png', (tex) => {
      seatCardImage = tex.image;
      // Regenerate textures for all existing seat number plates
      for (const { mesh, label } of seatNumberPlates) {
        const newTex = makeSeatNumberTexture(label);
        mesh.material.map = newTex;
        mesh.material.needsUpdate = true;
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
      texture.anisotropy = 8;
      texture.needsUpdate = true;
      return texture;
    }

    function makeStarTexture(width = 2048, height = 2048) {
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

    scene.add(new THREE.AmbientLight(0x4b3a58, 0.72));

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
      new THREE.CircleGeometry(9.0, 160),
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
      new THREE.CylinderGeometry(8.55, 8.55, 5.25, 160, 1, true, Math.PI * 0.06, Math.PI * 0.88),
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
      new THREE.CylinderGeometry(8.57, 8.57, 0.28, 160, 1, true, Math.PI * 0.06, Math.PI * 0.88),
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

    async function createFanBarrier() {
      const [redPillar, bluePillar] = await Promise.all([
        gltfLoader.loadAsync("/livehall-assets/models/red-pillar.glb"),
        gltfLoader.loadAsync("/livehall-assets/models/blue-pillar.glb")
      ]);
      const pillarTemplates = [redPillar.scene, bluePillar.scene];
      pillarTemplates.forEach(preparePillarTemplate);

      for (let i = 0; i < 15; i++) {
        addPillarInstance(pillarTemplates[i % pillarTemplates.length], -84 + i * (168 / 14));
      }
    }

    createFanBarrier();

    const centerTexture = makeCanvasTexture((ctx, w, h) => {
      const g = ctx.createLinearGradient(0, 0, 0, h);
      g.addColorStop(0, "#100d25");
      g.addColorStop(1, "#030307");
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, w, h);

      for (let i = 0; i < 240; i++) {
        ctx.fillStyle = "rgba(255,235,190,.8)";
        ctx.fillRect(Math.random() * w, Math.random() * h, 2, 2);
      }

      const pts = [];
      for (let i = 0; i < 20; i++) {
        pts.push([130 + Math.random() * 770, 130 + Math.random() * 440]);
      }

      ctx.strokeStyle = "rgba(120,170,255,.56)";
      ctx.lineWidth = 3;

      for (let i = 0; i < pts.length - 1; i += 2) {
        ctx.beginPath();
        ctx.moveTo(pts[i][0], pts[i][1]);
        ctx.lineTo(pts[i + 1][0], pts[i + 1][1]);
        ctx.stroke();
      }

      pts.forEach(([x, y]) => {
        ctx.fillStyle = "rgba(255,245,220,.95)";
        ctx.beginPath();
        ctx.arc(x, y, 5, 0, Math.PI * 2);
        ctx.fill();
      });

      ctx.font = "italic 118px Georgia";
      ctx.textAlign = "center";
      ctx.fillStyle = "rgba(255,235,220,.92)";
      ctx.fillText("Nightcouncil", w / 2, h * 0.72);
    }, 1024, 1024);

    const centerPanel = new THREE.Mesh(
      new THREE.PlaneGeometry(2.72, 3.38),
      new THREE.MeshStandardMaterial({
        map: centerTexture,
        roughness: 0.55,
        metalness: 0.08
      })
    );
    centerPanel.position.set(0, 2.58, -7.42);
    centerPanel.castShadow = true;
    centerPanel.visible = false;

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
            texture.anisotropy = 8;
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
      setTimeout(() => loading.remove(), 450);
    }

    loading.style.opacity = "0";
    setTimeout(() => loading.remove(), 450);

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
        const fontSize = String(label).length > 1 ? 260 : 340;
        ctx.font = `900 ${fontSize}px Microsoft YaHei, Arial, sans-serif`;
        ctx.fillText(label, w / 2, h * 0.52);
      }, 512, 680);
    }

    function disposeSceneObject(object) {
      object.traverse((child) => {
        child.geometry?.dispose?.();
        const materials = Array.isArray(child.material) ? child.material : [child.material];
        materials.filter(Boolean).forEach((material) => {
          Object.values(material).forEach((value) => value?.isTexture && value.dispose());
          material.dispose?.();
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

    function createTableSeatNumber(label, seatPosition) {
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
    const textureCache = new Map();
    const modelCache = new Map();
    let playerRosterSignature = "";
    let queuedModelLoaders = [];
    let modelQueueTimer = null;
    let speechByPlayer = {};
    let activeSpeakerId = null;
    let nightMode = false;
    let playersRevealed = true;
    let humanPlayerId = null;
    let humanSeatLabel = null;
    let humanSeatMesh = null;
    let selectableIds = new Set();
    let onPlayerSelect = null;
    let voteTallyByTarget = new Map();
    let hoveredStandee = null;
    const typewriterTimers = new Set();
    const typewriterReducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches === true;
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
      if (hint.includes("狼王")) return { ...PLAYER_CUTOUTS[7], playerId: player.id };
      if (hint.includes("狼人")) return { ...PLAYER_CUTOUTS[0], playerId: player.id, model: "/livehall-assets/models/werewolf.glb" };
      if (hint.includes("女巫")) return { ...PLAYER_CUTOUTS[2], playerId: player.id, model: "/livehall-assets/models/nvwu.glb" };
      if (hint.includes("守卫")) return { ...PLAYER_CUTOUTS[3], playerId: player.id, model: "/livehall-assets/models/guard.glb" };
      if (hint.includes("预言")) return { ...PLAYER_CUTOUTS[4], playerId: player.id, model: "/livehall-assets/models/seer.glb" };
      if (hint.includes("猎人")) return { ...PLAYER_CUTOUTS[5], playerId: player.id, model: "/livehall-assets/models/hunter.glb" };
      if (hint.includes("村民")) return { ...PLAYER_CUTOUTS[6], playerId: player.id, model: "/livehall-assets/models/villager.glb" };
      return { ...PLAYER_CUTOUTS[index % PLAYER_CUTOUTS.length], playerId: player?.id };
    }

    function getCutoutTexture(file) {
      if (textureCache.has(file)) return textureCache.get(file);
      const texture = textureLoader.load(file, (tex) => {
        tex.colorSpace = THREE.SRGBColorSpace;
        tex.anisotropy = 8;
      });
      texture.colorSpace = THREE.SRGBColorSpace;
      texture.anisotropy = 8;
      textureCache.set(file, texture);
      return texture;
    }

    function loadModel(file) {
      if (modelCache.has(file)) return modelCache.get(file);
      const promise = gltfLoader.loadAsync(file).then((gltf) => gltf.scene);
      modelCache.set(file, promise);
      return promise;
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
          object.material = new THREE.MeshBasicMaterial({
            color: 0xdfe8ff,
            transparent: true,
            opacity: 0.2,
            depthWrite: false,
            side: THREE.BackSide,
            toneMapped: false
          });
          object.renderOrder = 14;
        } else {
          object.material = object.material?.clone?.() || object.material;
          if (object.material) {
            object.material.side = THREE.DoubleSide;
            object.material.toneMapped = false;
            object.material.transparent = false;
            object.material.opacity = 1;
            object.material.alphaTest = 0;
            if ("emissive" in object.material) {
              object.material.emissive = new THREE.Color(0x21160f);
              object.material.emissiveIntensity = 0.16;
            }
            if ("metalness" in object.material) object.material.metalness = 0.02;
            if ("roughness" in object.material) object.material.roughness = Math.min(object.material.roughness ?? 0.65, 0.72);
            object.material.depthWrite = true;
            object.material.needsUpdate = true;
          }
          object.renderOrder = 19;
        }
      });
      return model;
    }

    function createPlayerStandee(cfg, index, total) {
      const group = new THREE.Group();
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
                    seats: [
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
                    ],
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
      group.userData.modelRequired = Boolean(cfg.model);
      group.userData.modelReady = !cfg.model;
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
      textureLoader.load(cfg.file, (tex) => {
        const aspect = tex.image.width / tex.image.height;
        figure.scale.set(cfg.height * aspect, cfg.height, 1);
        outline.scale.set(cfg.height * aspect * 1.1, cfg.height * 1.1, 1);
      });

      const outline = new THREE.Mesh(
        new THREE.PlaneGeometry(1, 1),
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
        new THREE.PlaneGeometry(1, 1),
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
      figure.renderOrder = 18;
      group.add(figure);

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
      group.add(backPlate);

      const foot = new THREE.Mesh(
        new THREE.CylinderGeometry(0.25, 0.34, 0.08, 32),
        new THREE.MeshStandardMaterial({
          color: 0x21130d,
          roughness: 0.42,
          metalness: 0.22
        })
      );
      foot.position.y = 0.46;
      foot.scale.set(1.28, 0.45, 0.78);
      group.add(foot);

      const activeRing = new THREE.Mesh(
        new THREE.RingGeometry(0.44, 0.62, 48),
        new THREE.MeshBasicMaterial({
          color: 0xdfe8ff,
          transparent: true,
          opacity: 0.34,
          depthWrite: false,
          side: THREE.DoubleSide,
          toneMapped: false
        })
      );
      activeRing.position.y = 0.505;
      activeRing.rotation.x = -Math.PI / 2;
      activeRing.visible = false;
      activeRing.renderOrder = 21;
      group.add(activeRing);

      const activeHalo = new THREE.Mesh(
        new THREE.PlaneGeometry(1.7, 2.05),
        new THREE.MeshBasicMaterial({
          color: 0xdfe8ff,
          transparent: true,
          opacity: 0.08,
          depthWrite: false,
          side: THREE.DoubleSide,
          toneMapped: false
        })
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
      const blackMaterial = new THREE.MeshBasicMaterial({
        color: 0x020202,
        transparent: false,
        toneMapped: false,
        side: THREE.DoubleSide
      });
      const setObjectDead = (object, dead) => {
        object.traverse((child) => {
          if (!child.isMesh || child === modelOutline) return;
          if (!child.userData.liveMaterial) child.userData.liveMaterial = child.material;
          child.material = dead ? blackMaterial : child.userData.liveMaterial;
        });
      };
      const applyDeadState = (dead) => {
        group.userData.dead = dead;
        setObjectDead(figure, dead);
        setObjectDead(backPlate, dead);
        setObjectDead(foot, dead);
        if (activeModel) setObjectDead(activeModel, dead);
        if (dead) {
          group.userData.hovered = false;
          group.userData.selectable = false;
          updateStandeeSpeech(group, "", "");
          callout.classList.remove("speaking");
          outline.visible = false;
          activeRing.visible = false;
          activeHalo.visible = false;
          if (modelOutline) modelOutline.visible = false;
          glow.intensity = 0;
        }
      };
      if (cfg.model) {
        mountModel = () => {
          if (modelOutline) return Promise.resolve();
          if (modelLoading && modelMountPromise) return modelMountPromise;
          modelLoading = true;
          group.userData.modelReady = false;
          group.userData.modelFailed = false;
          modelMountPromise = loadModel(cfg.model).then((source) => {
            if (!group.parent) return;
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
            outline.visible = false;
            activeHalo.visible = false;
            applyDeadState(group.userData.dead === true);
            group.userData.setActive?.(group.userData.active === true);
            group.userData.modelReady = true;
          }).catch(() => {
            cfg.model = "";
            group.userData.modelFailed = true;
            group.userData.modelReady = true;
          }).finally(() => {
            modelLoading = false;
          });
          return modelMountPromise;
        };
        queuedModelLoaders.push(mountModel);
      }

      const glow = new THREE.PointLight(0xffc07a, 0.18, 2.0, 2);
      glow.position.set(0, 1.2, 0.35);
      group.add(glow);
      if (cfg.model) {
        figure.visible = false;
        backPlate.visible = false;
        outline.visible = false;
      }
      group.userData.setActive = (active) => {
        if (group.userData.dead) active = false;
        group.userData.active = active;
        if (active && cfg.model && !modelOutline) mountModel();
        const speech = speechByPlayer[group.userData.playerId] || "";
        const text = typeof speech === "string" ? speech : speech.text || "";
        const tone = typeof speech === "string" ? "" : speech.tone || "";
        updateStandeeSpeech(group, text, tone);
        const outlined = group.userData.hovered === true;
        outline.visible = outlined && !modelOutline;
        if (modelOutline) modelOutline.visible = outlined;
        activeRing.visible = active;
        activeHalo.visible = outlined && !modelOutline;
        glow.color.set(outlined ? 0xffffff : 0xffc07a);
        glow.intensity = active ? 0.62 : group.userData.hovered ? 0.48 : group.userData.selectable ? 0.32 : 0.18;
      };
      group.userData.setHover = (hovered) => {
        if (group.userData.dead) hovered = false;
        group.userData.hovered = hovered;
        group.userData.setActive?.(group.userData.active === true);
      };
      group.userData.setSelectable = (selectable) => {
        if (group.userData.dead) selectable = false;
        group.userData.selectable = selectable;
        group.userData.setActive?.(group.userData.active === true);
      };
      group.userData.setDead = applyDeadState;
      applyDeadState(cfg.dead === true);

      return group;
    }

    function updateActiveSpeaker(currentSpeakerId = null) {
      activeSpeakerId = currentSpeakerId;
      playerStandeeGroup.children.forEach((standee) => {
        standee.userData.setActive?.(standee.userData.playerId === currentSpeakerId);
      });
    }

    function updateSpeechBubbles() {
      playerStandeeGroup.children.forEach((standee) => {
        standee.userData.setActive?.(standee.userData.playerId === activeSpeakerId);
      });
    }

    function clearTypewriterTimer(standee) {
      const state = standee.userData.speechState;
      if (!state?.timer) return;
      window.clearTimeout(state.timer);
      typewriterTimers.delete(state.timer);
      state.timer = null;
    }

    function scrollSpeechToLatest(standee) {
      const scroll = standee.userData.speechScroll;
      if (!scroll) return;
      requestAnimationFrame(() => {
        scroll.scrollTop = scroll.scrollHeight;
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

      clearTypewriterTimer(standee);
      state.fullText = text;
      state.visibleText = "";
      state.tone = tone;

      if (!text) {
        speechText.textContent = "";
        callout.classList.remove("typing");
        return;
      }

      if (typewriterReducedMotion) {
        state.visibleText = text;
        speechText.textContent = text;
        callout.classList.remove("typing");
        scrollSpeechToLatest(standee);
        return;
      }

      const characters = Array.from(text);
      let index = 0;
      speechText.textContent = "";
      callout.classList.add("typing");
      const punctuationDelay = new Set(["，", "。", "？", "！", "；", "、", ",", ".", "?", "!", ";", ":"]);
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
        state.timer = window.setTimeout(typeNextCharacter, delay);
        typewriterTimers.add(state.timer);
      };
      state.timer = window.setTimeout(typeNextCharacter, 180);
      typewriterTimers.add(state.timer);
    }

    function updatePlayerReveal() {
      playerStandeeGroup.children.forEach((standee) => {
        standee.visible = playersRevealed;
      });
      tableSeatNumberGroup.visible = playersRevealed;
    }

    function updateDeadStates(players = []) {
      const deadById = new Map(players.map((player) => [player.id, player.alive === false]));
      playerStandeeGroup.children.forEach((standee) => {
        standee.userData.setDead?.(deadById.get(standee.userData.playerId) === true);
      });
    }

    function updateSelectableStandeeState() {
      playerStandeeGroup.children.forEach((standee) => {
        standee.userData.setSelectable?.(selectableIds.has(standee.userData.playerId));
      });
      if (hoveredStandee && !selectableIds.has(hoveredStandee.userData.playerId)) {
        hoveredStandee.userData.setHover?.(false);
        hoveredStandee = null;
      }
      renderer.domElement.style.cursor = selectableIds.size ? "pointer" : "";
    }

    function updateVoteBadges() {
      playerStandeeGroup.children.forEach((standee) => {
        const badge = standee.userData.voteBadge;
        if (!badge) return;
        const row = voteTallyByTarget.get(standee.userData.playerId);
        const count = row?.count || 0;
        badge.classList.toggle("hidden", !count || !standee.visible || standee.userData.dead === true);
        if (!count) return;
        const voters = row.voters?.length ? row.voters.join("、") : "暂无明细";
        badge.innerHTML = `<b>${count}</b><span>${voters}</span>`;
      });
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
        return;
      }

      playerRosterSignature = nextSignature;
      queuedModelLoaders = [];
      if (modelQueueTimer) {
        window.clearTimeout(modelQueueTimer);
        modelQueueTimer = null;
      }
      while (playerStandeeGroup.children.length) {
        const child = playerStandeeGroup.children[0];
        playerStandeeGroup.remove(child);
        child.userData.bubble?.remove?.();
        child.userData.voteBadge?.remove?.();
        child.traverse((object) => {
          if (object.userData.fromCachedModel) return;
          object.geometry?.dispose?.();
          const materials = Array.isArray(object.material) ? object.material : [object.material];
          materials.filter(Boolean).forEach((material) => material.dispose?.());
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

      // 12 人布局的座位表（用于定位）
      const seats12 = [
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
      const playerModeSeatShift = -0.45;
      const shiftedSeat = (index, shift = 0) => {
        const base = ((index % seats12.length) + seats12.length) % seats12.length;
        const next = (Math.floor(base + shift) + seats12.length) % seats12.length;
        const following = (next + 1) % seats12.length;
        const t = ((base + shift) % 1 + 1) % 1;
        const a = seats12[next];
        const b = seats12[following];
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
        standee.visible = playersRevealed;
        playerStandeeGroup.add(standee);
        tableSeatNumberGroup.add(createTableSeatNumber(cfg.seatLabel, standee.position));
      });

      // 玩家模式：在桌子对面（靠近相机侧）放自己的序号牌
      if (humanPlayer && humanVisualIndex >= 0) {
        const humanSeatPos = new THREE.Vector3(
          seats12[humanVisualIndex].x,
          0.2,
          seats12[humanVisualIndex].z
        );
        const humanLabel = String(humanVisualIndex + 1);
        humanSeatLabel = humanLabel;
        humanSeatMesh = createHumanSeatPlate(humanLabel, humanSeatPos);
        tableSeatNumberGroup.add(humanSeatMesh);
      }

      tableSeatNumberGroup.visible = playersRevealed;
      updateSelectableStandeeState();
      updateVoteBadges();
      if (playersRevealed) scheduleModelQueue();
    }

    function scheduleModelQueue() {
      if (modelQueueTimer || !queuedModelLoaders.length) return;
      modelQueueTimer = window.setTimeout(() => {
        modelQueueTimer = null;
        const next = queuedModelLoaders.shift();
        next?.();
        scheduleModelQueue();
      }, 900);
    }

    function preloadQueuedModels() {
      if (modelQueueTimer) {
        window.clearTimeout(modelQueueTimer);
        modelQueueTimer = null;
      }
      const loaders = queuedModelLoaders.splice(0);
      const waitForMountedModels = () => new Promise((resolve) => {
        const startedAt = performance.now();
        const check = () => {
          const pending = playerStandeeGroup.children.filter((standee) =>
            standee.userData.modelRequired && !standee.userData.modelReady
          );
          if (!pending.length || performance.now() - startedAt > 20000) {
            resolve();
            return;
          }
          window.setTimeout(check, 80);
        };
        check();
      });
      const warmRenderModels = () => {
        const previous = playerStandeeGroup.children.map((standee) => standee.visible);
        playerStandeeGroup.children.forEach((standee) => {
          if (standee.userData.modelRequired && standee.userData.modelReady) standee.visible = true;
        });
        renderer.compile(scene, camera);
        renderer.render(scene, camera);
        playerStandeeGroup.children.forEach((standee, index) => {
          standee.visible = previous[index];
        });
      };
      const runLoaders = loaders.length
        ? Promise.allSettled(loaders.map((load) => load?.())).then(() => {})
        : Promise.resolve();
      return runLoaders.then(waitForMountedModels).then(warmRenderModels);
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
      new THREE.CircleGeometry(5.85, 160),
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
    }

    let lastRenderTime = 0;
    function animate(time = 0) {
      animationFrameId = requestAnimationFrame(animate);
      if (time - lastRenderTime < 33) return;
      lastRenderTime = time;

      const t = clock.getElapsedTime();

      controls.update();

      ceilingGroup.rotation.y = t * 0.016;
      chandelier.rotation.y = 0;
      moonCrescent.quaternion.copy(camera.quaternion);
      lampCore.scale.setScalar(1);
      mainLight.intensity = nightMode ? 1.18 : 2.35;
      particles.rotation.y = t * 0.011;

      renderer.render(scene, camera);
      playerStandeeGroup.children.forEach((standee) => {
        const bubble = standee.userData.bubble;
        const voteBadge = standee.userData.voteBadge;
        const pos = new THREE.Vector3();
        standee.getWorldPosition(pos);
        const bubblePos = pos.clone();
        bubblePos.y += 2.54 * standee.scale.y;
        bubblePos.project(camera);
        const x = (bubblePos.x * 0.5 + 0.5) * app.clientWidth;
        const y = (-bubblePos.y * 0.5 + 0.5) * app.clientHeight;
        if (bubble) {
          bubble.classList.toggle("hidden", !standee.visible || standee.userData.dead === true);
          bubble.style.transform = `translate(-50%, -100%) translate(${x}px, ${y}px)`;
        }
        if (voteBadge) {
          const votePos = pos.clone();
          votePos.y += 2.82 * standee.scale.y;
          votePos.project(camera);
          const vx = (votePos.x * 0.5 + 0.5) * app.clientWidth;
          const vy = (-votePos.y * 0.5 + 0.5) * app.clientHeight;
          voteBadge.style.transform = `translate(-50%, -100%) translate(${vx}px, ${vy}px)`;
        }
      });
    }

    animate();

    const resizeObserver = new ResizeObserver(() => {
      const width = Math.max(1, app.clientWidth);
      const height = Math.max(1, app.clientHeight);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height);
    });
    resizeObserver.observe(app);

    return {
      update({ players = [], currentSpeakerId = null, speechByPlayer: nextSpeechByPlayer = {}, isNight = false, revealPlayers = true, humanId = null, selectableIds: nextSelectableIds = [], onPlayerSelect: nextOnPlayerSelect = null, voteTally: nextVoteTally = [] } = {}) {
        speechByPlayer = nextSpeechByPlayer;
        playersRevealed = revealPlayers;
        humanPlayerId = humanId;
        selectableIds = new Set(nextSelectableIds);
        onPlayerSelect = nextOnPlayerSelect;
        voteTallyByTarget = new Map(nextVoteTally.map((row) => [row.target_id, row]));
        if (nightMode !== isNight) {
          nightMode = isNight;
          applyTimeLighting();
        }
        setScenePlayers(players, currentSpeakerId);
        updatePlayerReveal();
        updateSpeechBubbles();
        updateSelectableStandeeState();
        updateVoteBadges();
      },
      preloadModels() {
        return preloadQueuedModels();
      },
      dispose() {
      typewriterTimers.forEach((timer) => window.clearTimeout(timer));
      typewriterTimers.clear();
      cancelAnimationFrame(animationFrameId);
      resizeObserver.disconnect();
      renderer.domElement.removeEventListener("pointermove", handlePointerMove);
      renderer.domElement.removeEventListener("click", handleClick);
      controls.dispose();
      renderer.dispose();
      renderer.domElement.remove();
      bubbleLayer.remove();
      scene.traverse((object) => {
        object.geometry?.dispose?.();
        const materials = Array.isArray(object.material) ? object.material : [object.material];
        materials.filter(Boolean).forEach((material) => {
          Object.values(material).forEach((value) => value?.isTexture && value.dispose());
          material.dispose?.();
        });
      });
      }
    };
  }

