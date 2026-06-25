/* Inhabit — subtle interactions only */
(function () {
  "use strict";

  /* current year */
  var yearEl = document.getElementById("year");
  if (yearEl) yearEl.textContent = new Date().getFullYear();

  /* nav background on scroll */
  var nav = document.getElementById("nav");
  var onScroll = function () {
    if (window.scrollY > 24) nav.classList.add("is-stuck");
    else nav.classList.remove("is-stuck");
  };
  onScroll();
  window.addEventListener("scroll", onScroll, { passive: true });

  /* fade/slide-up reveal on scroll */
  var reveals = document.querySelectorAll(".reveal");
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  if (reduceMotion || !("IntersectionObserver" in window)) {
    reveals.forEach(function (el) { el.classList.add("is-visible"); });
  } else {
    var io = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry, i) {
          if (entry.isIntersecting) {
            // small stagger for grouped elements
            var delay = entry.target.dataset.delay || 0;
            entry.target.style.transitionDelay = delay + "ms";
            entry.target.classList.add("is-visible");
            io.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.12, rootMargin: "0px 0px -8% 0px" }
    );

    // stagger siblings inside grids/cta for a clean cascade
    var stagger = function (selector, step) {
      document.querySelectorAll(selector).forEach(function (el, i) {
        el.dataset.delay = i * step;
      });
    };
    stagger(".cards .reveal", 70);
    stagger(".stats .reveal", 60);
    stagger(".hero__inner .reveal", 80);

    reveals.forEach(function (el) { io.observe(el); });
  }

  /* card hover spotlight follows cursor */
  document.querySelectorAll(".card").forEach(function (card) {
    card.addEventListener("pointermove", function (e) {
      var r = card.getBoundingClientRect();
      card.style.setProperty("--mx", (e.clientX - r.left) + "px");
      card.style.setProperty("--my", (e.clientY - r.top) + "px");
    });
  });
})();
