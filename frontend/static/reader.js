/* Standalone reading page: /paper/<id> */

import { mountPdfViewer } from "/static/pdfview.js";
import {
  $,
  api,
  apiJson,
  escapeHtml,
  safeUrl,
  toast,
  ICONS,
  folderPaths,
  openFolderPicker,
  openTagPicker,
  confirmDialog,
} from "/static/common.js";

const paperId = Number(window.location.pathname.split("/").filter(Boolean)[1]);
const paper = await api(`/api/papers/${paperId}`).catch((error) => {
  // Without the paper there is nothing to render; say so instead of
  // leaving a blank page behind.
  const root = $("#reader") || document.body;
  root.innerHTML = `<div class="empty">无法打开这篇文献：${escapeHtml(
    error.message
  )}</div><div style="text-align:center"><a class="btn" href="/">返回文献库</a></div>`;
  throw error;
});
// The tab shows which paper is open.
document.title = paper.title || "文仓";
// The folder tree, so a folder can be shown with its full path: the same
// name can live under different parents.
const folders = await api("/api/folders").catch(() => []);
const folderPathMap = folderPaths(folders);
// Every tag of the library: the picker searches them, so a tag that
// already exists can be reused instead of typed again.
const libraryTags = await api("/api/tags").catch(() => []);

let viewer = null;
// Where the reader is: the page that is on screen and how many there are.
// The page number is only shown, never typed into.
let currentPage = 1;
let totalPages = 0;
// One debounce timer per field: a shared timer would cancel the pending save
// of the previous field, silently dropping that edit.
const saveTimers = new Map();
// The mark that is waiting for a colour: what was picked, and where.
let pendingMark = null;
// The colour a new highlight gets when a thought is written next to it.
let chosenColor = "yellow";
// Drawing a frame around a figure, instead of selecting text.
let areaMode = false;
let dragStart = null;
let dragBox = null;

const star = (filled) => `<span class="${filled ? "on" : ""}">${filled ? "★" : "☆"}</span>`;

/** The colours a highlight can have. They mean something, so they are few. */
const ANNOTATION_COLORS = [
  { name: "blue", label: "引用", hex: "#338AFF" },
  { name: "green", label: "肯定", hex: "#80E639" },
  { name: "yellow", label: "重点", hex: "#FFFF00" },
  { name: "orange", label: "补充", hex: "#FF8C19" },
  { name: "red", label: "疑问 / 反驳", hex: "#F24030" },
];

/** The five stars of the importance editor, as separate clickable spans. */
function starSpans(value) {
  let out = "";
  for (let i = 1; i <= 5; i += 1) out += star(i <= value);
  return out;
}

function tagChipsHtml() {
  return paper.tags
    .map(
      (tag) =>
        `<span class="chip"><span class="chip-label">${escapeHtml(
          tag.name
        )}</span><button data-remove-tag="${escapeHtml(tag.name)}">×</button></span>`
    )
    .join("");
}

function folderChipsHtml() {
  return paper.folders
    .map((folder) => {
      const path = folderPathMap.get(folder.id) || folder.name;
      return `<span class="chip" title="${escapeHtml(path)}"><span class="chip-label">${escapeHtml(
        path
      )}</span><button data-remove-folder="${folder.id}">×</button></span>`;
    })
    .join("");
}

/**
 * Refresh the tag/folder chips in place.
 *
 * A full re-render would tear the side panel down and re-mount the PDF
 * viewer, which reloads the whole document and loses the scroll position.
 */
function refreshChips() {
  const tagList = $("#tag-list");
  if (tagList) {
    tagList.innerHTML = `${tagChipsHtml()}<button class="btn small" id="add-tag">+ 标签</button>`;
  }
  const folderList = $("#folder-list");
  if (folderList) {
    folderList.innerHTML = `${folderChipsHtml()}<button class="btn small" id="add-folder">+ 分类</button>`;
  }
  bindChipActions();
}

