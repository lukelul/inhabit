import * as THREE from "three";

// Shared mouse state — updated once, read by all scroll arm scenes
const mouse = { clientX: window.innerWidth * 0.5, clientY: window.innerHeight * 0.5 };

window.addEventListener("mousemove", (e) => {
  mouse.clientX = e.clientX;
  mouse.clientY = e.clientY;
});
window.addEventListener("touchmove", (e) => {
  if (e.touches[0]) { mouse.clientX = e.touches[0].clientX; mouse.clientY = e.touches[0].clientY; }
}, { passive: true });

// ─── Per-type materials ─────────────────────────────────────────────
function makeMats(type) {
  if (type === "so101") {
    return {
      body:    new THREE.MeshStandardMaterial({ color: 0x728898, metalness: 0.55, roughness: 0.38 }),
      joint:   new THREE.MeshStandardMaterial({ color: 0x1e2d38, metalness: 0.55,  roughness: 0.42, emissive: 0x8ff0dc, emissiveIntensity: 0.1 }),
      accent:  new THREE.MeshStandardMaterial({ color: 0x8ff0dc, metalness: 0.4,  roughness: 0.28, emissive: 0x3fa890, emissiveIntensity: 0.32 }),
      reticle: new THREE.MeshBasicMaterial({ color: 0x8ff0dc, transparent: true, opacity: 0.55, depthWrite: false }),
    };
  }
  // ur
  return {
    body:    new THREE.MeshStandardMaterial({ color: 0xcfd8dc, metalness: 0.6, roughness: 0.28 }),
    joint:   new THREE.MeshStandardMaterial({ color: 0x14202a, metalness: 0.75, roughness: 0.3, emissive: 0x3cc8ff, emissiveIntensity: 0.14 }),
    accent:  new THREE.MeshStandardMaterial({ color: 0x3cc8ff, metalness: 0.3, roughness: 0.28,  emissive: 0x1e8fb8, emissiveIntensity: 0.38 }),
    reticle: new THREE.MeshBasicMaterial({ color: 0x3cc8ff, transparent: true, opacity: 0.5, depthWrite: false }),
  };
}

