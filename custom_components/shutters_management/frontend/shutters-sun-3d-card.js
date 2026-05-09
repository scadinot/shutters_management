/**
 * Custom Lovelace card: 3D sun + window visualization for the
 * Shutters Management integration.
 *
 * Adapted from the standalone HTML provided by the user. The original
 * polled `/api/states/sun.sun` with a long-lived bearer token; here we
 * receive the fully-authenticated `hass` object from the Lovelace
 * runtime and read live sun position from `hass.states['sun.sun']`
 * — no token required.
 *
 * The card is registered globally as <shutters-sun-3d-card> via
 * `add_extra_js_url` in __init__.py.
 */

import * as THREE from "./three.module.min.js";
import { OrbitControls } from "./OrbitControls.js";

const HORIZON_R = 12;
const DOME_R = 11;

const STYLE = `
  :host {
    display: block;
    height: var(--shutters-sun-3d-height, 360px);
    position: relative;
    background: #0f1419;
    border-radius: var(--ha-card-border-radius, 12px);
    overflow: hidden;
  }
  #wrap {
    position: absolute;
    inset: 0;
  }
  canvas { display: block; }

  .overlay-top {
    position: absolute;
    top: 12px;
    left: 12px;
    right: 12px;
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 8px;
    pointer-events: none;
    z-index: 10;
  }
  .card {
    background: rgba(28, 28, 30, 0.85);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    border: 0.5px solid rgba(255, 255, 255, 0.12);
    border-radius: 10px;
    padding: 8px 12px;
    color: #ffffff;
    font-family: var(--paper-font-body1_-_font-family,
                     -apple-system, BlinkMacSystemFont, sans-serif);
  }
  .card .label {
    font-size: 10px;
    color: rgba(255, 255, 255, 0.6);
    text-transform: uppercase;
    letter-spacing: 0.6px;
  }
  .card .value {
    font-size: 16px;
    font-weight: 500;
    margin-top: 2px;
  }
  .card .sub {
    font-size: 11px;
    color: rgba(255, 255, 255, 0.6);
    margin-top: 1px;
  }
  .status-open  { color: #4ADE80; }
  .status-warn  { color: #FBBF24; }
  .status-close { color: #F87171; }

  .overlay-bottom {
    position: absolute;
    bottom: 8px;
    left: 12px;
    background: rgba(28, 28, 30, 0.85);
    border: 0.5px solid rgba(255, 255, 255, 0.12);
    border-radius: 8px;
    padding: 4px 8px;
    font-size: 10px;
    color: rgba(255, 255, 255, 0.6);
    z-index: 10;
    pointer-events: none;
  }
`;