function render() {
  $("#reader").innerHTML = `
    <div class="reader">
      <div class="reader-left" id="reader-left">
        <div class="reader-left-tabs">
          <span class="active">目录</span>
        </div>
        <div class="reader-left-body" id="outline-list"></div>
      </div>
      <div class="reader-main">
        ${
          paper.hasFile
            ? `<div class="pdf-container" id="pdf-container"></div>
               <!-- The bar at the bottom: where to go, how big, what to do. -->
               <div class="pdf-toolbar" id="pdf-toolbar">
                 <button class="icon-btn" id="pdf-find-btn" title="查找">查找</button>
                 <button class="icon-btn" id="frame-toggle" title="框选：在页面上拖一个框"
                         aria-pressed="false">框选</button>
                 <span class="pdf-toolbar-sep"></span>
                 <span class="pdf-page-jump">
                   <input type="text" id="pdf-page-input" value="1" aria-label="页码" />
                   <span class="pdf-page-total" id="pdf-page-total">/ -</span>
                 </span>
                 <span class="pdf-toolbar-sep"></span>
                 <button class="icon-btn" id="pdf-zoom-out" title="缩小">－</button>
                 <span class="pdf-zoom-level" id="pdf-zoom-level">100%</span>
                 <button class="icon-btn" id="pdf-zoom-in" title="放大">＋</button>
                 <button class="btn small" id="pdf-fit-width" title="适合宽度">适宽</button>
               </div>
               <!-- The search box: it hangs at the top of the PDF. -->
               <div class="pdf-find-bar" id="find-bar" hidden>
                 <input type="text" id="find-input" placeholder="在本文中查找" />
                 <span class="pdf-find-count" id="find-count">0 / 0</span>
                 <button class="icon-btn" id="find-prev" title="上一个">↑</button>
                 <button class="icon-btn" id="find-next" title="下一个">↓</button>
                 <button class="icon-btn" id="find-close" title="关闭">×</button>
               </div>`
            : `<div class="empty">该文献没有本地 PDF，${
                safeUrl(paper.url)
                  ? `<a href="${escapeHtml(safeUrl(paper.url))}" target="_blank" rel="noreferrer">打开原始链接</a>`
                  : "请上传 PDF"
              }</div>`
        }
        <!-- The download button: the only thing the little corner button
             used to do, so it is the button itself now. A paper without a
             file has no button at all. -->
        ${
          paper.hasFile
            ? `<button class="reader-download-btn" id="download-paper" title="下载">
                 ${ICONS.download}
               </button>
               <!-- The bar that shows up over a selection: pick a colour
                    for it, or add a thought of your own. -->
               <div class="pdf-sel-bar" id="sel-bar" hidden>
                 ${ANNOTATION_COLORS.map(
                   (color) =>
                     `<button class="sel-dot ${color.name}" data-color="${color.name}"
                              style="--dot: ${color.hex}" title="${color.label}"></button>`
                 ).join("")}
                 <span class="sel-sep"></span>
                 <button class="btn small" id="sel-idea-btn">${ICONS.pencil} 笔记</button>
               </div>
               <div class="pdf-sel-idea" id="sel-idea" hidden>
                 ${ANNOTATION_COLORS.map(
                   (color) =>
                     `<button class="sel-pick ${color.name}" data-color="${color.name}"
                              style="--dot: ${color.hex}" title="${color.label}"></button>`
                 ).join("")}
                 <input type="text" id="sel-idea-input" placeholder="写一句想法，回车保存" />
                 <button class="btn small" id="sel-idea-save">保存</button>
               </div>
               <!-- The popup on a highlight that is already there: a dashed
                    frame around it, a small × at the top-right corner to
                    delete it, at the bottom-right corner the colours and
                    the button for a thought, and - when there is a thought
                    - a box to write it in above the frame. -->
               <div class="annot-popup" id="annot-popup" hidden>
                 <div class="annot-popup-note" id="annot-popup-note" hidden>
                   <textarea id="annot-popup-note-input" rows="5"
                             placeholder="写一句想法，失焦即保存"></textarea>
                 </div>
                 <div class="annot-popup-frame"></div>
                 <button class="annot-popup-x" id="annot-popup-x" title="删除这条标注">×</button>
                 <div class="annot-popup-tools" id="annot-popup-tools">
                   ${ANNOTATION_COLORS.map(
                     (color) =>
                       `<button class="sel-dot ${color.name}" data-color="${color.name}"
                                style="--dot: ${color.hex}" title="${color.label}"></button>`
                   ).join("")}
                   <span class="sel-sep"></span>
                   <button class="icon-btn" id="annot-popup-idea" title="写想法">${ICONS.pencil}</button>
                 </div>
               </div>`
            : ""
        }
      </div>
      <div class="reader-side">
        <div class="field">
          <label>标题</label>
          <input type="text" data-field="title" value="${escapeHtml(paper.title)}" />
        </div>
        <div class="field">
          <label>作者</label>
          <input type="text" data-field="authors" value="${escapeHtml(paper.authors)}" />
        </div>
        <div class="field">
          <label>年份</label>
          <input type="number" data-field="year" value="${paper.year ?? ""}" />
        </div>
        <div class="field">
          <label>备注</label>
          <input type="text" data-field="remark" value="${escapeHtml(paper.remark)}" />
        </div>
        <div class="field">
          <label>重要性</label>
          <div id="stars-editor" class="stars" style="font-size:20px;cursor:pointer">
            ${starSpans(paper.importance)}
          </div>
        </div>
        <div class="field">
          <label>阅读状态</label>
          <button class="read-toggle ${paper.isRead ? "on" : ""}" id="read-toggle"
                  style="padding:4px 14px;font-size:13px">${paper.isRead ? "已读" : "未读"}</button>
        </div>
        <div class="field">
          <label>笔记</label>
          <textarea data-field="notes" placeholder="记录想法、结论、待办...">${escapeHtml(
            paper.notes
          )}</textarea>
        </div>
        <div class="field">
          <label>标签</label>
          <div class="chip-list" id="tag-list">
            ${tagChipsHtml()}
            <button class="btn small" id="add-tag">+ 标签</button>
          </div>
        </div>
        <div class="field">
          <label>分类</label>
          <div class="chip-list" id="folder-list">
            ${folderChipsHtml()}
            <button class="btn small" id="add-folder">+ 分类</button>
          </div>
        </div>
        <div id="annot-list">${annotationsHtml()}</div>
        <div class="section-title">信息</div>
        <div style="font-size:12.5px;color:#666;line-height:1.9">
          阅读次数：${paper.readCount}<br />
          最近阅读：${paper.lastReadAt || "—"}<br />
          添加时间：${paper.createdAt}<br />
          ${
            safeUrl(paper.url)
              ? `<a href="${escapeHtml(safeUrl(paper.url))}" target="_blank" rel="noreferrer">原始链接</a>`
              : ""
          }
        </div>
      </div>
      <!-- The catalog has its own handle on the left edge; when it is open
           the handle sits on the divider. -->
      <button
        class="reader-left-btn"
        id="toggle-left"
        title="显示目录"
        aria-expanded="false"
      >
        ${ICONS.panelOpen}
      </button>
      <!-- The side panel has its own handle on the right edge; when the
           panel is open the handle sits on the divider. -->
      <button
        class="reader-side-btn"
        id="toggle-side"
        title="显示信息侧栏"
        aria-expanded="false"
      >
        ${ICONS.panelClose}
      </button>
    </div>`;

  bind();
  bindAnnotationActions();
  if (paper.hasFile) mountViewer();
}

/* ------------------------------------------------------------------ */
/* the annotations: the highlights of this paper                        */
/* ------------------------------------------------------------------ */

