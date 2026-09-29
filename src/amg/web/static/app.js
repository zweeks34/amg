// Small Alpine components. Loaded (deferred) before Alpine itself so the
// components are registered by the time Alpine walks the page.

document.addEventListener("alpine:init", () => {
  // The interval chart opens scrolled so today's odometer line is in view —
  // on a phone the chart is wider than the screen and would otherwise open at
  // zero miles, showing only the car's distant past.
  Alpine.data("ichartScroll", () => ({
    init() {
      const scroller = this.$el;
      if (scroller.scrollWidth <= scroller.clientWidth) return;
      const chart = scroller.closest(".ichart");
      const track = scroller.querySelector(".ichart__row--axis .ichart__track");
      const here = parseFloat(getComputedStyle(chart).getPropertyValue("--here"));
      if (!track || Number.isNaN(here)) return;
      const trackBox = track.getBoundingClientRect();
      const scrollBox = scroller.getBoundingClientRect();
      const x = trackBox.left - scrollBox.left + scroller.scrollLeft + (trackBox.width * here) / 100;
      scroller.scrollLeft = Math.max(0, x - scroller.clientWidth * 0.6);
    },
  }));
});
