// Small Alpine components. Loaded (deferred) before Alpine itself so the
// components are registered by the time Alpine walks the page.

document.addEventListener("alpine:init", () => {
  let nextId = 1;

  // The line editor on the service form. Every line travels to the server as
  // one JSON field (lines_json), so rows, chips and checkboxes stay together
  // however many are added or removed. `editor` is {lines, errors, types}.
  Alpine.data("serviceLines", (editor, source) => ({
    source,
    types: editor.types,
    errors: [...editor.errors],
    lines: editor.lines.map((line) => ({ ...line, covers: [...line.covers], query: "", _id: nextId++ })),

    typeName(code) {
      const type = this.types.find((t) => t.code === code);
      return type ? type.name : code;
    },
    // An exact name wins; otherwise a fragment that fits exactly one type
    // ("oil fi" → Oil filter) is taken as that type. Ambiguous text is left
    // in the box for the person to finish.
    pick(line) {
      const wanted = line.query.trim().toLowerCase();
      if (!wanted) return;
      let type = this.types.find((t) => t.name.toLowerCase() === wanted);
      if (!type) {
        const fits = this.types.filter((t) => t.name.toLowerCase().includes(wanted));
        if (fits.length === 1) type = fits[0];
      }
      if (!type) return;
      if (!line.covers.includes(type.code)) line.covers.push(type.code);
      line.query = "";
    },
    // Choosing from the browser's suggestion list arrives as an input event
    // (insertReplacementText); while that list is open, Chrome keeps Enter
    // for itself, so waiting for Enter or blur would leave the chip unadded.
    picked(event, line) {
      if (event.inputType === "insertReplacementText" || !event.inputType) this.pick(line);
    },
    unpick(line, code) {
      line.covers = line.covers.filter((c) => c !== code);
    },
    add() {
      this.lines.push({ description: "", kind: "other", amount: "", covers: [], inspect_only: false,
                        part_number: "", quantity: "", query: "", _id: nextId++ });
      this.errors.push(null);
    },
    remove(index) {
      this.lines.splice(index, 1);
      this.errors.splice(index, 1);
      if (!this.lines.length) this.add();
    },
    get sumHint() {
      let cents = 0;
      let counted = 0;
      for (const line of this.lines) {
        const value = parseFloat(String(line.amount).replace(/[$,\s]/g, ""));
        if (!Number.isNaN(value)) { cents += Math.round(value * 100); counted += 1; }
      }
      if (!counted) return "Leave blank to add up the lines and tax.";
      return `Lines add up to $${(cents / 100).toFixed(2)}. Leave blank to use that plus tax.`;
    },
    get serialized() {
      return JSON.stringify(this.lines.map(({ query, _id, ...line }) => line));
    },
  }));

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
