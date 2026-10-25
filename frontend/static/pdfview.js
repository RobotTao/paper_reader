/* PDF viewer built on pdf.js: lazy canvas rendering + text layer + highlight overlays. */

let pdfjsPromise = null;

function loadPdfJs() {
  if (!pdfjsPromise) {
    pdfjsPromise = import("/static/vendor/pdf.min.mjs").then((module) => {
      module.GlobalWorkerOptions.workerSrc = "/static/vendor/pdf.worker.min.mjs";
      return module;
    });
  }
  return pdfjsPromise;
}

const PAGE_GAP = 16;

/**
 * Convert a stored highlight rectangle into viewport pixels.
 *
 * The readpaper export stores rectangles with the origin at the TOP-LEFT of
 * the page (x grows right, y grows down). PDF user space instead has its
 * origin at the BOTTOM-LEFT (y grows up), so the rectangle has to be flipped
 * before handing it to pdf.js. Doing the flip explicitly keeps the overlay
 * correct for rotated pages too.
 */
function rectToBox(rect, page, viewport) {
  const [x0, , , y1] = page.view; // crop box in PDF user space
  const xPdf = x0 + rect.x;
  const yTop = y1 - rect.y; // top edge, measured from the bottom
  const yBottom = y1 - (rect.y + rect.h);

  // Opposite corners: top-left and bottom-right of the stored rectangle.
  const [xa, ya] = viewport.convertToViewportPoint(xPdf, yTop);
  const [xb, yb] = viewport.convertToViewportPoint(xPdf + rect.w, yBottom);

  return {
    left: Math.min(xa, xb),
    top: Math.min(ya, yb),
    width: Math.abs(xb - xa),
    height: Math.abs(yb - ya),
  };
}

/**
 * Convert a box on the page into a stored rectangle.
 *
 * The other way round of `rectToBox`: a box in viewport pixels becomes the
 * same format the readpaper export uses (origin at the top-left of the page,
 * y grows down), so a highlight made here looks exactly like an imported
 * one and needs no conversion when it is exported.
 *
 * @param {object} box {left, top, width, height} in viewport pixels
 */
function boxToStored(box, page, viewport) {
  const [x0, , , y1] = page.view; // crop box in PDF user space
  const [ax, ay] = viewport.convertToPdfPoint(box.left, box.top);
  const [bx, by] = viewport.convertToPdfPoint(box.left + box.width, box.top + box.height);

  const left = Math.min(ax, bx);
  const right = Math.max(ax, bx);
  const top = Math.max(ay, by); // the higher of the two, in PDF space
  const bottom = Math.min(ay, by);

  return { x: left - x0, y: y1 - top, w: right - left, h: top - bottom };
}

/**
 * Mount a PDF viewer.
 * @param {HTMLElement} container scrollable container
 * @param {string} url pdf url
 * @param {Array} annotations [{id, pageNumber, color, rects: [{x,y,w,h,page}]}]
 * @param {object} controls {onLoaded, onPage, initialScale}
 */
