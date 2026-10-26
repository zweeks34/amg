// Small Alpine components. Loaded (deferred) before Alpine itself so the
// components are registered by the time Alpine walks the page.

document.addEventListener("alpine:init", () => {
  let nextId = 1;
  const withId = (row) => ({ ...row, covers: [...(row.covers || [])], ...(row.actions ? { actions: { ...row.actions } } : {}),
                               ...(row.jobs ? { jobs: [...row.jobs] } : {}), query: "", touched: false, _id: nextId++ });
  const strip = ({ query, touched, _id, jobs, ...row }) => row;
  const blankLine = () => withId({ description: "", kind: "other", amount: "", covers: [], actions: {}, jobs: [],
                                    inspect_only: false, part_number: "", quantity: "", covers_source: "you",
                                    from_read: false });
  const blankRec = () => withId({ description: "", covers: [], amount: "" });
  const blankWarranty = () => withId({ description: "", provider: "", months: "", miles: "", lifetime: false,
                                       covers: [], found: "" });

  // Rows with service-type chips — a service's lines, a receipt's lines and
  // its recommendations. Every row travels to the server inside one JSON field,
  // so rows, chips and checkboxes stay together however many are added or
  // removed. `editor` is {lines, errors, types}, and the car's schedule where
  // a line can be tagged from it. Methods, not getters: this object is spread
  // into components, and spreading would freeze a getter.
  function lineEditor(editor) {
    return {
      types: editor.types,
      schedule: editor.schedule || [],
      errors: [...editor.errors],
      lines: editor.lines.map(withId),

      typeName(code) {
        const type = this.types.find((t) => t.code === code);
        return type ? type.name : code;
      },
      // An exact name wins; otherwise a fragment that fits exactly one type
      // ("oil fi" → Oil filter) is taken as that type. Ambiguous text is left
      // in the box for the person to finish.
      pick(row) {
        const wanted = row.query.trim().toLowerCase();
        if (!wanted) return;
        let type = this.types.find((t) => t.name.toLowerCase() === wanted);
        if (!type) {
          const fits = this.types.filter((t) => t.name.toLowerCase().includes(wanted));
          if (fits.length === 1) type = fits[0];
        }
        if (!type) return;
        if (!row.covers.includes(type.code)) row.covers.push(type.code);
        row.query = "";
        row.touched = true;
        row.covers_source = "you";
      },
      // Choosing from the browser's suggestion list arrives as an input event
      // (insertReplacementText); while that list is open, Chrome keeps Enter
      // for itself, so waiting for Enter or blur would leave the chip unadded.
      picked(event, row) {
        if (event.inputType === "insertReplacementText" || !event.inputType) this.pick(row);
      },
      unpick(row, code) {
        row.covers = row.covers.filter((c) => c !== code);
        if (row.actions) delete row.actions[code];
        row.touched = true;
        row.covers_source = "you";
      },
      // A job from the car's schedule: its service types as chips, each with
      // the job's own action, so the line meets the job whatever a type's usual
      // action is. An inspection on an untagged line marks it inspected only;
      // a replacement or procedure clears that. A line with no description
      // takes the job's name. The menu goes back to its prompt, ready for
      // another job, so the line says beneath it which jobs it was tagged for.
      fromSchedule(row, event) {
        const job = this.schedule.find((j) => String(j.id) === event.target.value);
        event.target.value = "";
        if (!job) return;
        row.jobs = [...(row.jobs || []).filter((id) => id !== job.id), job.id];
        row.actions = row.actions || {};
        const untagged = !row.covers.length;
        for (const code of job.codes) {
          if (!row.covers.includes(code)) row.covers.push(code);
          if (job.action !== "inspect") row.actions[code] = job.action;
        }
        if (job.action !== "inspect") row.inspect_only = false;
        else if (untagged) row.inspect_only = true;
        if (!row.description.trim()) row.description = job.name;
        row.touched = true;
        row.covers_source = "you";
      },
      // The jobs a line was tagged for from the menu, while their chips are all still on it.
      taggedFor(row) {
        return (row.jobs || [])
          .map((id) => this.schedule.find((j) => j.id === id))
          .filter((job) => job && job.codes.every((code) => row.covers.includes(code)))
          .map((job) => job.name);
      },
      add() {
        this.lines.push(blankLine());
        this.errors.push(null);
      },
      remove(index) {
        this.lines.splice(index, 1);
        this.errors.splice(index, 1);
        if (!this.lines.length) this.add();
      },
      sumHint() {
        let cents = 0;
        let counted = 0;
        for (const line of this.lines) {
          const value = parseFloat(String(line.amount).replace(/[$,\s]/g, ""));
          if (!Number.isNaN(value)) { cents += Math.round(value * 100); counted += 1; }
        }
        if (!counted) return "Leave blank to add up the lines and tax.";
        return `Lines add up to $${(cents / 100).toFixed(2)}. Leave blank to use that plus tax.`;
      },
      serializedLines() {
        return JSON.stringify(this.lines.map(strip));
      },
    };
  }

  // The service form.
  Alpine.data("serviceLines", (editor, source) => ({ ...lineEditor(editor), source }));

  // The receipt review: lines and recommendations, and moving a row between
  // them — a shop's "recommended" item that was in fact done, or the reverse.
  // Lines still exactly as Claude read them are drawn as unconfirmed until
  // touched (editor.reading is true until the receipt is first confirmed).
  Alpine.data("receiptEditor", (editor) => ({
    ...lineEditor(editor),
    reading: editor.reading,
    recs: editor.recs.map(withId),
    recErrors: [...editor.recErrors],

    unread(line) {
      return this.reading && line.from_read && !line.touched;
    },
    addRec() {
      this.recs.push(blankRec());
      this.recErrors.push(null);
    },
    removeRec(index) {
      this.recs.splice(index, 1);
      this.recErrors.splice(index, 1);
    },
    toRecommendation(index) {
      const [line] = this.lines.splice(index, 1);
      this.errors.splice(index, 1);
      this.recs.push(withId({ description: line.description, covers: line.covers, amount: line.amount }));
      this.recErrors.push(null);
      if (!this.lines.length) this.add();
    },
    toLine(index) {
      const [rec] = this.recs.splice(index, 1);
      this.recErrors.splice(index, 1);
      const line = blankLine();
      Object.assign(line, { description: rec.description, covers: [...rec.covers], amount: rec.amount, touched: true });
      const empty = this.lines.length === 1 && !this.lines[0].description && !this.lines[0].covers.length && !this.lines[0].amount;
      if (empty) { this.lines.splice(0, 1, line); } else { this.lines.push(line); this.errors.push(null); }
    },
    serializedRecs() {
      return JSON.stringify(this.recs.map(strip));
    },

    // Its warranties. Ones found on an older receipt carry when they were found until saved.
    warranties: (editor.warranties || []).map(withId),
    warrantyErrors: [...(editor.warrantyErrors || [])],
    addWarranty() {
      this.warranties.push(blankWarranty());
      this.warrantyErrors.push(null);
    },
    removeWarranty(index) {
      this.warranties.splice(index, 1);
      this.warrantyErrors.splice(index, 1);
    },
    serializedWarranties() {
      return JSON.stringify(this.warranties.map(strip));
    },
  }));

  // A warranty you add: what it covers, as one row of the line editor's chips;
  // whether it's for life; and starting it from the car's in-service date.
  Alpine.data("warrantyForm", (editor) => ({
    ...lineEditor({ lines: [{ covers: editor.codes }], errors: [null], types: editor.types }),
    covers: editor.covers,
    lifetime: editor.lifetime,
    fromInService() {
      this.$refs.starts.value = editor.inService;
      this.$refs.startMiles.value = "0";
    },
  }));

  // A schedule: checking a draft before using it, and editing a car's schedule
  // after. Rows share the line editor's chips; each row is one item and action.
  // Rows as Claude read them are drawn as unconfirmed until touched; changing
  // an item's timing or action makes it yours ("Set by you").
  const blankItem = () => withId({
    id: null, name: "", covers: [], action: "replace", interval_miles: "", interval_months: "", first_miles: "",
    first_months: "", applies: "always", note: "", source: "you", document_id: null, page: null, included: true,
    why_not: "", marked: "", marked_miles: [], from_read: false, show_first: false, show_note: false,
    counts_from: "", show_start: false,
  });
  const LETTERS = { replace: "R", inspect: "I", perform: "P" };
  const SOURCES = { manual: "Owner's manual", claude: "Claude's draft", template: "Generic template", you: "Set by you" };

  Alpine.data("scheduleEditor", (editor) => ({
    ...lineEditor({ lines: editor.items, errors: editor.errors, types: editor.types }),
    reading: editor.reading,
    fingerprints: editor.fingerprints || {},

    unread(item) {
      return this.reading && item.from_read && !item.touched;
    },
    letter(action) {
      return LETTERS[action] || "?";
    },
    sourceLabel(item) {
      return SOURCES[item.source] || "";
    },
    pageLink(item) {
      const v = this.fingerprints[item.document_id];
      return `/documents/${item.document_id}/pages/${item.page}?${v ? `v=${v}&` : ""}size=full`;
    },
    timed(item) {
      item.touched = true;
      item.source = "you";
    },
    everyWords(item) {
      const parts = [];
      if (item.interval_miles) parts.push(`${item.interval_miles} mi`);
      if (item.interval_months) parts.push(`${item.interval_months} months`);
      return parts.length ? `every ${parts.join(" or ")}` : "";
    },
    whenHint(item) {
      const first = item.show_first && (item.first_miles || item.first_months);
      const every = item.interval_miles || item.interval_months;
      if (first && every && item.counts_from) return "Counted from the start date, so the first due doesn't apply.";
      if (first && every) return "The first is due at that point, then every interval after it.";
      if (first) return "Due once, at that point.";
      if (item.interval_miles && item.interval_months) return "Whichever comes first.";
      return "";
    },
    add() {
      this.lines.push(blankItem());
      this.errors.push(null);
    },
    remove(index) {
      this.lines.splice(index, 1);
      this.errors.splice(index, 1);
    },
    leaveOut(index) {
      this.lines[index].included = false;
    },
    include(index) {
      this.lines[index].included = true;
    },
    leftOutCount() {
      return this.lines.filter((item) => !item.included).length;
    },
    serializedItems() {
      return JSON.stringify(this.lines.map((item) => ({ ...strip(item), from_read: item.from_read && !item.touched })));
    },
  }));

  // The fill-up form: the price a gallon (or kWh) as you type, and for a home
  // charge, the cost at your last home rate until you type a cost yourself.
  Alpine.data("fuelForm", (options) => ({
    quantity: options.quantity,
    cost: options.cost,
    place: options.place,
    typed: options.cost !== "",

    number(text) {
      const value = parseFloat(String(text).replace(/[$,\s]/g, ""));
      return Number.isFinite(value) ? value : null;
    },
    fillCost() {
      if (this.typed || !options.rate) return;
      const kwh = this.number(this.quantity);
      this.cost = this.place === "home" && kwh ? ((kwh * options.rate) / 100).toFixed(2) : "";
    },
    costHint() {
      const quantity = this.number(this.quantity);
      const cost = this.number(this.cost);
      if (quantity && cost !== null) {
        const cents = (cost * 100) / quantity;
        const price = options.unit === "gal" ? `$${(cents / 100).toFixed(3)}/gal` : `${cents.toFixed(1)}¢/kWh`;
        return !this.typed && this.place === "home" ? `${price}, your last home rate. Change it if it's moved.` : price;
      }
      return options.rate && this.place === "home"
        ? `Fills in at your last home rate, ${options.rate.toFixed(1)}¢/kWh.`
        : "If you know it.";
    },
  }));

  // A car's photo on its form: what you pick shows in the circle before you
  // save. One file goes up: picking with one button clears the other, and
  // Remove photo clears both and the photo already kept. The big circle
  // frames it: drag the photo, or use the arrow keys, to move it (as a share
  // of the circle's width); the slider, or + and −, zoom from the whole photo
  // (1) to 4×. A new photo, or none, starts whole and centred.
  const shift = (value) => Math.max(-100, Math.min(100, Math.round(value * 10) / 10));
  const scale = (value) => Math.max(1, Math.min(4, Math.round(value * 100) / 100));
  Alpine.data("carPhoto", (options) => ({
    src: options.src,
    kept: options.kept,
    zoom: options.zoom,
    x: options.x,
    y: options.y,
    preview: null,
    held: null,

    get frame() {
      return `--z: ${this.zoom}; --dx: ${this.x}%; --dy: ${this.y}%`;
    },
    whole() {
      this.zoom = 1;
      this.x = 0;
      this.y = 0;
    },
    pick(event) {
      const file = event.target.files[0];
      for (const input of [this.$refs.chosen, this.$refs.shot]) {
        if (input !== event.target) input.value = "";
      }
      if (!file) return;
      if (this.preview) URL.revokeObjectURL(this.preview);
      this.preview = URL.createObjectURL(file);
      this.src = this.preview;
      this.whole();
    },
    remove() {
      this.$refs.chosen.value = "";
      this.$refs.shot.value = "";
      this.src = "";
      this.kept = "";
      this.whole();
    },
    grab(event) {
      if (!this.src) return;
      event.currentTarget.setPointerCapture(event.pointerId);
      this.held = { x: event.clientX, y: event.clientY, size: event.currentTarget.getBoundingClientRect().width };
    },
    drag(event) {
      if (!this.held) return;
      this.x = shift(this.x + ((event.clientX - this.held.x) / this.held.size) * 100);
      this.y = shift(this.y + ((event.clientY - this.held.y) / this.held.size) * 100);
      this.held.x = event.clientX;
      this.held.y = event.clientY;
    },
    drop() {
      this.held = null;
    },
    key(event) {
      if (!this.src) return;
      const step = event.shiftKey ? 10 : 2;
      const moves = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
      if (moves[event.key]) {
        this.x = shift(this.x + moves[event.key][0]);
        this.y = shift(this.y + moves[event.key][1]);
      } else if (event.key === "+" || event.key === "=") {
        this.zoom = scale(this.zoom + 0.1);
      } else if (event.key === "-" || event.key === "_") {
        this.zoom = scale(this.zoom - 0.1);
      } else {
        return;
      }
      event.preventDefault();
    },
  }));

  // A line of text to the clipboard: a fill-up from the fuel log. If the
  // browser refuses, the line is shown selected, to copy by hand.
  Alpine.data("copyLine", (text) => ({
    text,
    copied: false,
    failed: false,
    timer: null,

    async copy() {
      const done = await toClipboard(text);
      this.failed = !done;
      this.copied = done;
      clearTimeout(this.timer);
      if (done) {
        this.timer = setTimeout(() => { this.copied = false; }, 2000);
      } else {
        this.$nextTick(() => { this.$refs.line.focus(); this.$refs.line.select(); });
      }
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

// Text to the clipboard; true if it got there. The clipboard API is only
// given to secure pages, and AMG is served over plain HTTP at home, so the
// older copy command comes next: a hidden read-only box, selected and copied
// within the tap. Font size 12pt keeps iOS from zooming to it.
async function toClipboard(text) {
  if (window.isSecureContext && navigator.clipboard) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // refused: try the older way
    }
  }
  const before = document.activeElement;
  const box = document.createElement("textarea");
  box.value = text;
  box.setAttribute("readonly", "");
  box.style.cssText = `position: absolute; left: -9999px; top: ${window.scrollY}px; font-size: 12pt`;
  document.body.append(box);
  box.select();
  box.setSelectionRange(0, text.length);
  let done = false;
  try {
    done = document.execCommand("copy");
  } catch {
    done = false;
  }
  box.remove();
  if (before instanceof HTMLElement) before.focus();
  return done;
}

// A suggestion fills its box as if typed: data-for names the box, data-use holds the value.
document.addEventListener("click", (event) => {
  const button = event.target instanceof Element ? event.target.closest("[data-use]") : null;
  const box = button ? document.getElementById(button.dataset.for) : null;
  if (box) {
    box.value = button.dataset.use;
    box.dispatchEvent(new Event("input", { bubbles: true }));
    box.focus();
  }
});

// On the receipt review, a field still holding what Claude read is drawn as
// unconfirmed; once you change it, it's yours. data-read holds the reading.
document.addEventListener("input", (event) => {
  const field = event.target;
  if (field instanceof HTMLElement && field.dataset.read !== undefined) {
    field.classList.toggle("is-edited", field.value !== field.dataset.read);
  }
});
