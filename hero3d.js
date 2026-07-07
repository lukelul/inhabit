import * as THREE from "three";

// ─── Constants ─────────────────────────────────────────────────────
const L1 = 3.2;           // upper arm (shoulder → elbow)
const L2 = 2.6;           // forearm (elbow → wrist tip)
const SHOULDER_Y = -2.2;  // shoulder in rig local space
const SMOOTH = 0.18;
const MAX_ANGULAR_SPEED = 4.0; // rad/s — caps how fast joints can chase a target that jumped far

// ─── Renderer ──────────────────────────────────────────────────────
const canvas = document.getElementById("hero3d");
if (!canvas) throw new Error("hero3d canvas missing");

const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;

const scene = new THREE.Scene();

const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 120);
camera.position.set(0, 0.8, 10.5);
camera.lookAt(0, 0.4, 0);

// ─── Lights ────────────────────────────────────────────────────────
const dl1 = new THREE.DirectionalLight(0x9fd8ff, 2.4);
dl1.position.set(4, 6, 5);
scene.add(dl1);

const dl2 = new THREE.DirectionalLight(0x3cc8ff, 1.8);
dl2.position.set(-5, 2, -4);
scene.add(dl2);

scene.add(new THREE.AmbientLight(0x1a2530, 1.5));

// ─── Materials ─────────────────────────────────────────────────────
const matBody   = new THREE.MeshStandardMaterial({ color: 0x2a343b, metalness: 0.75, roughness: 0.28 });
const matJoint  = new THREE.MeshStandardMaterial({ color: 0x0d1417, metalness: 0.5, roughness: 0.4, emissive: 0x1c6f8a, emissiveIntensity: 0.16 });
const matAccent = new THREE.MeshStandardMaterial({ color: 0x3cc8ff, metalness: 0.4, roughness: 0.3,  emissive: 0x1e8fb8, emissiveIntensity: 0.4 });
const matReticle = new THREE.MeshBasicMaterial({ color: 0x3cc8ff, transparent: true, opacity: 0.6, depthWrite: false });

const m = (geo, mat) => new THREE.Mesh(geo, mat);

// ─── Arm rig ───────────────────────────────────────────────────────
const rig = new THREE.Group();
rig.scale.setScalar(1.15);
rig.position.set(0, 0.8, 0);
scene.add(rig);

// Base
const baseCyl = m(new THREE.CylinderGeometry(1.4, 1.65, 0.6, 32), matBody);
baseCyl.position.set(0, -2.8, 0);
rig.add(baseCyl);

const baseRing = m(new THREE.TorusGeometry(1.44, 0.05, 12, 40), matAccent);
baseRing.rotation.x = Math.PI / 2;
baseRing.position.set(0, -2.52, 0);
rig.add(baseRing);

// Column connecting base to shoulder
const basePillar = m(new THREE.CylinderGeometry(0.52, 0.6, 0.7, 20), matBody);
basePillar.position.set(0, -2.1, 0);
rig.add(basePillar);

// Shoulder group — pivot for IK
const shoulderGrp = new THREE.Group();
shoulderGrp.position.set(0, SHOULDER_Y, 0);
rig.add(shoulderGrp);
shoulderGrp.add(m(new THREE.SphereGeometry(0.55, 24, 24), matJoint));
const shoulderRing = m(new THREE.TorusGeometry(0.58, 0.06, 10, 36), matAccent);
shoulderRing.rotation.x = Math.PI / 2;
shoulderGrp.add(shoulderRing);

// Upper arm pivot — rotation.z = theta1
const upperArmPivot = new THREE.Group();
shoulderGrp.add(upperArmPivot);

const upperArm = m(new THREE.CapsuleGeometry(0.33, L1, 8, 16), matBody);
upperArm.position.set(L1 * 0.5, 0, 0);
upperArm.rotation.z = Math.PI / 2;
upperArmPivot.add(upperArm);