export async function mountPdfViewer(container, url, annotations = [], controls = {}) {
  const pdfjs = await loadPdfJs();

  container.innerHTML = `<div class="pdf-stage"></div>`;
  const stage = container.querySelector(".pdf-stage");

  const doc = await pdfjs.getDocument({ url }).promise;

  // The size of the page changes in steps of ten per cent, so the number
  // on the screen is always a round one.
  const ZOOM_STEP = 0.1;

  /**
   * The scale that makes a page as wide as the window.
   *
   * The result is a round number - a whole ten per cent - and a page that
   * would stick out of the window is stepped back until it fits.
   */
  function fitScale(plainWidth) {
    const room = container.clientWidth - 48;
    let target = Math.round((room / plainWidth) / ZOOM_STEP) * ZOOM_STEP;
    while (target > 0.5 && target * plainWidth > room) {
      target -= ZOOM_STEP;
    }
    return Math.max(0.5, target);
  }

  // The reader opens with the page as wide as the window.
  const firstPage = await doc.getPage(1);
  const firstPlain = firstPage.getViewport({ scale: 1 });
  const scale = { value: controls.initialScale || fitScale(firstPlain.width) };
  const pages = [];

  // Every highlight of the document, grouped by the page it sits on.
  // A mark remembers its colour and whether it is a text highlight or a
  // frame drawn around a figure.
  const marksByPage = new Map();
  const annotationList = [];

  const marksFor = (pageNumber) => {
    if (!marksByPage.has(pageNumber)) marksByPage.set(pageNumber, []);
    return marksByPage.get(pageNumber);
  };

  const addAnnotation = (annot) => {
    if (!annot) return;
    annotationList.push(annot);
    const pageNumber = Number(annot.pageNumber) || 1;
    for (const rect of annot.rects || []) {
      marksFor(pageNumber).push({
        rect,
        color: rect.color || annot.color || "yellow",
        kind: rect.kind || "text",
        id: annot.id,
      });
    }
    const entry = pages[pageNumber - 1];
    if (entry && entry.painted) paintOverlay(entry);
  };

  const removeAnnotation = (id) => {
    const index = annotationList.findIndex((item) => item.id === id);
    if (index < 0) return;
    const [annot] = annotationList.splice(index, 1);
    const pageNumber = Number(annot.pageNumber) || 1;
    const marks = marksByPage.get(pageNumber) || [];
    // The rectangles are compared by their place, not by their identity:
    // a highlight that comes back from the server is a new list of them.
    const kept = marks.filter(
      (mark) =>
        !(annot.rects || []).some(
          (rect) =>
            rect.x === mark.rect.x &&
            rect.y === mark.rect.y &&
            rect.w === mark.rect.w &&
            rect.h === mark.rect.h &&
            rect.page === mark.rect.page
        )
    );
    marksByPage.set(pageNumber, kept);
    const entry = pages[pageNumber - 1];
    if (entry && entry.painted) paintOverlay(entry);
  };

  /** Draw the highlights of one page. */
  const paintOverlay = (entry) => {
    const overlay = entry.wrapper.querySelector(".pdf-overlay");
    if (!overlay || !entry.page) return;
    overlay.innerHTML = "";
    // The rectangles of one annotation are drawn inside one group. The
    // group carries the transparency, so rectangles that cover each other
    // - the lines of a long selection do - keep one colour instead of
    // piling up into a darker patch.
    const groups = new Map();
    for (const mark of marksByPage.get(entry.pageNumber) || []) {
      const { left, top, width, height } = rectToBox(mark.rect, entry.page, entry.viewport);
      // A rectangle without width is a leftover of the selection, not a
      // place the reader pointed at.
      if (width < 2) continue;
      const area = mark.kind === "area";
      let host = overlay;
      if (!area) {
        let group = groups.get(mark.id);
        if (!group) {
          group = document.createElement("div");
          group.className = `pdf-highlight-group ${mark.color}`;
          group.dataset.annotId = mark.id ?? "";
          groups.set(mark.id, group);
          overlay.appendChild(group);
        }
        host = group;
      }
      const box = document.createElement("div");
      box.className = `pdf-highlight ${mark.color}${area ? " area" : ""}`;
      // The reader needs to know which highlight was clicked.
      box.dataset.annotId = mark.id ?? "";
      box.dataset.kind = mark.kind;
      box.style.left = `${left}px`;
      box.style.top = `${top}px`;
      box.style.width = `${Math.max(1, width)}px`;
      box.style.height = `${Math.max(1, height)}px`;
      host.appendChild(box);
    }
  };

  /**
   * Give an existing highlight another colour.
   *
   * The boxes that are already on the page only get a new class: they are
   * not drawn again, so the popup that hangs on them stays where it is.
   */
  const setAnnotationColor = (id, color) => {
    const annot = annotationList.find((item) => item.id === id);
    if (annot) annot.color = color;
    for (const entry of pages) {
      for (const mark of marksFor(entry.pageNumber)) {
        if (mark.id === id) mark.color = color;
      }
      for (const group of entry.wrapper.querySelectorAll(`.pdf-highlight-group[data-annot-id="${id}"]`)) {
        group.className = `pdf-highlight-group ${color}`;
      }
      for (const box of entry.wrapper.querySelectorAll(`.pdf-highlight[data-annot-id="${id}"]`)) {
        box.className = `pdf-highlight ${color}${box.dataset.kind === "area" ? " area" : ""}`;
      }
    }
  };

  /**
   * The highlight that lies under a point on the page.
   *
   * The highlights themselves let the mouse through - the text under them
   * has to stay selectable - so they are looked up by their place on the
   * screen instead of by the click.
   */
  const annotationAt = (clientX, clientY) => {
    for (const entry of pages) {
      for (const box of entry.wrapper.querySelectorAll(".pdf-highlight")) {
        const r = box.getBoundingClientRect();
        if (clientX < r.left || clientX > r.right || clientY < r.top || clientY > r.bottom) {
          continue;
        }
        const id = Number(box.dataset.annotId);
        if (!id) continue;
        return { id, element: box, page: entry.wrapper };
      }
    }
    return null;
  };

  /* ------------------------------------------------------------------ */
  /* the bookmarks of the document                                        */
  /* ------------------------------------------------------------------ */

  /**
   * The page a destination points at.
   *
   * A destination is either a name ("chapter-1") or a list whose first entry
   * is a reference to a page. The rest says where on the page to land.
   */
  const resolveDest = async (dest) => {
    let target = dest;
    if (typeof target === "string") {
      target = await doc.getDestination(target).catch(() => null);
    }
    if (!Array.isArray(target) || !target.length) return null;
    let pageNumber = null;
    try {
      const index = await doc.getPageIndex(target[0]);
      if (typeof index === "number") pageNumber = index + 1;
    } catch {
      // A bookmark without a usable page is skipped, not an error.
    }
    // The height on the page, in PDF user space. Only two kinds of
    // destination carry one.
    const kind = target[1] && target[1].name;
    let top = null;
    if (kind === "XYZ" && typeof target[3] === "number") top = target[3];
    else if (kind === "FitR" && typeof target[5] === "number") top = target[5];
    return { pageNumber, top };
  };

  /** The bookmarks of the document, as a tree of {title, pageNumber, items}. */
  const getOutline = async () => {
    let raw = [];
    try {
      raw = (await doc.getOutline()) || [];
    } catch {
      return [];
    }
    const build = async (item) => {
      const dest = await resolveDest(item.dest);
      return {
        title: item.title || "",
        pageNumber: dest?.pageNumber || null,
        top: dest?.top ?? null,
        items: await Promise.all((item.items || []).map(build)),
      };
    };
    return Promise.all(raw.map(build));
  };

  /** Jump to a place in the document: a page, and a height on that page. */
  const goToDest = async (pageNumber, top) => {
    const item = pages[pageNumber - 1];
    if (!item) return;
    paintQuietly(item);
    let offset = 0;
    if (typeof top === "number") {
      const page = item.page || (await doc.getPage(pageNumber));
      const viewport = page.getViewport({ scale: scale.value });
      // The height is measured from the bottom of the page: the viewport
      // knows how to turn it into a distance from the top.
      const [, y] = viewport.convertToViewportPoint(page.view[0], top);
      offset = Math.max(0, y - 24);
    }
    container.scrollTo({
      top: item.wrapper.offsetTop + offset,
      behavior: "smooth",
    });
  };

  /* ------------------------------------------------------------------ */
  /* searching in the document                                            */
  /* ------------------------------------------------------------------ */

  // The hits of the current search, and the one that is looked at.
  const finds = { matches: [], index: -1 };

  /** Draw the hits of the search on one page. */
  const paintFinds = (entry) => {
    const layer = entry.wrapper.querySelector(".pdf-find-layer");
    if (!layer) return;
    layer.innerHTML = "";
    if (!entry.page) return;
    for (const match of finds.matches) {
      if (match.pageNumber !== entry.pageNumber) continue;
      const current = finds.matches[finds.index] === match;
      // One group per hit: the rectangles of a hit that runs over several
      // lines cover each other a little, and they have to stay one colour.
      const group = document.createElement("div");
      group.className = `pdf-find-group${current ? " current" : ""}`;
      layer.appendChild(group);
      for (const rect of match.rects) {
        const box = document.createElement("div");
        box.className = `pdf-find${current ? " current" : ""}`;
        const { left, top, width, height } = rectToBox(rect, entry.page, entry.viewport);
        box.style.left = `${left}px`;
        box.style.top = `${top}px`;
        box.style.width = `${Math.max(2, width)}px`;
        box.style.height = `${Math.max(2, height)}px`;
        group.appendChild(box);
      }
    }
  };

  /**
   * Look for a text in the whole document.
   *
   * Every page is asked for its text; the words are put together and the
   * search is run over them. A hit that falls inside one word is narrowed
   * down to the part of the word that matched.
   */
  const find = async (query) => {
    const needle = query.trim().toLowerCase();
    if (!needle) return { matches: [] };
    const matches = [];
    for (let pageNumber = 1; pageNumber <= doc.numPages; pageNumber += 1) {
      const page = await doc.getPage(pageNumber);
      const viewport = page.getViewport({ scale: scale.value });
      const content = await page.getTextContent();
      let text = "";
      const words = [];
      for (const item of content.items) {
        if (!item || typeof item.str !== "string" || !item.transform) continue;
        words.push({ start: text.length, end: text.length + item.str.length, item });
        text += item.str;
      }
      const haystack = text.toLowerCase();
      let at = 0;
      while ((at = haystack.indexOf(needle, at)) !== -1) {
        const rects = [];
        for (const word of words) {
          if (word.end <= at || word.start >= at + needle.length) continue;
          const from = Math.max(at, word.start);
          const to = Math.min(at + needle.length, word.end);
          const length = word.item.str.length;
          if (!length) continue;
          // The word is wider than the hit: only the matching part of it
          // is marked.
          const tx = pdfjs.Util.transform(viewport.transform, word.item.transform);
          const fontHeight = Math.hypot(tx[2], tx[3]);
          const full = (word.item.width || 0) * viewport.scale;
          const width = full * ((to - from) / length);
          if (width <= 0) continue;
          rects.push({
            ...boxToStored(
              {
                left: tx[4] + full * ((from - word.start) / length),
                top: tx[5] - fontHeight,
                width,
                height: fontHeight,
              },
              page,
              viewport
            ),
            page: pageNumber,
          });
        }
        if (rects.length) matches.push({ pageNumber, rects });
        at += needle.length;
      }
    }
    return { matches };
  };

  /** Show the hits of a search; the first one is the one that is looked at. */
  const showFinds = (matches, index = 0) => {
    finds.matches = matches || [];
    finds.index = finds.matches.length
      ? Math.max(0, Math.min(index, finds.matches.length - 1))
      : -1;
    for (const item of pages) if (item.painted) paintFinds(item);
  };

  /** Take the hits of the search off the page. */
  const clearFinds = () => {
    finds.matches = [];
    finds.index = -1;
    for (const item of pages) if (item.painted) paintFinds(item);
  };

  /** Look at another hit: it is marked and the page scrolls to it. */
  const goToFind = async (index) => {
    if (!finds.matches.length) return;
    const total = finds.matches.length;
    finds.index = ((index % total) + total) % total;
    const match = finds.matches[finds.index];
    for (const item of pages) if (item.painted) paintFinds(item);
    const item = pages[match.pageNumber - 1];
    if (!item) return;
    paintQuietly(item);
    const rect = match.rects[0];
    if (!rect) return;
    const page = item.page || (await doc.getPage(match.pageNumber));
    const viewport = page.getViewport({ scale: scale.value });
    const { top } = rectToBox(rect, page, viewport);
    container.scrollTo({
      top: item.wrapper.offsetTop + Math.max(0, top - 80),
      behavior: "smooth",
    });
  };

  /**
   * Put the text of the page under the cursor into the page.
   *
   * The text is invisible (the canvas shows it) but selectable, which is
   * what makes highlighting a sentence possible. A PDF without a text layer
   * (a scan) simply gets no text layer - the pages still render.
   */
  const paintTextLayer = async (entry, page, viewport) => {
    const layer = entry.wrapper.querySelector(".textLayer");
    if (!layer) return;
    // The layer asks for --scale-factor to size itself; nobody else sets it.
    layer.style.setProperty("--scale-factor", String(viewport.scale));
    layer.innerHTML = "";
    try {
      if (entry.textLayer) {
        entry.textLayer.cancel();
        entry.textLayer = null;
      }
      const content = await page.getTextContent();
      entry.textLayer = new pdfjs.TextLayer({
        textContentSource: content,
        container: layer,
        viewport,
      });
      await entry.textLayer.render();
    } catch {
      // A page without usable text is not an error: the canvas is enough.
      entry.textLayer = null;
    }
  };

  const paint = async (entry) => {
    if (entry.painted) return;
    entry.painted = true;
    try {
      const { pageNumber, wrapper, canvas } = entry;
      const page = await doc.getPage(pageNumber);
      const viewport = page.getViewport({ scale: scale.value });
      const dpr = window.devicePixelRatio || 1;

      entry.page = page;
      entry.viewport = viewport;

      canvas.width = Math.floor(viewport.width * dpr);
      canvas.height = Math.floor(viewport.height * dpr);
      canvas.style.width = `${Math.floor(viewport.width)}px`;
      canvas.style.height = `${Math.floor(viewport.height)}px`;

      await page.render({
        canvasContext: canvas.getContext("2d"),
        viewport,
        transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : undefined,
      }).promise;

      await paintTextLayer(entry, page, viewport);
      paintOverlay(entry);
      paintFinds(entry);
      // The page is on the screen: whatever hangs on it can find its place.
      if (controls.onPainted) controls.onPainted(entry.pageNumber);
    } catch (error) {
      // A page that failed to render must be tried again the next time it
      // comes into view, otherwise it stays blank for good.
      entry.painted = false;
      throw error;
    }
  };

  // Painting happens in the background: a page that fails is not worth an
  // unhandled rejection, the reader shows the rest of the document.
  const paintQuietly = (entry) => paint(entry).catch(() => {});

  // Build one lightweight placeholder per page, paint them as they scroll in.
  for (let pageNumber = 1; pageNumber <= doc.numPages; pageNumber += 1) {
    const page = await doc.getPage(pageNumber);
    const viewport = page.getViewport({ scale: scale.value });
    // The width of the page without any zoom: "fit width" is computed
    // from it.
    const plain = page.getViewport({ scale: 1 });

    const wrapper = document.createElement("div");
    wrapper.className = "pdf-page";
    wrapper.dataset.page = String(pageNumber);
    wrapper.style.width = `${Math.floor(viewport.width)}px`;
    wrapper.style.height = `${Math.floor(viewport.height)}px`;
    wrapper.style.margin = `0 auto ${PAGE_GAP}px`;

    const canvas = document.createElement("canvas");
    canvas.style.display = "block";
    wrapper.appendChild(canvas);

    // The text of the page: invisible, but selectable. Without it there is
    // nothing to highlight and no text to copy.
    const textLayer = document.createElement("div");
    textLayer.className = "textLayer";
    wrapper.appendChild(textLayer);

    const overlay = document.createElement("div");
    overlay.className = "pdf-overlay";
    wrapper.appendChild(overlay);

    // The hits of a search: they sit above the highlights, but they do not
    // take the mouse, so the text can still be picked.
    const findLayer = document.createElement("div");
    findLayer.className = "pdf-find-layer";
    wrapper.appendChild(findLayer);

    stage.appendChild(wrapper);
    pages.push({
      pageNumber,
      wrapper,
      canvas,
      painted: false,
      viewport,
      width: plain.width,
    });
  }

  for (const annot of annotations) addAnnotation(annot);

  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        const index = Number(entry.target.dataset.page) - 1;
        const item = pages[index];
        if (item && !item.painted) paintQuietly(item);
      }
    },
    { root: container, rootMargin: "900px 0px" }
  );
  pages.forEach((item) => observer.observe(item.wrapper));

  // The page that is being read: the one that covers the middle of the
  // window. The top of the window is no good - a page that is only half
  // on screen would count as the one before it.
  const currentPage = () => {
    const marker = container.scrollTop + container.clientHeight / 2;
    let page = 1;
    for (const item of pages) {
      if (item.wrapper.offsetTop <= marker) page = item.pageNumber;
    }
    return page;
  };

  let scrollFrame = null;
  const onScroll = () => {
    if (scrollFrame) return;
    scrollFrame = requestAnimationFrame(() => {
      scrollFrame = null;
      if (controls.onPage) controls.onPage(currentPage());
    });
  };
  container.addEventListener("scroll", onScroll);

  /**
   * The scale that makes the current page as wide as the window.
   *
   * A little room is kept on the sides, so the page does not touch the
   * edges.
   */
  const fitWidthScale = () => {
    const item = pages[currentPage() - 1];
    if (!item) return null;
    return fitScale(item.width);
  };

  /**
   * Zoom to a scale, keeping the place inside the page.
   *
   * The pages change size, the position inside the current page should not:
   * that is why the offset is kept as a fraction of the page height.
   */
  const applyScale = async (newScale) => {
    // The size is always a whole ten per cent: the reader counts in tens.
    const rounded = Math.round(newScale / ZOOM_STEP) * ZOOM_STEP;
    scale.value = Math.min(4, Math.max(0.5, rounded));
    const page = currentPage();
    const item = pages[page - 1];
    const oldHeight = item?.wrapper.offsetHeight || 1;
    const fraction = item ? (container.scrollTop - item.wrapper.offsetTop) / oldHeight : 0;
    for (const item of pages) item.painted = false;
    for (const item of pages) {
      const page_ = await doc.getPage(item.pageNumber);
      const viewport = page_.getViewport({ scale: scale.value });
      item.viewport = viewport;
      item.wrapper.style.width = `${Math.floor(viewport.width)}px`;
      item.wrapper.style.height = `${Math.floor(viewport.height)}px`;
      item.canvas.width = 0;
      item.canvas.height = 0;
    }
    const current = pages[page - 1];
    if (current) {
      const newHeight = current.wrapper.offsetHeight || 1;
      container.scrollTop = current.wrapper.offsetTop + fraction * newHeight;
    }
    pages.forEach((item) => {
      const rect = item.wrapper.getBoundingClientRect();
      if (rect.bottom > -900 && rect.top < container.clientHeight + 900) paintQuietly(item);
    });
    if (controls.onZoom) controls.onZoom(scale.value);
  };

  /** The stored rectangle of a box drawn on the page. */
  const rectFromClient = async (pageNumber, clientRect) => {
    const entry = pages[pageNumber - 1];
    if (!entry) return null;
    const page = entry.page || (await doc.getPage(pageNumber));
    const viewport = page.getViewport({ scale: scale.value });
    const box = entry.wrapper.getBoundingClientRect();
    const local = {
      left: clientRect.left - box.left,
      top: clientRect.top - box.top,
      width: clientRect.width,
      height: clientRect.height,
    };
    return { ...boxToStored(local, page, viewport), page: pageNumber };
  };

  /** The text of the page that lies under a box drawn on it. */
  const textInArea = (pageNumber, clientRect) => {
    const entry = pages[pageNumber - 1];
    const layer = entry?.wrapper.querySelector(".textLayer");
    if (!layer) return "";
    // The box is given by its left corner and its size; the other two
    // corners are worked out here.
    const right = clientRect.right ?? clientRect.left + clientRect.width;
    const bottom = clientRect.bottom ?? clientRect.top + clientRect.height;
    const parts = [];
    for (const span of layer.querySelectorAll("span")) {
      const box = span.getBoundingClientRect();
      if (!box.width || !box.height) continue;
      const inside =
        box.right > clientRect.left &&
        box.left < right &&
        box.bottom > clientRect.top &&
        box.top < bottom;
      if (!inside) continue;
      parts.push(span.textContent);
    }
    return parts.join(" ").replace(/\s+/g, " ").trim();
  };

  /**
   * What the reader has selected right now.
   *
   * Returns the text and the stored rectangles of every page the selection
   * touches, so a highlight that runs over a page break still lands on the
   * right spot. The anchor is the box of the *last* character of the
   * selection: the bar with the colours hangs under it.
   */
  const selectionInfo = () => {
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) return null;
    const range = selection.getRangeAt(0);
    if (!container.contains(range.commonAncestorContainer)) return null;
    const text = selection.toString().trim();
    if (!text) return null;

    const rects = [];
    let pageNumber = 0;
    // The last character of the selection: the little bar of colours hangs
    // at its bottom-right corner.
    let anchor = null;
    for (const entry of pages) {
      if (!range.intersectsNode(entry.wrapper)) continue;
      const pageBox = entry.wrapper.getBoundingClientRect();
      for (const rect of range.getClientRects()) {
        const left = Math.max(rect.left, pageBox.left);
        const right = Math.min(rect.right, pageBox.right);
        const top = Math.max(rect.top, pageBox.top);
        const bottom = Math.min(rect.bottom, pageBox.bottom);
        if (right - left < 1 || bottom - top < 1) continue;
        if (
          !anchor ||
          bottom > anchor.bottom ||
          (bottom === anchor.bottom && right > anchor.right)
        ) {
          anchor = { left, top, right, bottom };
        }
        if (!entry.page || !entry.viewport) continue;
        const local = {
          left: left - pageBox.left,
          top: top - pageBox.top,
          width: right - left,
          height: bottom - top,
        };
        rects.push({
          ...boxToStored(local, entry.page, entry.viewport),
          page: entry.pageNumber,
        });
        if (!pageNumber) pageNumber = entry.pageNumber;
      }
    }
    if (!rects.length) return null;
    return { pageNumber, text, rects, anchor };
  };

  if (controls.onLoaded) controls.onLoaded(doc.numPages);
  paintQuietly(pages[0]);

  return {
    numPages: doc.numPages,
    goToPage: (pageNumber) => {
      const item = pages[pageNumber - 1];
      if (!item) return Promise.resolve();
      paintQuietly(item);
      container.scrollTo({ top: item.wrapper.offsetTop - 8, behavior: "smooth" });
      return Promise.resolve();
    },
    // The size moves in steps of ten per cent, up or down.
    zoom: async (steps) => {
      await applyScale(scale.value + steps * ZOOM_STEP);
    },
    fitWidth: async () => {
      const target = fitWidthScale();
      if (target) await applyScale(target);
    },
    getScale: () => scale.value,
    addAnnotation,
    removeAnnotation,
    setAnnotationColor,
    annotationAt,
    selectionInfo,
    rectFromClient,
    textInArea,
    getOutline,
    goToDest,
    find,
    showFinds,
    clearFinds,
    goToFind,
    getFindIndex: () => finds.index,
    getFindCount: () => finds.matches.length,
    destroy: () => {
      observer.disconnect();
      container.removeEventListener("scroll", onScroll);
      for (const item of pages) {
        if (item.textLayer) item.textLayer.cancel();
      }
      doc.destroy();
    },
  };
}