class ShuttersSun3dCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._built = false;
    this._lastUpdate = 0;
  }

  setConfig(config) {
    if (config === undefined || config === null) {
      throw new Error("Invalid configuration");
    }
    this._config = {
      orientation: 180,
      arc: 60,
      min_elevation: 5,
      latitude: null,
      longitude: 0,
      subentry_prefix: null,
      labels: null,
      covers: [],
      ...config,
    };
    if (this._built) {
      // Rebuild the scene so orientation/arc changes apply on reload.
      this._teardown();
    }
    this._build();
    if (this._hass) {
      this._refreshFromHass();
    }
  }

  set hass(hass) {
    this._hass = hass;
    if (this._built) {
      this._refreshFromHass();
    }
  }

  getCardSize() {
    return 6;
  }

  // ----------------------------------------------------------------
  // Scene construction
  // ----------------------------------------------------------------

  _build() {
    const root = this.shadowRoot;
    root.innerHTML = `
      <style>${STYLE}</style>
      <div id="wrap">
        <div class="overlay-top">
          <div class="card">
            <div class="label">${this._t("shutter")}</div>
            <div class="value" data-id="statusValue">—</div>
            <div class="sub" data-id="statusSub">—</div>
          </div>
          <div class="card">
            <div class="label">${this._t("sun")}</div>
            <div class="value" data-id="azValue">—</div>
            <div class="sub" data-id="elValue">—</div>
          </div>
          <div class="card">
            <div class="label">${this._t("facade")}</div>
            <div class="value" data-id="facadeValue">—</div>
            <div class="sub" data-id="deltaValue">Δ —</div>
          </div>
        </div>
        <div class="overlay-bottom">${this._t("hint")}</div>
      </div>
    `;
    this._wrap = root.getElementById("wrap");
    this._uiRefs = {
      statusValue: root.querySelector('[data-id="statusValue"]'),
      statusSub: root.querySelector('[data-id="statusSub"]'),
      azValue: root.querySelector('[data-id="azValue"]'),
      elValue: root.querySelector('[data-id="elValue"]'),
      facadeValue: root.querySelector('[data-id="facadeValue"]'),
      deltaValue: root.querySelector('[data-id="deltaValue"]'),
    };

    // The container is sized via CSS but its actual pixel dimensions
    // depend on the layout — defer to a ResizeObserver to apply the
    // real size to the renderer once it is laid out.
    this._buildScene();
    this._buildHouse();
    this._buildSky();
    this._buildSun();
    this._buildIncidenceCone();
    this._buildDayPath();

    this._resizeObserver = new ResizeObserver(() => this._handleResize());
    this._resizeObserver.observe(this._wrap);

    this._built = true;
    this._animate();
  }

  _buildScene() {
    const w = Math.max(this._wrap.clientWidth, 200);
    const h = Math.max(this._wrap.clientHeight, 200);

    this._scene = new THREE.Scene();
    this._scene.background = new THREE.Color(0x0f1419);
    this._scene.fog = new THREE.Fog(0x0f1419, 30, 80);

    this._camera = new THREE.PerspectiveCamera(45, w / h, 0.1, 200);
    this._camera.position.set(15, 12, 18);

    this._renderer = new THREE.WebGLRenderer({ antialias: true });
    this._renderer.setSize(w, h);
    this._renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this._renderer.shadowMap.enabled = true;
    this._renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this._wrap.appendChild(this._renderer.domElement);

    this._controls = new OrbitControls(this._camera, this._renderer.domElement);
    this._controls.enableDamping = true;
    this._controls.dampingFactor = 0.08;
    this._controls.minDistance = 8;
    this._controls.maxDistance = 50;
    this._controls.maxPolarAngle = Math.PI / 2 - 0.05;
    this._controls.target.set(0, 1, 0);

    // Lights
    this._scene.add(new THREE.AmbientLight(0x6688aa, 0.4));
    this._scene.add(new THREE.HemisphereLight(0x88aaff, 0x2a3320, 0.5));

    this._sunLight = new THREE.DirectionalLight(0xfff0d0, 1.0);
    this._sunLight.castShadow = true;
    this._sunLight.shadow.mapSize.set(1024, 1024);
    this._sunLight.shadow.camera.left = -15;
    this._sunLight.shadow.camera.right = 15;
    this._sunLight.shadow.camera.top = 15;
    this._sunLight.shadow.camera.bottom = -15;
    this._scene.add(this._sunLight);
    this._scene.add(this._sunLight.target);

    // Ground + horizon ring
    const ground = new THREE.Mesh(
      new THREE.CircleGeometry(HORIZON_R, 64),
      new THREE.MeshStandardMaterial({ color: 0x3a5a2a, roughness: 0.95 })
    );
    ground.rotation.x = -Math.PI / 2;
    ground.receiveShadow = true;
    this._scene.add(ground);

    // Horizon ring as a thin torus instead of a 1px Line — WebGL
    // line widths are clamped to 1 by most browsers, so we use a
    // tube to get a visible thickness.
    const horizonTorus = new THREE.Mesh(
      new THREE.TorusGeometry(HORIZON_R, 0.07, 8, 96),
      new THREE.MeshBasicMaterial({ color: 0x88aa66 })
    );
    horizonTorus.rotation.x = Math.PI / 2;
    // Lift the ring so its full thickness sits above the ground (the
    // tube radius is 0.07; sitting at y=0.02 dipped half below the
    // green disc at y=0 and z-fought with it).
    horizonTorus.position.y = 0.09;
    this._scene.add(horizonTorus);

    // Cardinal / intermediate tick marks as thin boxes (cardinal
    // longer + thicker than intermediates) so they read against the
    // green ground.
    const tickMat = new THREE.MeshBasicMaterial({ color: 0x88aa66 });
    for (let deg = 0; deg < 360; deg += 30) {
      const rad = THREE.MathUtils.degToRad(deg);
      const isCardinal = deg % 90 === 0;
      const length = isCardinal ? 0.6 : 0.3;
      const thick = isCardinal ? 0.09 : 0.06;
      const tick = new THREE.Mesh(
        new THREE.BoxGeometry(length, thick, thick),
        tickMat
      );
      const midR = HORIZON_R - length / 2;
      // Lift the box's center to thick/2 + small offset so its
      // bottom face stays above the ground and avoids z-fighting.
      const tickY = 0.02 + thick / 2;
      tick.position.set(Math.sin(rad) * midR, tickY, -Math.cos(rad) * midR);
      // Default box X axis points along world X. Rotate around Y so
      // the long side aligns with the radial direction at ``rad``.
      tick.rotation.y = Math.PI / 2 - rad;
      this._scene.add(tick);
    }
  }

  _buildSky() {
    const elevationCircle = (elDeg, color, opacity = 0.35) => {
      const elRad = THREE.MathUtils.degToRad(elDeg);
      const radius = Math.cos(elRad) * DOME_R;
      const y = Math.sin(elRad) * DOME_R;
      const pts = [];
      for (let i = 0; i <= 128; i++) {
        const a = (i / 128) * Math.PI * 2;
        pts.push(
          new THREE.Vector3(Math.cos(a) * radius, y, Math.sin(a) * radius)
        );
      }
      const geo = new THREE.BufferGeometry().setFromPoints(pts);
      return new THREE.Line(
        geo,
        new THREE.LineBasicMaterial({ color, transparent: true, opacity })
      );
    };

    this._scene.add(elevationCircle(10, 0x4a6a8a, 0.25));
    this._scene.add(elevationCircle(30, 0x4a6a8a, 0.3));
    this._scene.add(elevationCircle(60, 0x4a6a8a, 0.3));

    for (let deg = 0; deg < 360; deg += 30) {
      const rad = THREE.MathUtils.degToRad(deg);
      const pts = [];
      for (let i = 0; i <= 32; i++) {
        const elRad = (i / 32) * (Math.PI / 2);
        const r = Math.cos(elRad) * DOME_R;
        const y = Math.sin(elRad) * DOME_R;
        pts.push(
          new THREE.Vector3(Math.sin(rad) * r, y, -Math.cos(rad) * r)
        );
      }
      const geo = new THREE.BufferGeometry().setFromPoints(pts);
      const opacity = deg % 90 === 0 ? 0.3 : 0.12;
      this._scene.add(
        new THREE.Line(
          geo,
          new THREE.LineBasicMaterial({
            color: 0x4a6a8a,
            transparent: true,
            opacity,
          })
        )
      );
    }

    const cardinals = this._cardinalLabels();
    cardinals.forEach((c) => {
      const s = this._makeLabel(c.text, c.color);
      s.position.set(c.x, 0.5, c.z);
      this._scene.add(s);
    });

    [30, 60].forEach((el) => {
      const elRad = THREE.MathUtils.degToRad(el);
      const s = this._makeLabel(el + "°", "#7a9ab5", 48);
      s.scale.set(0.9, 0.9, 1);
      s.position.set(
        Math.cos(elRad) * DOME_R + 0.3,
        Math.sin(elRad) * DOME_R,
        0
      );
      this._scene.add(s);
    });
  }

  _cardinalLabels() {
    const west = this._t("west");
    return [
      { text: "N", x: 0, z: -HORIZON_R - 0.8, color: "#ff8866" },
      { text: "S", x: 0, z: HORIZON_R + 0.8, color: "#88ccff" },
      { text: "E", x: HORIZON_R + 0.8, z: 0, color: "#ffffff" },
      { text: west, x: -HORIZON_R - 0.8, z: 0, color: "#ffffff" },
    ];
  }

  _makeLabel(text, color = "#ffffff", size = 64) {
    const canvas = document.createElement("canvas");
    canvas.width = 128;
    canvas.height = 128;
    const ctx = canvas.getContext("2d");
    ctx.font = "bold " + size + "px sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillStyle = color;
    ctx.fillText(text, 64, 64);
    const tex = new THREE.CanvasTexture(canvas);
    tex.minFilter = THREE.LinearFilter;
    const sprite = new THREE.Sprite(
      new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false })
    );
    sprite.scale.set(1.6, 1.6, 1);
    return sprite;
  }

  _buildHouse() {
    const houseGroup = new THREE.Group();
    this._scene.add(houseGroup);

    const wallMat = new THREE.MeshStandardMaterial({
      color: 0xf0d8b8,
      roughness: 0.85,
    });
    const walls = new THREE.Mesh(new THREE.BoxGeometry(3.5, 2.5, 3.5), wallMat);
    walls.position.y = 1.25;
    walls.castShadow = true;
    walls.receiveShadow = true;
    houseGroup.add(walls);

    const roofMat = new THREE.MeshStandardMaterial({
      color: 0xb04a25,
      roughness: 0.7,
    });
    const roof = new THREE.Mesh(new THREE.ConeGeometry(2.7, 1.8, 4), roofMat);
    roof.position.y = 3.4;
    roof.rotation.y = Math.PI / 4;
    roof.castShadow = true;
    houseGroup.add(roof);

    const facadeRad = THREE.MathUtils.degToRad(this._config.orientation);
    this._facadeRad = facadeRad;
    this._facadeNormal = new THREE.Vector3(
      Math.sin(facadeRad),
      0,
      -Math.cos(facadeRad)
    );

    const windowMat = new THREE.MeshStandardMaterial({
      color: 0x6699cc,
      emissive: 0x223344,
      roughness: 0.2,
      metalness: 0.4,
    });
    const windowMesh = new THREE.Mesh(
      new THREE.PlaneGeometry(1.2, 1.2),
      windowMat
    );
    windowMesh.position.copy(this._facadeNormal).multiplyScalar(1.76);
    windowMesh.position.y = 1.4;
    windowMesh.lookAt(windowMesh.position.clone().add(this._facadeNormal));
    houseGroup.add(windowMesh);
    this._windowMesh = windowMesh;

    const frameMat = new THREE.MeshStandardMaterial({ color: 0xffffff });
    const frameGroup = new THREE.Group();
    const frameThick = 0.06;
    const frameSize = 1.2;
    [
      [0, frameSize / 2, frameSize, frameThick],
      [0, -frameSize / 2, frameSize, frameThick],
      [-frameSize / 2, 0, frameThick, frameSize],
      [frameSize / 2, 0, frameThick, frameSize],
      [0, 0, frameSize, frameThick],
      [0, 0, frameThick, frameSize],
    ].forEach(([x, y, w, h]) => {
      const bar = new THREE.Mesh(new THREE.PlaneGeometry(w, h), frameMat);
      bar.position.set(x, y, 0.001);
      frameGroup.add(bar);
    });
    frameGroup.position.copy(windowMesh.position);
    frameGroup.quaternion.copy(windowMesh.quaternion);
    houseGroup.add(frameGroup);

    const shutterMat = new THREE.MeshStandardMaterial({
      color: 0x3a2f22,
      roughness: 0.9,
    });
    // Match the window's intrinsic height (1.2). With a near-zero
    // intrinsic height the `scale.y = coverage` trick from the
    // standalone HTML rendered the shutter invisible.
    const shutterMesh = new THREE.Mesh(
      new THREE.PlaneGeometry(1.2, 1.2),
      shutterMat
    );
    shutterMesh.position.copy(windowMesh.position);
    shutterMesh.position.add(this._facadeNormal.clone().multiplyScalar(0.005));
    shutterMesh.quaternion.copy(windowMesh.quaternion);
    shutterMesh.visible = false;
    houseGroup.add(shutterMesh);
    this._shutterMesh = shutterMesh;

    houseGroup.add(
      new THREE.ArrowHelper(
        this._facadeNormal,
        new THREE.Vector3()
          .copy(this._facadeNormal)
          .multiplyScalar(1.76)
          .setY(1.4),
        1.5,
        0xffaa44,
        0.3,
        0.2
      )
    );
  }

  _buildIncidenceCone() {
    // The integration's `arc` is the FULL arc width centred on the
    // façade orientation, not a half-angle. We split it in half here.
    const halfAng = THREE.MathUtils.degToRad(this._config.arc / 2);
    // The wedge spans the yearly *solar-noon* elevation envelope
    // at the configured latitude: outside the tropics the bottom
    // sits at the winter solstice noon elevation and the top at
    // the summer solstice noon; inside the tropics (|φ| < 23.45°)
    // the formula is clamped at 90° (sun reaches the zenith on the
    // day the solar declination crosses the latitude). This
    // matches the physical reality of the site much better than
    // the previous min_elevation-to-zenith range.
    let { lowerRad, upperRad } = solsticeBounds(this._config.latitude);
    // Degenerate case (e.g. polar latitude near 90° + cap effects):
    // fall back to [horizon, zenith] so the wedge stays usable.
    if (upperRad - lowerRad < THREE.MathUtils.degToRad(5)) {
      lowerRad = 0;
      upperRad = Math.PI / 2;
    }
    const segments = 24;
    const elSegs = 12;
    const pts = [];
    const indices = [];

    for (let j = 0; j <= elSegs; j++) {
      const elRad = lowerRad + (j / elSegs) * (upperRad - lowerRad);
      const r = Math.cos(elRad) * DOME_R;
      const y = Math.sin(elRad) * DOME_R;
      for (let i = 0; i <= segments; i++) {
        const t = i / segments;
        const azOffset = (t - 0.5) * 2 * halfAng;
        const az = this._facadeRad + azOffset;
        pts.push(Math.sin(az) * r, y, -Math.cos(az) * r);
      }
    }
    for (let j = 0; j < elSegs; j++) {
      for (let i = 0; i < segments; i++) {
        const a = j * (segments + 1) + i;
        const b = a + 1;
        const c = a + (segments + 1);
        const d = c + 1;
        indices.push(a, c, b, b, c, d);
      }
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
    geo.setIndex(indices);
    geo.computeVertexNormals();
    const mat = new THREE.MeshBasicMaterial({
      color: 0xffaa44,
      transparent: true,
      // Initial opacity for the brief window before the first
      // _updateSun() call. After that the value is overwritten on
      // every refresh with one of {0.40 in-axis, 0.32 grazing, 0.18
      // out / night}.
      opacity: 0.22,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    this._coneMesh = new THREE.Mesh(geo, mat);
    this._scene.add(this._coneMesh);

    // Outline tubes (bottom arc + two slanted edges + top arc) for
    // definition. Kept in a stable color so the wedge stays readable
    // even when the fill darkens (out-of-axis state). The top arc
    // closes the polygon — the slanted edges no longer converge at
    // the zenith now that the cone tops out at upperRad < π/2.
    const outlineMat = new THREE.MeshBasicMaterial({ color: 0xffd089 });
    const tubeRadius = 0.05;
    const arcSegs = 36;

    const arcAtElevation = (elRad) => {
      const pts = [];
      for (let i = 0; i <= arcSegs; i++) {
        const t = i / arcSegs;
        const az = this._facadeRad + (t - 0.5) * 2 * halfAng;
        const r = Math.cos(elRad) * DOME_R;
        const y = Math.sin(elRad) * DOME_R;
        pts.push(new THREE.Vector3(Math.sin(az) * r, y, -Math.cos(az) * r));
      }
      return pts;
    };

    for (const elRad of [lowerRad, upperRad]) {
      const pts = arcAtElevation(elRad);
      if (pts.length < 2) continue;
      const curve = new THREE.CatmullRomCurve3(pts);
      const geoArc = new THREE.TubeGeometry(
        curve, arcSegs, tubeRadius, 6, false
      );
      this._scene.add(new THREE.Mesh(geoArc, outlineMat));
    }

    for (const sign of [-1, 1]) {
      const az = this._facadeRad + sign * halfAng;
      const edgeSegs = 16;
      const edgePts = [];
      for (let i = 0; i <= edgeSegs; i++) {
        const elRad = lowerRad + (i / edgeSegs) * (upperRad - lowerRad);
        const r = Math.cos(elRad) * DOME_R;
        const y = Math.sin(elRad) * DOME_R;
        edgePts.push(new THREE.Vector3(Math.sin(az) * r, y, -Math.cos(az) * r));
      }
      const edgeCurve = new THREE.CatmullRomCurve3(edgePts);
      const edgeGeo = new THREE.TubeGeometry(
        edgeCurve, edgeSegs, tubeRadius, 6, false
      );
      this._scene.add(new THREE.Mesh(edgeGeo, outlineMat));
    }
  }

  _buildSun() {
    this._sunGroup = new THREE.Group();
    this._scene.add(this._sunGroup);

    this._sunGroup.add(
      new THREE.Mesh(
        new THREE.SphereGeometry(0.5, 24, 24),
        new THREE.MeshBasicMaterial({ color: 0xffe066 })
      )
    );
    this._sunGroup.add(
      new THREE.Mesh(
        new THREE.SphereGeometry(0.9, 24, 24),
        new THREE.MeshBasicMaterial({
          color: 0xffaa44,
          transparent: true,
          opacity: 0.25,
        })
      )
    );

    const rayGeo = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(),
      new THREE.Vector3(),
    ]);
    this._rayMat = new THREE.LineBasicMaterial({
      color: 0xffd966,
      transparent: true,
      opacity: 0.6,
    });
    this._rayLine = new THREE.Line(rayGeo, this._rayMat);
    this._scene.add(this._rayLine);
  }

  _buildDayPath() {
    if (this._config.latitude === null || this._config.latitude === undefined) {
      return;
    }
    const today = new Date();
    const pts = [];
    for (let h = 0; h <= 24 * 4; h++) {
      const t = new Date(
        today.getFullYear(),
        today.getMonth(),
        today.getDate(),
        0,
        h * 15,
        0
      );
      const sp = solarPosition(
        t,
        this._config.latitude,
        this._config.longitude || 0
      );
      if (sp.elevation < 0) continue;
      pts.push(azElToVec3(sp.azimuth, sp.elevation, DOME_R));
    }
    if (pts.length < 2) return;
    // Day path as a tube so the trace stands out against the dome
    // grid; CatmullRom keeps the curve smooth between the 15-min
    // sample points.
    const curve = new THREE.CatmullRomCurve3(pts);
    const tubeGeo = new THREE.TubeGeometry(curve, pts.length * 2, 0.07, 8, false);
    this._scene.add(
      new THREE.Mesh(
        tubeGeo,
        new THREE.MeshBasicMaterial({
          color: 0xffaa44,
          transparent: true,
          opacity: 0.7,
        })
      )
    );
  }

  // ----------------------------------------------------------------
  // Rendering loop + reactive updates
  // ----------------------------------------------------------------

  _animate() {
    if (!this._built) return;
    this._animFrame = requestAnimationFrame(() => this._animate());
    this._controls.update();
    this._renderer.render(this._scene, this._camera);
  }

  _handleResize() {
    if (!this._renderer || !this._wrap) return;
    const w = Math.max(this._wrap.clientWidth, 200);
    const h = Math.max(this._wrap.clientHeight, 200);
    this._camera.aspect = w / h;
    this._camera.updateProjectionMatrix();
    this._renderer.setSize(w, h);
  }

  _refreshFromHass() {
    const sun = this._hass.states["sun.sun"];
    let az;
    let el;
    if (sun) {
      az = parseFloat(sun.attributes.azimuth);
      el = parseFloat(sun.attributes.elevation);
    }
    if (Number.isFinite(az) && Number.isFinite(el)) {
      this._update(az, el);
      return;
    }
    if (this._config.latitude !== null && this._config.latitude !== undefined) {
      const sp = solarPosition(
        new Date(),
        this._config.latitude,
        this._config.longitude || 0
      );
      this._update(sp.azimuth, sp.elevation);
    }
  }

  _update(az, el) {
    const cls = this._classify(az, el);
    const coverState = this._aggregateCoverState();
    this._updateSun(az, el, cls);
    this._updateShutter(coverState, cls);
  }

  _updateSun(az, el, cls) {
    const delta = angleDelta(az, this._config.orientation);

    const sunPos = azElToVec3(az, el, DOME_R);
    this._sunGroup.position.copy(sunPos);
    this._sunGroup.visible = el > -3;

    this._sunLight.position.copy(sunPos);
    this._sunLight.target.position.set(0, 0, 0);
    this._sunLight.intensity = el > 0 ? Math.min(1, el / 30) : 0;

    const winPos = new THREE.Vector3()
      .copy(this._facadeNormal)
      .multiplyScalar(1.76)
      .setY(1.4);
    const positions = this._rayLine.geometry.attributes.position.array;
    positions[0] = sunPos.x;
    positions[1] = sunPos.y;
    positions[2] = sunPos.z;
    positions[3] = winPos.x;
    positions[4] = winPos.y;
    positions[5] = winPos.z;
    this._rayLine.geometry.attributes.position.needsUpdate = true;
    this._rayLine.visible = el > 0 && Math.abs(delta) < 90;
    this._rayMat.opacity = cls.state === "axis" ? 0.8 : 0.35;
    this._rayMat.color.setHex(cls.state === "axis" ? 0xffaa44 : 0xffd966);

    this._coneMesh.material.color.setHex(
      cls.state === "axis"
        ? 0xff6644
        : cls.state === "grazing"
        ? 0xffaa44
        : 0x4488aa
    );
    this._coneMesh.material.opacity =
      cls.state === "axis"
        ? 0.4
        : cls.state === "grazing"
        ? 0.32
        : 0.18;

    const r = this._uiRefs;
    r.azValue.textContent = Math.round(az) + "°";
    r.elValue.textContent =
      this._t("elevation_prefix") + " " + Math.round(el) + "°";
    r.facadeValue.textContent = this._config.orientation + "°";
    r.deltaValue.textContent = "Δ " + Math.round(delta) + "°";
  }

  _updateShutter(coverState, cls) {
    // Real cover state wins over the sun-based heuristic. The
    // classification ``cls`` is only kept as a fallback when no
    // covers are configured (rare) so the visual still says
    // something meaningful.
    let coverage;
    let label;
    let sub;
    let cssClass;

    if (coverState !== null) {
      coverage = coverState.coverage;
      const avg = coverState.averagePosition;
      if (avg >= 95) {
        label = this._t("open");
        cssClass = "status-open";
      } else if (avg <= 5) {
        label = this._t("closed");
        cssClass = "status-close";
      } else {
        label = this._tFmt("partial_open", { pct: Math.round(avg) });
        cssClass = avg < 50 ? "status-warn" : "status-open";
      }
      sub = this._tFmt(
        coverState.count > 1 ? "cover_count_plural" : "cover_count_singular",
        { n: coverState.count, known: coverState.known }
      );
    } else {
      coverage = cls.coverage;
      label = cls.label;
      sub = cls.sub;
      cssClass = cls.cssClass;
    }

    if (coverage > 0.005) {
      this._shutterMesh.visible = true;
      this._shutterMesh.scale.y = coverage;
      this._shutterMesh.position.copy(this._windowMesh.position);
      this._shutterMesh.position.add(
        this._facadeNormal.clone().multiplyScalar(0.005)
      );
      this._shutterMesh.position.y = 1.4 + 0.6 - (1.2 * coverage) / 2;
    } else {
      this._shutterMesh.visible = false;
    }

    const r = this._uiRefs;
    r.statusValue.textContent = label;
    r.statusValue.className = "value " + cssClass;
    r.statusSub.textContent = sub;
  }

  _aggregateCoverState() {
    // Walk ``this._config.covers``, read each cover's HA state and
    // produce an aggregate `{averagePosition, coverage, count, known}`.
    // Returns ``null`` when no cover state is usable (no config, or
    // all covers unknown / unavailable) so the caller can fall back
    // to the sun-based heuristic.
    const covers = this._config.covers || [];
    if (!covers.length || !this._hass) return null;

    const positions = [];
    for (const id of covers) {
      const s = this._hass.states[id];
      if (!s) continue;
      // HA can retain ``current_position`` on a cover even after the
      // entity drops to ``unavailable`` / ``unknown`` — which would
      // otherwise let stale numeric data sneak into the aggregate.
      // Skip those states up front.
      if (s.state === "unavailable" || s.state === "unknown") continue;
      const attrPos = s.attributes && s.attributes.current_position;
      let pos;
      if (typeof attrPos === "number" && Number.isFinite(attrPos)) {
        pos = attrPos;
      } else if (s.state === "open" || s.state === "opening") {
        pos = 100;
      } else if (s.state === "closed" || s.state === "closing") {
        pos = 0;
      } else {
        continue;
      }
      positions.push(pos);
    }
    if (!positions.length) return null;

    const avg = positions.reduce((a, b) => a + b, 0) / positions.length;
    return {
      averagePosition: avg,
      coverage: Math.max(0, Math.min(1, 1 - avg / 100)),
      count: covers.length,
      known: positions.length,
    };
  }

  _tFmt(key, vars) {
    let s = this._t(key);
    for (const [k, v] of Object.entries(vars || {})) {
      s = s.replace("{" + k + "}", String(v));
    }
    return s;
  }

  _classify(az, el) {
    // Use the integration's arc as the half-arc of the close zone, and
    // arc + 30° as the grazing boundary. The numeric coverage is just
    // for the visual representation of the shutter, the integration
    // itself has its own decision engine driven by lux/temp/UV.
    const arcHalf = this._config.arc / 2;
    const grazing = arcHalf + 30;
    if (el < this._config.min_elevation) {
      return {
        state: "night",
        label: this._t("open"),
        sub: el < 0 ? this._t("sun_set") : this._t("sun_low"),
        cssClass: "status-open",
        coverage: 0,
      };
    }
    const d = Math.abs(angleDelta(az, this._config.orientation));
    if (d < arcHalf) {
      return {
        state: "axis",
        label: this._t("close_high"),
        sub: this._t("sun_in_axis"),
        cssClass: "status-close",
        coverage: 0.7,
      };
    }
    if (d < grazing) {
      return {
        state: "grazing",
        label: this._t("close_low"),
        sub: this._t("sun_grazing"),
        cssClass: "status-warn",
        coverage: 0.3,
      };
    }
    return {
      state: "out",
      label: this._t("open"),
      sub: this._t("sun_out_of_axis"),
      cssClass: "status-open",
      coverage: 0,
    };
  }

  _t(key) {
    const labels = this._config.labels || {};
    return labels[key] !== undefined ? labels[key] : DEFAULT_LABELS[key];
  }

  // ----------------------------------------------------------------
  // Teardown
  // ----------------------------------------------------------------

  _teardown() {
    if (this._animFrame) {
      cancelAnimationFrame(this._animFrame);
      this._animFrame = null;
    }
    if (this._resizeObserver) {
      this._resizeObserver.disconnect();
      this._resizeObserver = null;
    }
    if (this._controls) {
      // OrbitControls registers DOM listeners on the renderer canvas;
      // dispose() is the only way to detach them.
      this._controls.dispose();
      this._controls = null;
    }
    if (this._scene) {
      // Walk the scene graph and free every disposable resource so
      // setConfig() rebuilds do not leak GPU buffers / textures.
      this._scene.traverse((obj) => {
        if (obj.geometry) obj.geometry.dispose();
        if (obj.material) {
          const mats = Array.isArray(obj.material)
            ? obj.material
            : [obj.material];
          for (const mat of mats) {
            if (mat.map) mat.map.dispose();
            mat.dispose();
          }
        }
      });
      this._scene.clear();
      this._scene = null;
    }
    if (this._renderer) {
      this._renderer.dispose();
      this._renderer.domElement.remove();
      this._renderer = null;
    }
    this._camera = null;
    this._sunLight = null;
    this._sunGroup = null;
    this._coneMesh = null;
    this._shutterMesh = null;
    this._windowMesh = null;
    this._rayLine = null;
    this._rayMat = null;
    this._built = false;
  }

  disconnectedCallback() {
    this._teardown();
  }

  connectedCallback() {
    if (this._config && !this._built) {
      this._build();
      if (this._hass) {
        this._refreshFromHass();
      }
    }
  }
}