// Accent stripe at midpoint of upper arm
const uaStripe = m(new THREE.CylinderGeometry(0.34, 0.34, 0.07, 20), matAccent);
uaStripe.position.set(L1 * 0.5, 0, 0);
uaStripe.rotation.z = Math.PI / 2;
upperArmPivot.add(uaStripe);

// Elbow — at L1 from shoulder
const elbowGrp = new THREE.Group();
elbowGrp.position.set(L1, 0, 0);
upperArmPivot.add(elbowGrp);
elbowGrp.add(m(new THREE.SphereGeometry(0.42, 24, 24), matJoint));
const elbowRing = m(new THREE.TorusGeometry(0.46, 0.05, 10, 36), matAccent);
elbowRing.rotation.x = Math.PI / 2;
elbowGrp.add(elbowRing);

// Forearm pivot — rotation.z = theta2 (relative to upper arm)
const forearmPivot = new THREE.Group();
elbowGrp.add(forearmPivot);

const forearmMesh = m(new THREE.CapsuleGeometry(0.25, L2, 8, 16), matBody);
forearmMesh.position.set(L2 * 0.5, 0, 0);
forearmMesh.rotation.z = Math.PI / 2;
forearmPivot.add(forearmMesh);

// Wrist + gripper — at L2 from elbow
const wristGrp = new THREE.Group();
wristGrp.position.set(L2, 0, 0);
forearmPivot.add(wristGrp);

wristGrp.add(m(new THREE.SphereGeometry(0.28, 20, 20), matJoint));

const gripBody = m(new THREE.BoxGeometry(0.4, 0.28, 0.52), matBody);
gripBody.position.set(0.32, 0, 0);
wristGrp.add(gripBody);

const finA = m(new THREE.BoxGeometry(0.66, 0.1, 0.13), matAccent);
finA.position.set(0.82, 0.13, 0.18);
wristGrp.add(finA);

const finB = m(new THREE.BoxGeometry(0.66, 0.1, 0.13), matAccent);
finB.position.set(0.82, 0.13, -0.18);
wristGrp.add(finB);

// ─── Reticle ───────────────────────────────────────────────────────
const reticle = new THREE.Group();
reticle.position.set(2.5, 0.2, 1.5);
scene.add(reticle);

reticle.add(m(new THREE.TorusGeometry(0.20, 0.010, 8, 40), matReticle));
reticle.add(m(new THREE.TorusGeometry(0.065, 0.008, 8, 24), matReticle));
reticle.add(m(new THREE.BoxGeometry(0.35, 0.005, 0.005), matReticle));
reticle.add(m(new THREE.BoxGeometry(0.005, 0.35, 0.005), matReticle));

// ─── Grid ──────────────────────────────────────────────────────────
const GROUND_Y = -3.2;
const grid = new THREE.GridHelper(20, 20, 0x123642, 0x0c1f26);
grid.position.y = GROUND_Y;
scene.add(grid);

// Lowest IK target height (rig-local, unscaled units), clamped above the
// grid with clearance for the gripper mesh so the arm never visibly reaches
// into the floor. rig.scale divides out since L1/L2/SHOULDER_Y are unscaled.
const MIN_LOCAL_Y = (GROUND_Y - rig.position.y) / rig.scale.x + 0.65;

// ─── Particles ─────────────────────────────────────────────────────
const N = 320;
const pBuf = new Float32Array(N * 3);
{
  let seed = 1337;
  const rng = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  for (let i = 0; i < N; i++) {
    pBuf[i * 3]     = (rng() - 0.5) * 20;
    pBuf[i * 3 + 1] = (rng() - 0.5) * 11;
    pBuf[i * 3 + 2] = (rng() - 0.5) * 12 - 1;
  }
}
const pGeo = new THREE.BufferGeometry();
pGeo.setAttribute("position", new THREE.BufferAttribute(pBuf, 3));
const particles = new THREE.Points(pGeo, new THREE.PointsMaterial({
  color: 0x3cc8ff, size: 0.024, transparent: true, opacity: 0.38, sizeAttenuation: true,
}));
scene.add(particles);