// ─── Scene builder ─────────────────────────────────────────────────
function buildScrollArm(canvasEl, type) {
  if (!canvasEl) return null;

  const L1 = 2.9, L2 = 2.3;
  const SHOULDER_Y = -1.9;
  const SMOOTH = 0.14;
  const MAX_ANGULAR_SPEED = 4.0; // rad/s — caps how fast joints can chase a target that jumped far

  const renderer = new THREE.WebGLRenderer({ canvas: canvasEl, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;

  const scene = new THREE.Scene();

  const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 80);
  camera.position.set(0, 0.4, 10);
  camera.lookAt(0, 0.1, 0);

  // Lights
  {
    const d1 = new THREE.DirectionalLight(0x9fd8ff, 1.9); d1.position.set(4, 6, 5); scene.add(d1);
    const d2 = new THREE.DirectionalLight(0x3cc8ff, 1.3); d2.position.set(-5, 2, -4); scene.add(d2);
    scene.add(new THREE.AmbientLight(0x1a2530, 1.3));
  }

  const mat = makeMats(type);
  const mk = (geo, material) => new THREE.Mesh(geo, material);

  // ─── Rig ─────────────────────────────────────────────────────────
  const rig = new THREE.Group();
  rig.scale.setScalar(type === "ur" ? 1.1 : 1.0);
  // SO-101 on left, UR on right — slight offset so they don't center-block the text
  rig.position.set(type === "ur" ? 1.4 : -1.4, 0.4, 0);
  scene.add(rig);

  if (type === "so101") {
    // Box-style base (low-cost arm aesthetic)
    const base = mk(new THREE.BoxGeometry(1.5, 0.28, 1.5), mat.body);
    base.position.set(0, -2.5, 0);
    rig.add(base);
    const baseRing = mk(new THREE.TorusGeometry(0.76, 0.03, 8, 32), mat.accent);
    baseRing.rotation.x = Math.PI / 2;
    baseRing.position.set(0, -2.36, 0);
    rig.add(baseRing);
  } else {
    // Round-flange UR base
    const base = mk(new THREE.CylinderGeometry(0.95, 1.15, 0.55, 32), mat.body);
    base.position.set(0, -2.55, 0);
    rig.add(base);
    const flange = mk(new THREE.CylinderGeometry(0.98, 0.98, 0.09, 32), mat.joint);
    flange.position.set(0, -2.3, 0);
    rig.add(flange);
    const baseRing = mk(new THREE.TorusGeometry(0.97, 0.048, 8, 40), mat.accent);
    baseRing.rotation.x = Math.PI / 2;
    baseRing.position.set(0, -2.26, 0);
    rig.add(baseRing);
  }

  // Shoulder
  const shoulderGrp = new THREE.Group();
  shoulderGrp.position.set(0, SHOULDER_Y, 0);
  rig.add(shoulderGrp);

  if (type === "so101") {
    shoulderGrp.add(mk(new THREE.BoxGeometry(0.6, 0.6, 0.6), mat.joint));
  } else {
    shoulderGrp.add(mk(new THREE.SphereGeometry(0.42, 22, 22), mat.joint));
    const sRing = mk(new THREE.TorusGeometry(0.46, 0.055, 8, 32), mat.accent);
    sRing.rotation.x = Math.PI / 2;
    shoulderGrp.add(sRing);
  }

  // Upper arm
  const upperArmPivot = new THREE.Group();
  shoulderGrp.add(upperArmPivot);

  if (type === "so101") {
    // Thin capsule — slender low-cost arm
    const ua = mk(new THREE.CapsuleGeometry(0.12, L1, 6, 12), mat.body);
    ua.position.set(L1 * 0.5, 0, 0);
    ua.rotation.z = Math.PI / 2;
    upperArmPivot.add(ua);
  } else {
    // Thicker UR-style cylindrical link
    const ua = mk(new THREE.CylinderGeometry(0.3, 0.3, L1, 18), mat.body);
    ua.position.set(L1 * 0.5, 0, 0);
    ua.rotation.z = Math.PI / 2;
    upperArmPivot.add(ua);
    // Mid-link accent band
    const band = mk(new THREE.CylinderGeometry(0.305, 0.305, 0.065, 18), mat.accent);
    band.position.set(L1 * 0.5, 0, 0);
    band.rotation.z = Math.PI / 2;
    upperArmPivot.add(band);
  }

  // Elbow
  const elbowGrp = new THREE.Group();
  elbowGrp.position.set(L1, 0, 0);
  upperArmPivot.add(elbowGrp);

  if (type === "so101") {
    elbowGrp.add(mk(new THREE.BoxGeometry(0.48, 0.48, 0.48), mat.joint));
  } else {
    elbowGrp.add(mk(new THREE.SphereGeometry(0.33, 20, 20), mat.joint));
    const eRing = mk(new THREE.TorusGeometry(0.37, 0.055, 8, 32), mat.accent);
    eRing.rotation.x = Math.PI / 2;
    elbowGrp.add(eRing);
  }

  // Forearm
  const forearmPivot = new THREE.Group();
  elbowGrp.add(forearmPivot);

  if (type === "so101") {
    const fa = mk(new THREE.CapsuleGeometry(0.09, L2, 6, 12), mat.body);
    fa.position.set(L2 * 0.5, 0, 0);
    fa.rotation.z = Math.PI / 2;
    forearmPivot.add(fa);
  } else {
    const fa = mk(new THREE.CylinderGeometry(0.24, 0.24, L2, 18), mat.body);
    fa.position.set(L2 * 0.5, 0, 0);
    fa.rotation.z = Math.PI / 2;
    forearmPivot.add(fa);
  }

  // Wrist / end effector
  const wristGrp = new THREE.Group();
  wristGrp.position.set(L2, 0, 0);
  forearmPivot.add(wristGrp);

  if (type === "so101") {
    wristGrp.add(mk(new THREE.BoxGeometry(0.38, 0.28, 0.38), mat.joint));
    const f1 = mk(new THREE.BoxGeometry(0.44, 0.06, 0.08), mat.accent);
    f1.position.set(0.32, 0.1, 0.11);
    wristGrp.add(f1);
    const f2 = mk(new THREE.BoxGeometry(0.44, 0.06, 0.08), mat.accent);
    f2.position.set(0.32, 0.1, -0.11);
    wristGrp.add(f2);
  } else {
    wristGrp.add(mk(new THREE.SphereGeometry(0.22, 16, 16), mat.joint));
    const wRing = mk(new THREE.TorusGeometry(0.26, 0.046, 6, 28), mat.accent);
    wRing.rotation.x = Math.PI / 2;
    wristGrp.add(wRing);
    const grip = mk(new THREE.BoxGeometry(0.32, 0.2, 0.42), mat.body);
    grip.position.set(0.26, 0, 0);
    wristGrp.add(grip);
    const f1 = mk(new THREE.BoxGeometry(0.5, 0.08, 0.1), mat.accent);
    f1.position.set(0.65, 0.09, 0.14);
    wristGrp.add(f1);
    const f2 = mk(new THREE.BoxGeometry(0.5, 0.08, 0.1), mat.accent);
    f2.position.set(0.65, 0.09, -0.14);
    wristGrp.add(f2);
  }

  // Reticle
  const reticle = new THREE.Group();
  reticle.position.set(2, 0, 0.5);
  scene.add(reticle);
  reticle.add(mk(new THREE.TorusGeometry(0.16, 0.009, 8, 36), mat.reticle));
  reticle.add(mk(new THREE.BoxGeometry(0.28, 0.005, 0.005), mat.reticle));
  reticle.add(mk(new THREE.BoxGeometry(0.005, 0.28, 0.005), mat.reticle));

  // Grid
  const GROUND_Y = -2.6;
  const grid = new THREE.GridHelper(14, 14, 0x112d3a, 0x0a1d26);
  grid.position.y = GROUND_Y;
  scene.add(grid);

  // Lowest IK target height (rig-local, unscaled units), clamped above the
  // grid with clearance for the gripper mesh so the arm never visibly reaches
  // into the floor. rig.scale divides out since L1/L2/SHOULDER_Y are unscaled.
  const MIN_LOCAL_Y = (GROUND_Y - rig.position.y) / rig.scale.x + 0.5;

  // Particles (sparse for section backgrounds)
  {
    const NP = 100;
    const buf = new Float32Array(NP * 3);
    let seed = type === "so101" ? 2468 : 9753;
    const rng = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
    for (let i = 0; i < NP; i++) {
      buf[i * 3]     = (rng() - 0.5) * 16;
      buf[i * 3 + 1] = (rng() - 0.5) * 9;
      buf[i * 3 + 2] = (rng() - 0.5) * 10;
    }
    const pg = new THREE.BufferGeometry();
    pg.setAttribute("position", new THREE.BufferAttribute(buf, 3));
    scene.add(new THREE.Points(pg, new THREE.PointsMaterial({
      color: type === "so101" ? 0x8ff0dc : 0x3cc8ff,
      size: 0.018, transparent: true, opacity: 0.3, sizeAttenuation: true,
    })));
  }

  // ─── IK state ─────────────────────────────────────────────────────
  let th1 = 0.3, th2 = -0.75;

  // IK solver (same cosine rule)
  function solveIK(tx, ty) {
    const d  = Math.hypot(tx, ty);
    const dC = Math.max(Math.abs(L1 - L2) + 0.01, Math.min(L1 + L2 - 0.01, d));
    const s  = d > 0.001 ? dC / d : 1;
    const txC = tx * s, tyC = ty * s;
    const cosA = (L1*L1 + L2*L2 - dC*dC) / (2*L1*L2);
    const alpha = Math.acos(Math.max(-1, Math.min(1, cosA)));
    const cosB = (L1*L1 + dC*dC - L2*L2) / (2*L1*dC);
    const beta  = Math.acos(Math.max(-1, Math.min(1, cosB)));
    let theta1 = Math.atan2(tyC, txC) + beta;
    let theta2 = -(Math.PI - alpha);

    // Floor clamp — bound elbow and wrist heights directly so the arm
    // never dips below the grid regardless of how the IK projection scaled.
    const elbowFloorRatio = Math.max(-1, Math.min(1, (MIN_LOCAL_Y - SHOULDER_Y) / L1));
    const theta1Min = Math.asin(elbowFloorRatio);
    if (theta1 < theta1Min) theta1 = theta1Min;

    const elbowY = SHOULDER_Y + L1 * Math.sin(theta1);
    const wristFloorRatio = Math.max(-1, Math.min(1, (MIN_LOCAL_Y - elbowY) / L2));
    const sumMin = Math.asin(wristFloorRatio);
    let sum = theta1 + theta2;
    if (sum < sumMin) sum = sumMin;
    theta2 = sum - theta1;

    return { theta1, theta2 };
  }

  // Raycast helpers
  const raycaster  = new THREE.Raycaster();
  const ndcV       = new THREE.Vector2();
  const planeNorm  = new THREE.Vector3();
  const shoulderWP = new THREE.Vector3();
  const ikPlane    = new THREE.Plane();
  const worldHit   = new THREE.Vector3();
  const invRig     = new THREE.Matrix4();
  const localHit   = new THREE.Vector3();

  function computeIK() {
    rig.updateMatrixWorld();
    shoulderGrp.getWorldPosition(shoulderWP);
    planeNorm.set(0, 0, 1).applyQuaternion(rig.quaternion).normalize();
    ikPlane.setFromNormalAndCoplanarPoint(planeNorm, shoulderWP);
    const rect = canvasEl.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return null;
    ndcV.x =  ((mouse.clientX - rect.left) / rect.width)  * 2 - 1;
    ndcV.y = -(((mouse.clientY - rect.top)  / rect.height) * 2 - 1);
    raycaster.setFromCamera(ndcV, camera);
    if (!raycaster.ray.intersectPlane(ikPlane, worldHit)) return null;
    invRig.copy(rig.matrixWorld).invert();
    localHit.copy(worldHit).applyMatrix4(invRig);
    localHit.y = Math.max(localHit.y, MIN_LOCAL_Y);
    return solveIK(localHit.x, localHit.y - SHOULDER_Y);
  }

  // ─── Resize ─────────────────────────────────────────────────────────
  function resize() {
    const section = canvasEl.closest(".section") || canvasEl.parentElement;
    const w = section ? section.clientWidth  : 800;
    const h = section ? section.clientHeight : 600;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }

  let resizeTimer;
  window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(resize, 120); });

  // ─── Render loop ─────────────────────────────────────────────────────
  let animId  = null;
  let running = false;
  let prevT   = 0;
  let rotY    = type === "ur" ? -0.4 : 0.5;
  let cursorInSection = false; // auto-spins until the cursor is over this section

  function tick(now) {
    if (!running) return;
    animId = requestAnimationFrame(tick);
    const t  = now * 0.001;
    const dt = Math.min(t - prevT, 0.05);
    prevT = t;

    // Rig auto-spins until the cursor is over this section, then holds
    // steady so IK tracking reads clearly.
    if (!cursorInSection) rotY += 0.07 * dt;
    rig.rotation.y = rotY;
    camera.position.x = Math.sin(t * 0.25) * 0.35;
    camera.position.y = 0.4 + Math.sin(t * 0.18) * 0.12;
    camera.lookAt(0, 0.1, 0);
    camera.updateMatrixWorld();

    // IK, rate-limited so a target that jumps far can't snap the arm there
    // in one frame (e.g. mouse crossing quickly into/out of this section)
    const ik = computeIK();
    if (ik) {
      const maxDelta = MAX_ANGULAR_SPEED * dt;
      th1 += Math.max(-maxDelta, Math.min(maxDelta, (ik.theta1 - th1) * SMOOTH));
      th2 += Math.max(-maxDelta, Math.min(maxDelta, (ik.theta2 - th2) * SMOOTH));
      reticle.position.x += (worldHit.x - reticle.position.x) * 0.1;
      reticle.position.y += (worldHit.y - reticle.position.y) * 0.1;
      reticle.position.z += (worldHit.z - reticle.position.z) * 0.1;
    }
    upperArmPivot.rotation.z = th1;
    forearmPivot.rotation.z  = th2;
    wristGrp.rotation.z      = -0.12 * Math.sin(t * 0.9);

    // Breathing
    mat.accent.emissiveIntensity  = 0.65 + Math.sin(t * 1.8) * 0.25;
    mat.joint.emissiveIntensity   = 0.22 + Math.sin(t * 1.2 + 1) * 0.1;
    mat.reticle.opacity           = 0.5  + Math.sin(t * 2.5) * 0.22;
    reticle.lookAt(camera.position);
    reticle.scale.setScalar(1 + Math.sin(t * 2.5) * 0.07);

    renderer.render(scene, camera);
  }

  function start() {
    if (running) return;
    running = true;
    resize();
    requestAnimationFrame(tick);
  }

  function stop() {
    running = false;
    if (animId) cancelAnimationFrame(animId);
  }

  // Only render when section is in view
  const target = canvasEl.closest(".section") || canvasEl.parentElement;
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((e) => { if (e.isIntersecting) start(); else stop(); });
  }, { threshold: 0.05 });
  observer.observe(target);

  target.addEventListener("mouseenter", () => { cursorInSection = true; });
  target.addEventListener("mouseleave", () => { cursorInSection = false; });

  return { start, stop };
}

// ─── Init ──────────────────────────────────────────────────────────
buildScrollArm(document.getElementById("armPlatform"), "so101");
buildScrollArm(document.getElementById("armKernel"),   "ur");
