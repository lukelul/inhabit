(function () {
  "use strict";

  /* ── Year ─────────────────────────────────────────────── */
  var yearEl = document.getElementById("year");
  if (yearEl) yearEl.textContent = new Date().getFullYear();

  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ═══════════════════════════════════════════════════════
     BOOT SEQUENCE
  ═══════════════════════════════════════════════════════ */
  var BOOT_LINES = [
    "[ 0.000 ] INHABIT KERNEL v0.9 — cold start",
    "[ 0.012 ] loading adapters: rtde ros2 canopen ethercat … 4/4 OK",
    "[ 0.038 ] transports: webrtc lan fiber sat … linked",
    "[ 0.104 ] PVT lockstep engaged · drift ±0.4ms",
    "[ 0.171 ] safety envelope armed · force ceiling 40N",
    "[ 0.220 ] operator link established",
    "[ 0.241 ] rendering surface …",
  ];
  var LINE_INTERVAL = 175;
  var TOTAL_DURATION = BOOT_LINES.length * LINE_INTERVAL + 500;

  var boot = document.getElementById("boot");
  if (boot) {
    if (reduceMotion || sessionStorage.getItem("ihb-boot-seen")) {
      boot.classList.add("is-gone");
    } else {
      sessionStorage.setItem("ihb-boot-seen", "1");
      var bootLog = document.getElementById("bootLog");
      var bootBar = document.getElementById("bootBar");
      var visibleLines = 0;
      var exitTimeout;

      function addBootLine() {
        if (!bootLog) return;
        bootLog.querySelectorAll(".boot__cursor").forEach(function (c) { c.remove(); });
        bootLog.querySelectorAll(".boot__line--last").forEach(function (l) { l.classList.remove("boot__line--last"); });

        var line = document.createElement("div");
        line.className = "boot__line" + (visibleLines === BOOT_LINES.length - 1 ? " boot__line--last" : "");
        line.textContent = BOOT_LINES[visibleLines];

        var cursor = document.createElement("span");
        cursor.className = "boot__cursor";
        cursor.textContent = "▍";
        line.appendChild(cursor);

        bootLog.appendChild(line);
        visibleLines++;
      }

      function exitBoot() {
        if (!boot.classList.contains("is-exiting")) {
          boot.classList.add("is-exiting");
          setTimeout(function () { boot.classList.add("is-gone"); }, 560);
        }
      }

      var lineInterval = setInterval(function () {
        if (visibleLines < BOOT_LINES.length) {
          addBootLine();
        } else {
          clearInterval(lineInterval);
        }
      }, LINE_INTERVAL);

      if (bootBar) {
        bootBar.style.transition = "width " + TOTAL_DURATION + "ms linear";
        setTimeout(function () { bootBar.style.width = "100%"; }, 16);
      }

      exitTimeout = setTimeout(exitBoot, TOTAL_DURATION);

      boot.addEventListener("pointerdown", function () { clearInterval(lineInterval); clearTimeout(exitTimeout); exitBoot(); });
      document.addEventListener("keydown", function h() {
        clearInterval(lineInterval); clearTimeout(exitTimeout); exitBoot();
        document.removeEventListener("keydown", h);
      });
    }
  }

  /* ═══════════════════════════════════════════════════════
     NAV scroll
  ═══════════════════════════════════════════════════════ */
  var nav = document.getElementById("nav");
  function onNavScroll() {
    if (window.scrollY > 20) nav.classList.add("is-stuck");
    else nav.classList.remove("is-stuck");
  }
  if (nav) { onNavScroll(); window.addEventListener("scroll", onNavScroll, { passive: true }); }

  /* ═══════════════════════════════════════════════════════
     REVEAL (IntersectionObserver)
  ═══════════════════════════════════════════════════════ */
  var reveals = document.querySelectorAll(".reveal");
  if (reduceMotion || !("IntersectionObserver" in window)) {
    reveals.forEach(function (el) { el.classList.add("is-visible"); });
  } else {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          var delay = parseInt(entry.target.dataset.delay || "0", 10);
          entry.target.style.transitionDelay = delay + "ms";
          entry.target.classList.add("is-visible");
          io.unobserve(entry.target);
        }
      });
    }, { threshold: 0.1, rootMargin: "0px 0px -6% 0px" });
    reveals.forEach(function (el) { io.observe(el); });
  }

  /* ═══════════════════════════════════════════════════════
     HERO CANVAS (particle network)
  ═══════════════════════════════════════════════════════ */
  (function () {
    var canvas = document.getElementById("heroCanvas");
    if (!canvas || reduceMotion) return;
    var ctx = canvas.getContext("2d");
    var w, h, nodes, raf;

    function resize() {
      w = canvas.width = canvas.offsetWidth;
      h = canvas.height = canvas.offsetHeight;
      createNodes();
    }

    function createNodes() {
      nodes = [];
      var count = Math.max(14, Math.round(w / 90));
      for (var i = 0; i < count; i++) {
        nodes.push({
          x: Math.random() * w,
          y: Math.random() * h,
          vx: (Math.random() - 0.5) * 0.35,
          vy: (Math.random() - 0.5) * 0.35,
          r: 1 + Math.random() * 1.2
        });
      }
    }

    function draw() {
      ctx.clearRect(0, 0, w, h);
      for (var i = 0; i < nodes.length; i++) {
        for (var j = i + 1; j < nodes.length; j++) {
          var dx = nodes[i].x - nodes[j].x;
          var dy = nodes[i].y - nodes[j].y;
          var d = Math.sqrt(dx * dx + dy * dy);
          if (d < 200) {
            var alpha = (1 - d / 200) * 0.09;
            ctx.beginPath();
            ctx.moveTo(nodes[i].x, nodes[i].y);
            ctx.lineTo(nodes[j].x, nodes[j].y);
            ctx.strokeStyle = "rgba(60,200,255," + alpha + ")";
            ctx.lineWidth = 0.75;
            ctx.stroke();
          }
        }
      }
      nodes.forEach(function (n) {
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(60,200,255,0.3)";
        ctx.fill();
      });
    }

    function update() {
      nodes.forEach(function (n) {
        n.x += n.vx; n.y += n.vy;
        if (n.x < 0 || n.x > w) n.vx *= -1;
        if (n.y < 0 || n.y > h) n.vy *= -1;
      });
    }

    function loop() {
      update(); draw();
      raf = requestAnimationFrame(loop);
    }

    resize();
    loop();
    var resizeTimer;
    window.addEventListener("resize", function () {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(resize, 150);
    });
  })();

  /* ═══════════════════════════════════════════════════════
     SPARKBARS (PVT cards)
  ═══════════════════════════════════════════════════════ */
  document.querySelectorAll(".sparkbars").forEach(function (el) {
    var values = (el.dataset.values || "").split(",").map(Number);
    var color = el.dataset.color || "rgba(60,200,255,0.6)";
    var ns = "http://www.w3.org/2000/svg";
    var cols = values.length;
    var gapW = 2;
    var barW = 8;
    var totalW = cols * (barW + gapW);
    var svgH = 36;

    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 " + totalW + " " + svgH);
    svg.setAttribute("preserveAspectRatio", "none");
    svg.style.display = "block";
    svg.style.width = "100%";
    svg.style.height = svgH + "px";

    values.forEach(function (v, i) {
      var barH = (v / 100) * svgH;
      var rect = document.createElementNS(ns, "rect");
      rect.setAttribute("x", i * (barW + gapW));
      rect.setAttribute("y", svgH - barH);
      rect.setAttribute("width", barW);
      rect.setAttribute("height", barH);
      rect.setAttribute("fill", color);
      rect.setAttribute("rx", "2");
      svg.appendChild(rect);
    });
    el.appendChild(svg);
  });

  /* ═══════════════════════════════════════════════════════
     SESSION SCRUBBER
  ═══════════════════════════════════════════════════════ */
  (function () {
    var PHASES = [
      { name: "REACH",    tag: "APPROACH",    grip: 0,   endPct: 22,  color: "#6aa6e8", bg: "rgba(106,166,232,0.08)",  hint: "free-space approach, no contact" },
      { name: "CONTACT",  tag: "CONTACT",     grip: 24,  endPct: 40,  color: "#3cc8ff", bg: "rgba(60,200,255,0.1)",   hint: "surface contact detected, force ramping" },
      { name: "GRASP",    tag: "GRASP",       grip: 62,  endPct: 58,  color: "#8ff0dc", bg: "rgba(143,240,220,0.08)", hint: "grip closed, load transfer stabilizing" },
      { name: "RECOVERY", tag: "SLIP-RECOVER",grip: 58,  endPct: 76,  color: "#e0a64a", bg: "rgba(224,166,74,0.08)",  hint: "micro-slip detected, grip modulation active" },
      { name: "PLACE",    tag: "PLACE",       grip: 8,   endPct: 100, color: "#5ce0a8", bg: "rgba(92,224,168,0.08)",  hint: "target placement, gripper release" },
    ];
    var TOTAL_SECS = 272;

    var track = document.getElementById("sessionTrack");
    var thumb = document.getElementById("sessionThumb");
    var phaseBg = document.getElementById("phaseBg");
    var phaseLegend = document.getElementById("phaseLegend");
    var phasePill = document.getElementById("phasePill");
    var phaseDot = document.getElementById("phaseDot");
    var phaseLabel = document.getElementById("phaseLabel");
    var gripBadge = document.getElementById("gripBadge");
    var tagBadge = document.getElementById("tagBadge");
    var frameHint = document.getElementById("frameHint");
    var frameTime = document.getElementById("frameTime");
    var telemRows = document.getElementById("telemRows");

    if (!track) return;

    /* render phase background segments */
    var prevEnd = 0;
    PHASES.forEach(function (ph) {
      var seg = document.createElement("div");
      seg.className = "session__phase-seg";
      seg.style.flexGrow = ph.endPct - prevEnd;
      seg.style.background = ph.bg;
      phaseBg.appendChild(seg);
      prevEnd = ph.endPct;
    });

    /* render phase legend */
    PHASES.forEach(function (ph) {
      var span = document.createElement("span");
      var pip = document.createElement("span");
      pip.className = "session__phase-pip";
      pip.style.background = ph.color;
      span.appendChild(pip);
      span.appendChild(document.createTextNode(ph.name));
      phaseLegend.appendChild(span);
    });

    /* build telemetry rows */
    var TELEM_DEFS = [
      { label: "Joint torque",     color: "#3cc8ff" },
      { label: "Tactile force",    color: "#8ff0dc" },
      { label: "Gripper aperture", color: "#9aa7ad" },
      { label: "Command latency",  color: "#5ce0a8" },
    ];
    var telemRowEls = TELEM_DEFS.map(function (t) {
      var wrap = document.createElement("div"); wrap.className = "telem-row";
      var meta = document.createElement("div"); meta.className = "telem-row__meta";
      var name = document.createElement("span"); name.className = "telem-row__name"; name.textContent = t.label;
      var val  = document.createElement("span"); val.className  = "telem-row__value";
      meta.appendChild(name); meta.appendChild(val);
      var barTrack = document.createElement("div"); barTrack.className = "telem-bar";
      var fill     = document.createElement("div"); fill.className = "telem-bar__fill";
      fill.style.background = t.color;
      barTrack.appendChild(fill);
      wrap.appendChild(meta); wrap.appendChild(barTrack);
      if (telemRows) telemRows.appendChild(wrap);
      return { val: val, fill: fill };
    });

    var scrubPct = 30;
    var scrubbing = false;

    function getPhase(pct) {
      for (var i = 0; i < PHASES.length; i++) {
        if (pct <= PHASES[i].endPct) return PHASES[i];
      }
      return PHASES[PHASES.length - 1];
    }

    function padTwo(n) { return (n < 10 ? "0" : "") + n; }

    function update() {
      var ph = getPhase(scrubPct);
      var secs = Math.round((scrubPct / 100) * TOTAL_SECS);
      var grip = ph.grip;
      var force = (ph.name === "CONTACT" || ph.name === "GRASP" || ph.name === "RECOVERY")
        ? (60 + Math.round(Math.sin(scrubPct * 0.12) * 15))
        : 6;

      if (thumb) thumb.style.left = scrubPct + "%";
      if (phaseDot) { phaseDot.style.background = ph.color; phaseDot.style.boxShadow = "0 0 5px " + ph.color; }
      if (phaseLabel) { phaseLabel.textContent = ph.name; phasePill.style.color = ph.color; }
      if (gripBadge) gripBadge.textContent = "GRIP " + grip + "%";
      if (tagBadge)  tagBadge.textContent  = ph.tag;
      if (frameHint) frameHint.textContent = ph.hint;
      if (frameTime) frameTime.textContent = padTwo(Math.floor(secs / 60)) + ":" + padTwo(secs % 60);

      var torqueVal  = (20 + scrubPct * 0.3).toFixed(1) + " Nm";
      var torquePct  = Math.min(95, 20 + scrubPct * 0.5);
      var forcePct   = Math.min(95, force);
      var gripPct    = grip;
      var latency    = "4.2 ms";

      if (telemRowEls[0]) { telemRowEls[0].val.textContent = torqueVal;        telemRowEls[0].fill.style.width = torquePct + "%"; }
      if (telemRowEls[1]) { telemRowEls[1].val.textContent = force.toFixed(1) + " N"; telemRowEls[1].fill.style.width = forcePct + "%"; }
      if (telemRowEls[2]) { telemRowEls[2].val.textContent = grip + "%";       telemRowEls[2].fill.style.width = gripPct + "%"; }
      if (telemRowEls[3]) { telemRowEls[3].val.textContent = latency;          telemRowEls[3].fill.style.width = "18%"; }
    }

    function pctFromClientX(clientX) {
      var rect = track.getBoundingClientRect();
      return Math.max(0, Math.min(100, (clientX - rect.left) / rect.width * 100));
    }

    track.addEventListener("pointerdown", function (e) {
      scrubbing = true;
      scrubPct = pctFromClientX(e.clientX);
      update();
      track.setPointerCapture(e.pointerId);
    });
    track.addEventListener("pointermove", function (e) {
      if (!scrubbing) return;
      if (thumb) thumb.style.transition = "none";
      scrubPct = pctFromClientX(e.clientX);
      update();
    });
    track.addEventListener("pointerup", function () {
      scrubbing = false;
      if (thumb) thumb.style.transition = "";
    });

    update();
  })();

  /* ═══════════════════════════════════════════════════════
     LAST CENTIMETER CANVAS (animated sparklines)
  ═══════════════════════════════════════════════════════ */
  (function () {
    var canvas = document.getElementById("lastCmCanvas");
    if (!canvas || reduceMotion) return;
    var ctx = canvas.getContext("2d");
    var t = 0;

    function resize() {
      canvas.width  = canvas.offsetWidth  * (window.devicePixelRatio || 1);
      canvas.height = canvas.offsetHeight * (window.devicePixelRatio || 1);
      ctx.scale(window.devicePixelRatio || 1, window.devicePixelRatio || 1);
    }

    var STREAMS = [
      { color: "rgba(60,200,255,0.7)",   freq: 0.9,  amp: 0.25, offset: 0,   contactBoost: 0.28 },
      { color: "rgba(106,166,232,0.45)", freq: 0.35, amp: 0.16, offset: 1.6, contactBoost: 0.14 },
      { color: "rgba(143,240,220,0.75)", freq: 1.8,  amp: 0.32, offset: 2.8, contactBoost: 0.42 },
    ];

    function draw() {
      var W = canvas.offsetWidth;
      var H = canvas.offsetHeight;
      ctx.clearRect(0, 0, W, H);

      STREAMS.forEach(function (s) {
        ctx.beginPath();
        for (var i = 0; i <= W; i++) {
          var xPct = i / W;
          var contact = xPct > 0.3 && xPct < 0.72 ? s.contactBoost * Math.sin((xPct - 0.3) / 0.42 * Math.PI) : 0;
          var y = H * 0.5 - (Math.sin(xPct * Math.PI * 7 * s.freq + t + s.offset) * s.amp + contact) * H * 0.7;
          i === 0 ? ctx.moveTo(i, y) : ctx.lineTo(i, y);
        }
        ctx.strokeStyle = s.color;
        ctx.lineWidth = 1.5;
        ctx.stroke();
      });

      t += 0.028;
      requestAnimationFrame(draw);
    }

    resize();
    draw();
    window.addEventListener("resize", resize);
  })();

})();