const DEFAULT_LABELS = {
  shutter: "Volet",
  sun: "Soleil",
  facade: "Façade",
  west: "O",
  open: "Ouvert",
  closed: "Fermé",
  partial_open: "{pct}% ouvert",
  cover_count_singular: "{known}/{n} volet",
  cover_count_plural: "{known}/{n} volets",
  close_high: "Fermer 70%",
  close_low: "Fermer 30%",
  sun_set: "soleil couché",
  sun_low: "soleil bas",
  sun_in_axis: "soleil dans l'axe",
  sun_grazing: "soleil rasant",
  sun_out_of_axis: "hors axe",
  elevation_prefix: "élévation",
  hint: "Glisser : rotation · Molette : zoom · Clic-droit : pan",
};

// ---------------------------------------------------------------------------
// Helpers (pure, kept module-level so they can be unit-tested manually)
// ---------------------------------------------------------------------------

// Earth's axial tilt — used to derive the yearly noon-elevation
// envelope from a single latitude. Practical accuracy: ±0.05° vs.
// the precise 23.4393° value, well within rendering tolerance.
const AXIAL_TILT_DEG = 23.45;

function solsticeBounds(latDeg) {
  // Returns the yearly envelope of solar elevations *at solar noon*
  // for the given latitude, in radians. The two extremes occur on
  // the solstices outside the tropics; inside the tropics
  // (|φ| < 23.45°), the maximum is reached when the declination
  // crosses the latitude (sun overhead) and the formula is clamped
  // at 90°. The output bounds the wedge so it never claims a
  // region the sun cannot reach at noon throughout the year:
  //   upper = clamp(90 - |φ| + 23.45, 0..90)
  //   lower = clamp(90 - |φ| - 23.45, 0..90)
  // Defensive about non-finite input (string, NaN, Infinity, ...) —
  // such values would cascade NaN into Three.js geometry.
  const lat = Number(latDeg);
  if (!Number.isFinite(lat)) {
    return { lowerRad: 0, upperRad: Math.PI / 2 };
  }
  const phi = Math.min(90, Math.abs(lat));
  const upperDeg = Math.min(90, 90 - phi + AXIAL_TILT_DEG);
  const lowerDeg = Math.max(0, 90 - phi - AXIAL_TILT_DEG);
  return {
    lowerRad: THREE.MathUtils.degToRad(lowerDeg),
    upperRad: THREE.MathUtils.degToRad(upperDeg),
  };
}