function annotationHtml(note) {
  const color = note.color || "yellow";
  const isArea = (note.rects || []).some((rect) => rect.kind === "area");
  return `<div class="annotation ${color}" data-annot-id="${note.id}"
               data-annot-page="${note.pageNumber || ""}">
    <div class="annot-head">
      <span class="annot-dot ${color}"></span>
      <span class="page">${note.pageNumber ? `第 ${note.pageNumber} 页` : ""}</span>
      <span class="annot-kind">${isArea ? "框选" : "高亮"}</span>
      <button class="annot-del" title="删除标注">×</button>
    </div>
    ${note.text ? `<div class="annot-text">${escapeHtml(note.text)}</div>` : ""}
    <textarea class="annot-idea" rows="2" placeholder="写想法…">${escapeHtml(
      note.idea || ""
    )}</textarea>
  </div>`;
}

function annotationsHtml() {
  const count = paper.annotations.length;
  const head = `<div class="section-title">高亮标注 (${count})</div>`;
  if (!count) {
    return `${head}<div style="color:#9aa0a6;font-size:12.5px">在 PDF 里选中文字就能划重点</div>`;
  }
  return `${head}${paper.annotations.map(annotationHtml).join("")}`;
}

/** Draw the list of highlights again - after one was added or removed. */
function renderAnnotations() {
  const list = $("#annot-list");
  if (!list) return;
  list.innerHTML = annotationsHtml();
  bindAnnotationActions();
}

function bindAnnotationActions() {
  document.querySelectorAll("[data-annot-id]").forEach((node) => {
    const id = Number(node.dataset.annotId);
    const note = paper.annotations.find((item) => item.id === id);

    node.addEventListener("click", async (event) => {
      // The text field and the delete button are their own business.
      if (event.target.closest("textarea") || event.target.closest(".annot-del")) return;
      const page = Number(node.dataset.annotPage);
      if (page && viewer) await viewer.goToPage(page);
    });

    const idea = node.querySelector(".annot-idea");
    if (idea) {
      idea.addEventListener("blur", () => saveIdea(id, idea));
      idea.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !event.shiftKey) {
          event.preventDefault();
          idea.blur();
        } else if (event.key === "Escape") {
          idea.value = note?.idea || "";
          idea.blur();
        }
      });
    }

    node.querySelector(".annot-del")?.addEventListener("click", async (event) => {
      event.stopPropagation();
      const answer = await confirmDialog("删除这条标注？", {
        title: "删除标注",
        confirmText: "删除",
      });
      if (!answer) return;
      try {
        await apiJson(`/api/annotations/${id}`, "DELETE");
      } catch (error) {
        toast(`删除失败：${error.message}`);
        return;
      }
      paper.annotations = paper.annotations.filter((item) => item.id !== id);
      viewer?.removeAnnotation(id);
      renderAnnotations();
      toast("标注已删除");
    });
  });
}

/** Save the thought next to a highlight. */
async function saveIdea(id, field) {
  const note = paper.annotations.find((item) => item.id === id);
  if (!note) return;
  const value = field.value.trim();
  if (value === (note.idea || "")) return;
  try {
    await apiJson(`/api/annotations/${id}`, "PATCH", { idea: value });
    note.idea = value;
  } catch (error) {
    // Show what is really stored, not what failed to save.
    field.value = note.idea || "";
    toast(`保存失败：${error.message}`);
  }
}

/* ------------------------------------------------------------------ */
/* making a highlight: pick some text, or draw a frame around a figure */
/* ------------------------------------------------------------------ */

/** Show which colour is the one that will be used. */
function markChosenColor() {
  document.querySelectorAll(".sel-pick").forEach((button) => {
    button.classList.toggle("on", button.dataset.color === chosenColor);
  });
}

/**
 * Put the bar with the colours where the selection ends.
 *
 * The bar hangs at the bottom-right corner of the *last* character of the
 * selection: its left edge sits on the right edge of that character and it
 * drops a little below it. That is where readpaper puts it too.
 */
function showSelBar(anchor, keepIdea = false) {
  const bar = $("#sel-bar");
  const main = $(".reader-main");
  if (!bar || !main || !anchor) return;
  // The bar has to be visible before it can be measured.
  bar.hidden = false;
  const idea = $("#sel-idea");
  // The box for a thought belongs to the selection that is on screen: a new
  // selection puts it away.
  if (idea && !keepIdea) idea.hidden = true;

  const box = main.getBoundingClientRect();
  const width = bar.offsetWidth;
  const height = bar.offsetHeight;
  let left = anchor.right - box.left;
  let top = anchor.bottom - box.top - 5;
  // No room on the right of the text: the bar goes to the left of it.
  if (left + width > main.clientWidth - 8) {
    left = anchor.left - box.left - width;
  }
  left = Math.max(8, Math.min(left, main.clientWidth - width - 8));
  top = Math.max(8, Math.min(top, main.clientHeight - height - 8));
  bar.style.left = `${left}px`;
  bar.style.top = `${top}px`;
}

/**
 * Let the selection take on the colour of the colour that is hovered.
 *
 * readpaper does this: the text under the mouse already looks the way it
 * will look when the colour is really chosen. Moving away puts the old
 * colour back.
 */
function previewColor(name) {
  const container = $("#pdf-container");
  if (!container) return;
  for (const color of ANNOTATION_COLORS) {
    container.classList.remove(`preview-${color.name}`);
  }
  if (name) container.classList.add(`preview-${name}`);
}

/** Take the bar away. */
function hideSelBar() {
  const bar = $("#sel-bar");
  if (bar) bar.hidden = true;
  const idea = $("#sel-idea");
  if (idea) idea.hidden = true;
  previewColor(null);
  pendingMark = null;
}