// ─── Mouse / interaction state ─────────────────────────────────────
const mouse = { x: 0, y: 0 };
let mouseClientX = 0, mouseClientY = 0;

let rotY = 0.5, rotX = -0.15;
let dragging = false;
let dragStart = { x: 0, y: 0 }, dragRotY = 0.5, dragRotX = -0.15;
let cursorInHero = false; // auto-spins until the cursor is over this section

let th1 = 0.32;   // shoulder Z (smoothed)
let th2 = -0.85;  // forearm Z relative to upper arm (smoothed)

// ─── IK solver — 2-link law of cosines ─────────────────────────────
function solveIK(tx, ty) {
  const d = Math.hypot(tx, ty);
  const dC = Math.max(Math.abs(L1 - L2) + 0.01, Math.min(L1 + L2 - 0.01, d));
  const s = d > 0.001 ? dC / d : 1;
  const txC = tx * s, tyC = ty * s;

  const cosA = (L1 * L1 + L2 * L2 - dC * dC) / (2 * L1 * L2);
  const alpha = Math.acos(Math.max(-1, Math.min(1, cosA)));

  const cosB = (L1 * L1 + dC * dC - L2 * L2) / (2 * L1 * dC);
  const beta  = Math.acos(Math.max(-1, Math.min(1, cosB)));

  const atan = Math.atan2(tyC, txC);
  let theta1 = atan + beta;
  let theta2 = -(Math.PI - alpha);

  // Floor clamp — the reachability projection above can push the solved
  // joint angles below ground even when the mouse target was clamped, so
  // bound the elbow and wrist heights directly as a final safeguard.
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

// ─── Raycast helpers ───────────────────────────────────────────────
const raycaster  = new THREE.Raycaster();
const ndcV       = new THREE.Vector2();
const planeNorm  = new THREE.Vector3();
const shoulderWP = new THREE.Vector3();
const ikPlane    = new THREE.Plane();
const worldHit   = new THREE.Vector3();
const invRig     = new THREE.Matrix4();
const localHit   = new THREE.Vector3();

function computeIKAngles() {
  rig.updateMatrixWorld();
  shoulderGrp.getWorldPosition(shoulderWP);

  planeNorm.set(0, 0, 1).applyQuaternion(rig.quaternion).normalize();
  ikPlane.setFromNormalAndCoplanarPoint(planeNorm, shoulderWP);

  const rect = canvas.getBoundingClientRect();
  if (rect.width === 0 || rect.height === 0) return null;
  ndcV.x =  ((mouseClientX - rect.left) / rect.width)  * 2 - 1;
  ndcV.y = -(((mouseClientY - rect.top)  / rect.height) * 2 - 1);

  raycaster.setFromCamera(ndcV, camera);
  if (!raycaster.ray.intersectPlane(ikPlane, worldHit)) return null;

  invRig.copy(rig.matrixWorld).invert();
  localHit.copy(worldHit).applyMatrix4(invRig);
  localHit.y = Math.max(localHit.y, MIN_LOCAL_Y);

  return solveIK(localHit.x, localHit.y - SHOULDER_Y);
}

// ─── Animation ─────────────────────────────────────────────────────
let prevT = 0;

function animate(now) {
  requestAnimationFrame(animate);
  const t  = now * 0.001;
  const dt = Math.min(t - prevT, 0.05);
  prevT = t;

  // Camera parallax — kept mostly on-axis (x/y), only a light touch of
  // depth so mouse movement doesn't spin the scene around in 3D
  camera.position.x = mouse.x * 0.5;
  camera.position.y = 0.8 - mouse.y * 0.25;
  camera.lookAt(0, 0.4, 0);
  camera.updateMatrixWorld();

  // Rig rotation — auto-spins until the cursor is over this section, then
  // holds steady (just a light mouse-driven touch) so IK tracking reads
  // clearly, plus whatever the user sets by dragging.
  if (!dragging && !cursorInHero) rotY += 0.11 * dt;
  rig.rotation.y = rotY + mouse.x * 0.05;
  rig.rotation.x = rotX * 0.25;

  // IK solve + smooth, rate-limited so a target that jumps far (e.g. mouse
  // crossing into the next section) can't snap the arm there in one frame
  const ik = computeIKAngles();
  if (ik) {
    const maxDelta = MAX_ANGULAR_SPEED * dt;
    const d1 = Math.max(-maxDelta, Math.min(maxDelta, (ik.theta1 - th1) * SMOOTH));
    const d2 = Math.max(-maxDelta, Math.min(maxDelta, (ik.theta2 - th2) * SMOOTH));
    th1 += d1;
    th2 += d2;
  }
  upperArmPivot.rotation.z = th1;
  forearmPivot.rotation.z  = th2;

  wristGrp.rotation.y = mouse.x * 0.15;
  wristGrp.rotation.z = -mouse.y * 0.1;

  // Reticle follows IK world target
  if (ik) {
    reticle.position.x += (worldHit.x - reticle.position.x) * 0.12;
    reticle.position.y += (worldHit.y - reticle.position.y) * 0.12;
    reticle.position.z += (worldHit.z - reticle.position.z) * 0.12;
  }
  reticle.lookAt(camera.position);
  reticle.scale.setScalar(1 + Math.sin(t * 3.2) * 0.08);

  // Breathing emissives
  matAccent.emissiveIntensity  = 0.75 + Math.sin(t * 2.1) * 0.30;
  matJoint.emissiveIntensity   = 0.30 + Math.sin(t * 1.4 + 1) * 0.12;
  matReticle.opacity           = 0.65 + Math.sin(t * 3.2) * 0.25;

  // Particle drift
  particles.rotation.y = t * 0.014;
  particles.position.y = Math.sin(t * 0.3) * 0.18;

  renderer.render(scene, camera);
}

requestAnimationFrame(animate);

// ─── Resize ────────────────────────────────────────────────────────
function resize() {
  const heroEl = canvas.closest(".hero") || canvas.parentElement;
  const w = heroEl ? heroEl.clientWidth  : window.innerWidth;
  const h = heroEl ? heroEl.clientHeight : window.innerHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
resize();

let resizeTimer;
window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(resize, 120); });