function angleDelta(a, b) {
  return ((a - b + 540) % 360) - 180;
}

function azElToVec3(azDeg, elDeg, r) {
  const az = THREE.MathUtils.degToRad(azDeg);
  const el = THREE.MathUtils.degToRad(elDeg);
  return new THREE.Vector3(
    Math.sin(az) * Math.cos(el) * r,
    Math.sin(el) * r,
    -Math.cos(az) * Math.cos(el) * r
  );
}

function dayOfYear(d) {
  const start = new Date(d.getFullYear(), 0, 0);
  return Math.floor((d - start) / 86400000);
}

function solarPosition(date, lat, lon = 0) {
  // Simplified NOAA algorithm; ~1° precision is plenty for the viz.
  // ``lon`` is the site's longitude in degrees east (HA stores
  // ``hass.config.longitude`` with the same sign convention). The
  // local-solar-time correction needs both ``lon`` and the time-zone
  // meridian (``lstm``) to align the path with the actual day at the
  // user's location; without it the trajectory was offset by up to
  // ±15° in azimuth depending on the site.
  const n = dayOfYear(date);
  const decl = THREE.MathUtils.degToRad(
    23.45 * Math.sin((2 * Math.PI * (284 + n)) / 365)
  );
  const latRad = THREE.MathUtils.degToRad(lat);
  const B = (2 * Math.PI * (n - 81)) / 364;
  const E = 9.87 * Math.sin(2 * B) - 7.53 * Math.cos(B) - 1.5 * Math.sin(B);
  const localTime =
    date.getHours() + date.getMinutes() / 60 + date.getSeconds() / 3600;
  const tz = -date.getTimezoneOffset() / 60;
  const lstm = 15 * tz;
  const tc = 4 * (lon - lstm) + E;
  const solarTime = localTime + tc / 60;
  const H = THREE.MathUtils.degToRad(15 * (solarTime - 12));
  const sinEl =
    Math.sin(latRad) * Math.sin(decl) +
    Math.cos(latRad) * Math.cos(decl) * Math.cos(H);
  const el = Math.asin(sinEl);
  const cosAz =
    (Math.sin(decl) - Math.sin(el) * Math.sin(latRad)) /
    (Math.cos(el) * Math.cos(latRad));
  let az = Math.acos(Math.max(-1, Math.min(1, cosAz)));
  if (H > 0) az = 2 * Math.PI - az;
  return {
    azimuth: THREE.MathUtils.radToDeg(az),
    elevation: THREE.MathUtils.radToDeg(el),
  };
}

if (!customElements.get("shutters-sun-3d-card")) {
  customElements.define("shutters-sun-3d-card", ShuttersSun3dCard);
}

window.customCards = window.customCards || [];
if (!window.customCards.find((c) => c.type === "shutters-sun-3d-card")) {
  window.customCards.push({
    type: "shutters-sun-3d-card",
    name: "Shutters Sun 3D",
    description:
      "3D sun + window visualization for the Shutters Management integration.",
  });
}