/** Save the highlight that is waiting for a colour. */
async function createMark(color, idea) {
  if (!pendingMark) return;
  // A frame around a figure is not a highlight: it is told apart.
  const isArea = (pendingMark.rects || []).some((rect) => rect.kind === "area");
  const body = {
    pageNumber: pendingMark.pageNumber,
    text: pendingMark.text,
    idea,
    rects: pendingMark.rects,
    color,
  };
  let created;
  try {
    created = await apiJson(`/api/papers/${paper.id}/annotations`, "POST", body);
  } catch (error) {
    toast(`保存失败：${error.message}`);
    return;
  }
  paper.annotations.push(created);
  viewer?.addAnnotation(created);
  renderAnnotations();
  hideSelBar();
  // The selection is used up; keeping it would only confuse.
  window.getSelection()?.removeAllRanges();
  toast(idea ? "标注已保存" : isArea ? "已添加框选，点它可以换颜色" : "已高亮");
}


/* ------------------------------------------------------------------ */
/* the popup on a highlight that is already there                      */
/* ------------------------------------------------------------------ */

// The annotation the popup belongs to, and the page it is drawn on.
let popupAnnot = null;
let popupPage = null;
// Set while the page is scrolled to make room for the box of a thought, so
// the scroll is not taken for the need of another one.
let noteScrolled = false;

/**
 * The place the highlight takes up.
 *
 * A highlight over several lines is drawn as several rectangles, so the
 * frame around it has to hold all of them: the smallest box that covers
 * every one of them.
 */
function popupFrameRect() {
  if (!popupAnnot || !popupPage || !popupPage.isConnected) return null;
  const boxes = [
    ...popupPage.querySelectorAll(`.pdf-highlight[data-annot-id="${popupAnnot.id}"]`),
  ];
  let left = Infinity;
  let top = Infinity;
  let right = -Infinity;
  let bottom = -Infinity;
  for (const box of boxes) {
    const r = box.getBoundingClientRect();
    if (!r.width && !r.height) continue;
    left = Math.min(left, r.left);
    top = Math.min(top, r.top);
    right = Math.max(right, r.right);
    bottom = Math.max(bottom, r.bottom);
  }
  if (!Number.isFinite(left)) return null;
  return { left, top, right, bottom, width: right - left, height: bottom - top };
}

/** The colour of the frame: the colour of the highlight itself. */
function applyPopupColor() {
  const popup = $("#annot-popup");
  if (!popup || !popupAnnot) return;
  const color = ANNOTATION_COLORS.find((item) => item.name === popupAnnot.color);
  popup.style.setProperty("--annot-color", color?.hex || "#3c78d8");
}

/**
 * Put the popup on a highlight.
 *
 * The dashed frame sits exactly over the text that is highlighted: the ×
 * is on its top-right corner, the colours and the button for a thought on
 * its bottom-right one.
 */
function showAnnotPopup(hit) {
  const annot = paper.annotations.find((item) => item.id === hit.id);
  if (!annot) return;
  popupAnnot = annot;
  popupPage = hit.page;
  const popup = $("#annot-popup");
  if (!popup) return;
  popup.hidden = false;
  const tools = $("#annot-popup-tools");
  const note = $("#annot-popup-note");
  if (tools) tools.hidden = false;
  // A highlight that has a thought shows it in a box above the frame; one
  // without a thought shows nothing until the button is used.
  const idea = (annot.idea || "").trim();
  if (note) note.hidden = !idea;
  const input = $("#annot-popup-note-input");
  if (input) input.value = annot.idea || "";
  applyPopupColor();
  // The popup needs its width before the box for the thought can know how
  // the text is wrapped in it.
  positionAnnotPopup();
  growNoteInput();
  placePopupNote();
}

/** Keep the popup on its highlight: the page scrolls and zooms. */
function positionAnnotPopup() {
  const popup = $("#annot-popup");
  if (!popup || popup.hidden || !popupAnnot) return;
  const frame = popupFrameRect();
  // The page is being drawn again: the box is not there yet, but it will
  // be - the reader is told when it is.
  if (!frame) return;
  const main = $(".reader-main");
  const box = main.getBoundingClientRect();
  popup.style.width = `${frame.width}px`;
  popup.style.height = `${frame.height}px`;
  popup.style.left = `${frame.left - box.left}px`;
  popup.style.top = `${frame.top - box.top}px`;
  placePopupNote();
}

/** Take the popup away. */
function hideAnnotPopup() {
  const input = $("#annot-popup-note-input");
  const annot = popupAnnot;
  // A thought that was written but not saved is saved on the way out.
  if (
    input &&
    annot &&
    paper?.annotations?.some((item) => item.id === annot.id) &&
    input.value.trim() !== (annot.idea || "").trim()
  ) {
    savePopupIdea();
  }
  const popup = $("#annot-popup");
  if (popup) popup.hidden = true;
  popupAnnot = null;
  popupPage = null;
  noteScrolled = false;
}

/** Open the box for a thought, above the frame. */
function openPopupNote() {
  const note = $("#annot-popup-note");
  if (!note) return;
  note.hidden = false;
  const input = $("#annot-popup-note-input");
  if (input) {
    input.value = popupAnnot?.idea || "";
    growNoteInput();
    placePopupNote();
    input.focus();
    input.select();
  }
}

/**
 * The box for a thought is five lines high, and grows when the thought
 * needs more room.
 */
function growNoteInput() {
  const input = $("#annot-popup-note-input");
  if (!input) return;
  input.style.height = "auto";
  input.style.height = `${input.scrollHeight}px`;
}

/**
 * Put the box for the thought where it fits.
 *
 * It belongs above the frame. A highlight near the top of the window has no
 * room there: then the page is scrolled a little, so the box still hangs
 * above the frame. Only when the page cannot be scrolled any further does
 * the box go below the frame - where it can at least be read.
 */