// ─── Events ────────────────────────────────────────────────────────
window.addEventListener("mousemove", (e) => {
  mouseClientX = e.clientX;
  mouseClientY = e.clientY;
  mouse.x = e.clientX / window.innerWidth - 0.5;
  mouse.y = e.clientY / window.innerHeight - 0.5;
});

window.addEventListener("touchmove", (e) => {
  if (!e.touches[0]) return;
  mouseClientX = e.touches[0].clientX;
  mouseClientY = e.touches[0].clientY;
  mouse.x = e.touches[0].clientX / window.innerWidth - 0.5;
  mouse.y = e.touches[0].clientY / window.innerHeight - 0.5;
}, { passive: true });

// Drag-to-rotate
const heroSection = canvas.closest(".hero") || canvas.parentElement;

heroSection.addEventListener("mouseenter", () => { cursorInHero = true; });
heroSection.addEventListener("mouseleave", () => { cursorInHero = false; });

heroSection.addEventListener("pointerdown", (e) => {
  if (e.target.closest(".btn") || e.target.closest("a")) return;
  dragging = true;
  dragStart = { x: e.clientX, y: e.clientY };
  dragRotY = rotY; dragRotX = rotX;
  heroSection.classList.add("is-grabbing");
  heroSection.setPointerCapture && heroSection.setPointerCapture(e.pointerId);
});

heroSection.addEventListener("pointermove", (e) => {
  if (!dragging) return;
  rotY = dragRotY + (e.clientX - dragStart.x) * 0.008;
  rotX = Math.max(-1.0, Math.min(0.6, dragRotX + (e.clientY - dragStart.y) * 0.006));
});

heroSection.addEventListener("pointerup", () => {
  dragging = false;
  heroSection.classList.remove("is-grabbing");
});

heroSection.addEventListener("pointerleave", () => {
  dragging = false;
  heroSection.classList.remove("is-grabbing");
});