function placePopupNote() {
  const popup = $("#annot-popup");
  const note = $("#annot-popup-note");
  const input = $("#annot-popup-note-input");
  if (!popup || !note || !input || note.hidden) return;
  const frame = popupFrameRect();
  if (!frame) return;
  const main = $(".reader-main");
  const box = main.getBoundingClientRect();
  // The space above and below the frame.
  const roomAbove = frame.top - box.top;
  const roomBelow = box.bottom - frame.bottom;
  // The height the thought would like to have: the box of the text, the
  // padding around it and the gap that keeps it off the frame.
  input.style.maxHeight = "none";
  const wanted = input.offsetHeight + 22;
  input.style.maxHeight = "";
  if (roomAbove < wanted && !noteScrolled) {
    // Scroll the page down, so the box for the thought has room above the
    // frame. The page follows, so the box is measured again afterwards.
    const container = $("#pdf-container");
    if (container && container.scrollHeight > container.clientHeight + 2) {
      noteScrolled = true;
      container.scrollTop += wanted - roomAbove;
      positionAnnotPopup();
      noteScrolled = false;
      return;
    }
  }
  const below = roomAbove < wanted && roomBelow > roomAbove;
  note.classList.toggle("below", below);
  popup.classList.toggle("note-below", below);
  const room = Math.max(48, (below ? roomBelow : roomAbove) - 22);
  popup.style.setProperty("--note-max", `${room}px`);
  popup.style.setProperty("--note-h", `${note.offsetHeight}px`);
}

/** Leave the box for a thought. */
function closePopupNote() {
  const note = $("#annot-popup-note");
  if (note) note.hidden = true;
}

/**
 * Take over what the server has to say about a highlight.
 *
 * Only the words are taken: the rectangles come back as a new list, and
 * the boxes on the page know the old one.
 */
function mergeAnnotation(annot, saved) {
  if (typeof saved.color === "string") annot.color = saved.color;
  if (typeof saved.idea === "string") annot.idea = saved.idea;
  if (typeof saved.text === "string") annot.text = saved.text;
  return annot;
}

/** Save the thought of the highlight the popup is on. */
async function savePopupIdea() {
  const input = $("#annot-popup-note-input");
  // The annotation is taken now: the window may be closed while the server
  // is asked.
  const annot = popupAnnot;
  if (!input || !annot) return;
  const value = input.value.trim();
  if (value === (annot.idea || "").trim()) {
    // Nothing was written: a highlight without a thought has no box.
    if (!value) closePopupNote();
    return;
  }
  try {
    const saved = await apiJson(`/api/annotations/${annot.id}`, "PATCH", { idea: value });
    mergeAnnotation(annot, saved);
  } catch (error) {
    toast(`保存失败：${error.message}`);
    input.value = annot.idea || "";
    return;
  }
  renderAnnotations();
}

/** Give the highlight the popup is on another colour. */
async function setPopupColor(color) {
  if (!popupAnnot || color === popupAnnot.color) return;
  try {
    const saved = await apiJson(`/api/annotations/${popupAnnot.id}`, "PATCH", { color });
    mergeAnnotation(popupAnnot, saved);
  } catch (error) {
    toast(`保存失败：${error.message}`);
    return;
  }
  viewer?.setAnnotationColor(popupAnnot.id, color);
  applyPopupColor();
  renderAnnotations();
}

/* ------------------------------------------------------------------ */
/* the catalog of the document                                          */
/* ------------------------------------------------------------------ */

// The catalog is read once: it does not change while reading.
let outlineLoaded = false;

/** The catalog as a tree of links. */
function outlineHtml(items) {
  return `<ul class="outline-list">${items
    .map(
      (item) => `<li>
        <a class="outline-item" href="#" data-page="${item.pageNumber ?? ""}"
           data-top="${item.top ?? ""}">${escapeHtml(item.title)}</a>
        ${item.items && item.items.length ? outlineHtml(item.items) : ""}
      </li>`
    )
    .join("")}</ul>`;
}

/** Open the catalog and show what the PDF has to offer. */
async function showOutline() {
  const list = $("#outline-list");
  if (!list) return;
  if (!outlineLoaded) {
    list.innerHTML = `<div class="outline-empty">正在读取目录…</div>`;
    const items = (await viewer?.getOutline()) || [];
    outlineLoaded = true;
    list.innerHTML = items.length
      ? outlineHtml(items)
      : `<div class="outline-empty">这份 PDF 没有目录</div>`;
    list.querySelectorAll(".outline-item").forEach((node) => {
      node.addEventListener("click", (event) => {
        event.preventDefault();
        const page = Number(node.dataset.page);
        if (!page) return;
        const top = node.dataset.top === "" ? null : Number(node.dataset.top);
        viewer?.goToDest(page, top);
      });
    });
  }
  toggleLeftDrawer(true);
}

/** Open or close the catalog. */
function toggleLeftDrawer(open) {
  const root = $(".reader");
  if (!root) return;
  const on = open ?? !root.classList.contains("left-open");
  root.classList.toggle("left-open", on);
  const button = $("#toggle-left");
  if (button) {
    button.classList.toggle("on", on);
    button.setAttribute("aria-expanded", on ? "true" : "false");
    // The arrow points at what the next click will do.
    button.innerHTML = on ? ICONS.panelClose : ICONS.panelOpen;
    button.title = on ? "收起目录" : "显示目录";
  }
}

/* ------------------------------------------------------------------ */
/* searching in the document                                            */
/* ------------------------------------------------------------------ */

let findTimer = null;

/** How many hits there are, and which one is looked at. */
function updateFindCount() {
  const count = $("#find-count");
  if (!count) return;
  const total = viewer?.getFindCount() || 0;
  if (!total) {
    count.textContent = "0 / 0";
    return;
  }
  count.textContent = `${(viewer?.getFindIndex() || 0) + 1} / ${total}`;
}

/** Look for a text and mark where it is. */
async function runFind(query) {
  if (!query.trim()) {
    viewer?.clearFinds();
    updateFindCount();
    return;
  }
  const { matches } = (await viewer?.find(query)) || { matches: [] };
  viewer?.showFinds(matches, 0);
  updateFindCount();
  if (matches.length) await viewer?.goToFind(0);
  else {
    const count = $("#find-count");
    if (count) count.textContent = "没有找到";
  }
}

/** Put the search away and take the marks off the page. */
function closeFind() {
  const bar = $("#find-bar");
  if (bar) bar.hidden = true;
  viewer?.clearFinds();
  const input = $("#find-input");
  if (input) input.value = "";
}

/* ------------------------------------------------------------------ */
/* where am I: the page and the size                                    */
/* ------------------------------------------------------------------ */

/** The page number and the total, in the bar at the bottom. */
function updatePageIndicator() {
  const input = $("#pdf-page-input");
  // While the number is being typed out, it is left alone.
  if (input && document.activeElement !== input) input.value = String(currentPage);
  const total = $("#pdf-page-total");
  if (total) total.textContent = `/ ${totalPages || "-"}`;
}

async function patch(patchBody) {
  const updated = await apiJson(`/api/papers/${paper.id}`, "PATCH", patchBody);
  paper.tags = updated.tags;
  paper.folders = updated.folders;
  paper.importance = updated.importance;
  paper.isRead = updated.isRead;
  paper.remark = updated.remark;
  paper.notes = updated.notes;
  paper.title = updated.title;
  paper.authors = updated.authors;
  paper.year = updated.year;
}

/**
 * Patch the paper and report a failure.
 *
 * Returns false when the change did not make it to the server, so the
 * caller can leave the page showing what is really stored.
 */
async function patchWithFeedback(patchBody) {
  try {
    await patch(patchBody);
    return true;
  } catch (error) {
    toast(`保存失败：${error.message}`);
    return false;
  }
}

/** The size of the page, in per cent, in the bar at the bottom. */
function updateZoomLevel(scale) {
  const level = $("#pdf-zoom-level");
  if (level) level.textContent = `${Math.round(scale * 100)}%`;
}

async function mountViewer() {
  const container = $("#pdf-container");
  if (!container) return;
  if (viewer) {
    viewer.destroy();
    viewer = null;
  }
  try {
    viewer = await mountPdfViewer(container, `/api/papers/${paper.id}/file`, paper.annotations, {
      onLoaded: (total) => {
        totalPages = total;
        updatePageIndicator();
      },
      onPage: (page) => {
        currentPage = page;
        updatePageIndicator();
      },
      onZoom: (scale) => {
        updateZoomLevel(scale);
        positionAnnotPopup();
      },
      // A page that is drawn again takes its highlight with it: the popup
      // on it has to find its place.
      onPainted: () => positionAnnotPopup(),
    });
    totalPages = viewer.numPages;
    updatePageIndicator();
    updateZoomLevel(viewer.getScale());
  } catch (error) {
    container.innerHTML = `<div class="empty">PDF 加载失败：${escapeHtml(error.message)}</div>`;
  }
}

function bindChipActions() {
  $("#add-tag")?.addEventListener("click", () => {
    // The tags this paper already carries are of no use here.
    const own = new Set(paper.tags.map((t) => t.name));
    openTagPicker(
      libraryTags.map((t) => t.name).filter((name) => !own.has(name)),
      async (name) => {
        if (await patchWithFeedback({ tags: [...paper.tags.map((t) => t.name), name] })) {
          toast("标签已更新");
          refreshChips();
        }
      }
    );
  });

  $("#add-folder")?.addEventListener("click", () => {
    openFolderPicker(folders, "添加分类", paper.folders.map((f) => f.id), async (ids) => {
      if (await patchWithFeedback({ folderIds: ids })) {
        toast("分类已更新");
        refreshChips();
      }
    });
  });

  document.querySelectorAll("[data-remove-tag]").forEach((node) =>
    node.addEventListener("click", async () => {
      const name = node.dataset.removeTag;
      const ok = await patchWithFeedback({
        tags: paper.tags.filter((t) => t.name !== name).map((t) => t.name),
      });
      if (ok) refreshChips();
    })
  );

  document.querySelectorAll("[data-remove-folder]").forEach((node) =>
    node.addEventListener("click", async () => {
      const id = Number(node.dataset.removeFolder);
      const ok = await patchWithFeedback({
        folderIds: paper.folders.filter((f) => f.id !== id).map((f) => f.id),
      });
      if (ok) refreshChips();
    })
  );
}

/** Open or close the side panel with the fields of the paper. */
function toggleSidePanel() {
  const root = $(".reader");
  if (!root) return;
  const open = root.classList.toggle("side-open");
  const button = $("#toggle-side");
  if (button) {
    button.classList.toggle("on", open);
    button.setAttribute("aria-expanded", open ? "true" : "false");
    // The arrow points at what the next click will do: open the panel or
    // push it away again.
    button.innerHTML = open ? ICONS.panelOpen : ICONS.panelClose;
    button.title = open ? "收起信息侧栏" : "显示信息侧栏";
  }
}

function bind() {
  $("#download-paper")?.addEventListener("click", () => {
    // The server sends it as an attachment, named after the paper.
    window.location.href = `/api/papers/${paper.id}/file?download=true`;
  });

  // The side panel starts closed: the PDF gets the whole width. Its own
  // little button opens it.
  $("#toggle-side")?.addEventListener("click", () => {
    toggleSidePanel();
  });

  document.addEventListener("click", (event) => {
    if (event.target.closest("#sel-bar") || event.target.closest("#sel-idea")) return;
    if (event.target.closest("#annot-popup")) return;
    // The click that ends a text selection is not a click on empty space:
    // the bar belongs to that selection, so it stays.
    if (window.getSelection()?.toString().trim()) return;
    hideSelBar();
    // The popup on a highlight is closed by the PDF itself: it knows
    // whether the click landed on a highlight or on empty paper.
    if (!event.target.closest("#pdf-container")) hideAnnotPopup();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      hideSelBar();
      closeFind();
    }
  });

  $("#pdf-zoom-in")?.addEventListener("click", async () => viewer && viewer.zoom(1));
  $("#pdf-zoom-out")?.addEventListener("click", async () => viewer && viewer.zoom(-1));
  $("#pdf-fit-width")?.addEventListener("click", async () => viewer && viewer.fitWidth());

  $("#stars-editor")?.addEventListener("click", async (event) => {
    const editor = event.currentTarget;
    const index = [...editor.children].indexOf(event.target);
    if (index < 0) return;
    const value = index + 1 === paper.importance ? 0 : index + 1;
    const ok = await patchWithFeedback({ importance: value });
    // The stars only change when the server took them.
    editor.innerHTML = starSpans(ok ? value : paper.importance);
  });

  $("#read-toggle")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const next = !paper.isRead;
    // Same as in the library: the status is easy to change by accident, so
    // ask before it changes.
    const answer = await confirmDialog(
      next ? "确定把这篇文献标记为已读？" : "确定把这篇文献标记为未读？",
      { title: "更改已读状态", confirmText: next ? "标记已读" : "标记未读" }
    );
    if (!answer) return;
    const ok = await patchWithFeedback({ isRead: next });
    if (!ok) return;
    button.classList.toggle("on", next);
    button.textContent = next ? "已读" : "未读";
    toast(next ? "已标记为已读" : "已标记为未读");
  });

  bindChipActions();

  // ------------------------------------------ making a highlight
  markChosenColor();
  const bar = $("#sel-bar");
  // Pressing the bar must not clear the selection: the mark is still
  // waiting for its colour.
  bar?.addEventListener("mousedown", (event) => event.preventDefault());
  bar?.addEventListener("click", async (event) => {
    const button = event.target.closest(".sel-dot");
    if (!button) return;
    await createMark(button.dataset.color, "");
  });
  // Hovering a colour shows what the text will look like.
  bar?.querySelectorAll(".sel-dot").forEach((dot) => {
    dot.addEventListener("mouseenter", () => previewColor(dot.dataset.color));
    dot.addEventListener("mouseleave", () => previewColor(null));
  });

  $("#sel-idea-btn")?.addEventListener("click", () => {
    const idea = $("#sel-idea");
    if (!idea) return;
    idea.hidden = false;
    $("#sel-idea-input")?.focus();
  });
  $("#sel-idea")?.addEventListener("mousedown", (event) => event.preventDefault());
  $("#sel-idea")?.addEventListener("click", (event) => {
    const button = event.target.closest(".sel-pick");
    if (!button) return;
    chosenColor = button.dataset.color;
    markChosenColor();
  });
  $("#sel-idea-save")?.addEventListener("click", async () => {
    const input = $("#sel-idea-input");
    await createMark(chosenColor, input?.value.trim() || "");
  });
  $("#sel-idea-input")?.addEventListener("keydown", async (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    await createMark(chosenColor, event.target.value.trim() || "");
  });

  // ------------------------------------------ the popup on a highlight
  // The popup must not take the selection away while it is used.
  $("#annot-popup-x")?.addEventListener("mousedown", (event) => event.preventDefault());
  $("#annot-popup-tools")?.addEventListener("mousedown", (event) => event.preventDefault());

  $("#annot-popup-x")?.addEventListener("click", async () => {
    if (!popupAnnot) return;
    const id = popupAnnot.id;
    try {
      await apiJson(`/api/annotations/${id}`, "DELETE");
    } catch (error) {
      toast(`删除失败：${error.message}`);
      return;
    }
    paper.annotations = paper.annotations.filter((item) => item.id !== id);
    viewer?.removeAnnotation(id);
    renderAnnotations();
    hideAnnotPopup();
    toast("标注已删除");
  });

  $("#annot-popup-tools")?.addEventListener("click", async (event) => {
    const dot = event.target.closest(".sel-dot");
    if (!dot) return;
    await setPopupColor(dot.dataset.color);
  });

  $("#annot-popup-idea")?.addEventListener("click", () => openPopupNote());
  $("#annot-popup-note-input")?.addEventListener("keydown", async (event) => {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      await savePopupIdea();
    } else if (event.key === "Escape") {
      event.preventDefault();
      event.target.value = popupAnnot?.idea || "";
      // A highlight with a thought keeps its box.
      if (!(popupAnnot?.idea || "").trim()) closePopupNote();
    }
  });
  $("#annot-popup-note-input")?.addEventListener("input", () => {
    growNoteInput();
    placePopupNote();
  });
  $("#annot-popup-note-input")?.addEventListener("blur", () => savePopupIdea());

  // ------------------------------------------ the catalog
  $("#toggle-left")?.addEventListener("click", async () => {
    const root = $(".reader");
    if (root?.classList.contains("left-open")) {
      toggleLeftDrawer(false);
      return;
    }
    await showOutline();
  });

  // ------------------------------------------ searching
  $("#pdf-find-btn")?.addEventListener("click", () => {
    const findBar = $("#find-bar");
    if (!findBar) return;
    findBar.hidden = false;
    $("#find-input")?.focus();
  });
  $("#find-input")?.addEventListener("input", (event) => {
    clearTimeout(findTimer);
    const query = event.target.value;
    findTimer = setTimeout(() => runFind(query), 250);
  });
  $("#find-input")?.addEventListener("keydown", async (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      const step = event.shiftKey ? -1 : 1;
      await viewer?.goToFind((viewer?.getFindIndex() || 0) + step);
      updateFindCount();
    } else if (event.key === "Escape") {
      closeFind();
    }
  });
  $("#find-prev")?.addEventListener("click", async () => {
    await viewer?.goToFind((viewer?.getFindIndex() || 0) - 1);
    updateFindCount();
  });
  $("#find-next")?.addEventListener("click", async () => {
    await viewer?.goToFind((viewer?.getFindIndex() || 0) + 1);
    updateFindCount();
  });
  $("#find-close")?.addEventListener("click", () => closeFind());

  // ------------------------------------------ jumping to a page
  $("#pdf-page-input")?.addEventListener("keydown", async (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      const page = Number(event.target.value);
      if (page >= 1 && page <= totalPages) await viewer?.goToPage(page);
      event.target.blur();
      updatePageIndicator();
    } else if (event.key === "Escape") {
      event.target.value = String(currentPage);
      event.target.blur();
    }
  });
  $("#pdf-page-input")?.addEventListener("blur", () => updatePageIndicator());

  // ------------------------------------------ drawing a frame
  $("#frame-toggle")?.addEventListener("click", () => {
    areaMode = !areaMode;
    const button = $("#frame-toggle");
    button.classList.toggle("on", areaMode);
    button.setAttribute("aria-pressed", areaMode ? "true" : "false");
    button.title = areaMode
      ? "框选中：在页面上拖一个框，松开鼠标就画好了（再点一下退出）"
      : "框选：在页面上拖一个框";
    $(".reader")?.classList.toggle("area-mode", areaMode);
    if (areaMode) hideSelBar();
  });

  const container = $("#pdf-container");

  container?.addEventListener("mousedown", (event) => {
    if (!areaMode || event.button !== 0) return;
    const page = event.target.closest(".pdf-page");
    if (!page) return;
    // No text selection while a frame is being drawn.
    event.preventDefault();
    dragStart = { x: event.clientX, y: event.clientY, page: Number(page.dataset.page) };
    dragBox = document.createElement("div");
    dragBox.className = "pdf-area-preview";
    container.appendChild(dragBox);
  });

  container?.addEventListener("mousemove", (event) => {
    if (!dragStart || !dragBox) return;
    const box = container.getBoundingClientRect();
    dragBox.style.left = `${Math.min(event.clientX, dragStart.x) - box.left + container.scrollLeft}px`;
    dragBox.style.top = `${Math.min(event.clientY, dragStart.y) - box.top + container.scrollTop}px`;
    dragBox.style.width = `${Math.abs(event.clientX - dragStart.x)}px`;
    dragBox.style.height = `${Math.abs(event.clientY - dragStart.y)}px`;
  });

  container?.addEventListener("mouseup", async (event) => {
    if (!dragStart) return;
    const start = dragStart;
    dragStart = null;
    dragBox?.remove();
    dragBox = null;
    const rect = {
      left: Math.min(event.clientX, start.x),
      top: Math.min(event.clientY, start.y),
      width: Math.abs(event.clientX - start.x),
      height: Math.abs(event.clientY - start.y),
    };
    // A click is not a frame.
    if (rect.width < 6 || rect.height < 6) return;
    const stored = await viewer?.rectFromClient(start.page, rect);
    if (!stored) return;
    // readpaper does it this way: the frame is on the page the moment the
    // mouse is let go. Nothing has to be picked afterwards - the colour of
    // the frame is changed later by clicking on it.
    pendingMark = {
      pageNumber: start.page,
      text: viewer.textInArea(start.page, rect),
      rects: [{ ...stored, kind: "area" }],
    };
    await createMark(chosenColor, "");
  });

  // Picking some text: the bar shows up under it. The listener sits on the
  // document, so a selection that is finished outside the PDF still counts.
  document.addEventListener("mouseup", () => {
    if (areaMode) return;
    const info = viewer?.selectionInfo();
    if (!info) {
      hideSelBar();
      return;
    }
    // The same text as before: the box for a thought stays where it is.
    const same =
      pendingMark && pendingMark.text === info.text && pendingMark.pageNumber === info.pageNumber;
    pendingMark = { pageNumber: info.pageNumber, text: info.text, rects: info.rects };
    showSelBar(info.anchor, same);
  });

  // Clicking a highlight that is already there opens the popup on it.
  container?.addEventListener("click", (event) => {
    // A selection that was just made is not a click on a highlight.
    if (window.getSelection()?.toString().trim()) return;
    const hit = viewer?.annotationAt(event.clientX, event.clientY);
    if (!hit) {
      hideAnnotPopup();
      return;
    }
    showAnnotPopup(hit);
  });

  // The bar belongs to the selection: scrolling away leaves it behind.
  container?.addEventListener("scroll", () => {
    hideSelBar();
    // The popup on a highlight stays, but follows the text.
    positionAnnotPopup();
  });

  document.querySelectorAll("[data-field]").forEach((node) => {
    node.addEventListener("input", () => {
      const field = node.dataset.field;
      const value = node.value;
      clearTimeout(saveTimers.get(field));
      saveTimers.set(
        field,
        setTimeout(async () => {
          saveTimers.delete(field);
          // The year is a number on the server: an empty box means "no year",
          // not an empty string.
          const body =
            field === "year" ? { year: value === "" ? null : Number(value) } : { [field]: value };
          if (field === "year" && value !== "" && Number.isNaN(Number(value))) return;
          await patchWithFeedback(body);
        }, 400)
      );
    });
  });
}

render();
// Opening the paper bumps the read counter. The 已读 flag itself is only
// ever changed by an explicit user action.
apiJson(`/api/papers/${paper.id}`, "PATCH", { markRead: true }).catch(() => {});
