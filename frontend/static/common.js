/* Shared helpers for the library page and the standalone reader page. */

export const $ = (selector, root = document) => root.querySelector(selector);

export const el = (html) => {
  const tpl = document.createElement("template");
  tpl.innerHTML = html.trim();
  return tpl.content.firstElementChild;
};

export const escapeHtml = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]
  );

/**
 * A link that is safe to put in an href.
 *
 * Only http(s) links are kept: a stored "javascript:" or "data:" url would
 * run in the page when it is clicked.
 */
export const safeUrl = (value) => {
  const url = String(value ?? "").trim();
  if (!/^https?:\/\//i.test(url)) return "";
  return url;
};

export async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let detail = response.statusText;
    let body = null;
    try {
      body = await response.json();
      detail = body.detail || detail;
    } catch (_) {
      /* ignore */
    }
    const error = new Error(detail);
    // The whole answer is kept, so a caller can look at fields the message
    // does not carry (the id of a duplicate paper, say).
    error.data = body;
    throw error;
  }
  return response.status === 204 ? null : response.json();
}

export const apiJson = (path, method, body) =>
  api(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export function toast(message) {
  const node = document.getElementById("toast");
  if (!node) return;
  node.textContent = message;
  node.classList.add("show");
  clearTimeout(node._timer);
  node._timer = setTimeout(() => node.classList.remove("show"), 2200);
}

export const ICONS = {
  library:
    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>',
  folder:
    '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>',
  chevron:
    '<svg class="chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>',
  file:
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>',
  link:
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>',
  search:
    '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>',
  filter:
    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M3 6h18M6 12h12M10 18h4"/></svg>',
  plus:
    '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>',
  // A dashed frame: drawing one around a figure.
  frame:
    '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="4 3"><rect x="3.5" y="3.5" width="17" height="17" rx="2"/></svg>',
  external:
    '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><path d="M15 3h6v6M10 14 21 3"/></svg>',
  trash:
    '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14"/></svg>',
  download:
    '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/></svg>',
  more:
    '<svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="1.7"/><circle cx="12" cy="12" r="1.7"/><circle cx="19" cy="12" r="1.7"/></svg>',
  pencil:
    '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 013 3L7 19l-4 1 1-4z"/></svg>',
  check:
    '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>',
  close:
    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg>',
  // The two arrows of the side panel button: the icon points at what the
  // next click will do.
  panelClose:
    '<svg class="chev-left" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 17l-5-5 5-5"/><path d="M18 17l-5-5 5-5"/></svg>',
  panelOpen:
    '<svg class="chev-right" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 17l5-5-5-5"/><path d="M6 17l5-5-5-5"/></svg>',
};

/** Flatten the folder tree into a list with a depth marker and a full path. */
export function flattenFolders(nodes, depth = 0, parentPath = "") {
  const out = [];
  for (const node of nodes || []) {
    const path = parentPath ? `${parentPath} / ${node.name}` : node.name;
    out.push({ ...node, depth, path, parentPath });
    out.push(...flattenFolders(node.children || [], depth + 1, path));
  }
  return out;
}

/**
 * The full path of every folder ("CV / 点云 / 地图"), keyed by folder id.
 *
 * A folder name alone does not identify a folder: the same name can live
 * under different parents, so everything that shows a folder outside of the
 * tree itself needs the path.
 */
export function folderPaths(nodes) {
  const paths = new Map();
  for (const node of flattenFolders(nodes)) paths.set(node.id, node.path);
  return paths;
}

/* -------------------------------- modals -------------------------------- */

// The key handler of the modal that is currently open. Kept around so it
// can be removed when the modal goes away.
let modalKeyHandler = null;
// Set while a dialog waits for an answer. It is called when the modal goes
// away, so the dialog can settle its promise instead of hanging.
let modalCloseHook = null;

export function closeModal() {
  const root = document.getElementById("modal-root");
  if (root) root.innerHTML = "";
  if (modalKeyHandler) {
    document.removeEventListener("keydown", modalKeyHandler);
    modalKeyHandler = null;
  }
  if (modalCloseHook) {
    const hook = modalCloseHook;
    modalCloseHook = null;
    hook();
  }
}

export function openModal(html, onMount, wide = false) {
  const root = document.getElementById("modal-root");
  if (!root) return;
  // A modal that is replaced (not closed) must not leave its key handler
  // behind.
  if (modalKeyHandler) {
    document.removeEventListener("keydown", modalKeyHandler);
    modalKeyHandler = null;
  }
  // A dialog that waits for an answer loses it when another modal takes
  // its place - that counts as a cancel.
  if (modalCloseHook) {
    const hook = modalCloseHook;
    modalCloseHook = null;
    hook();
  }
  root.innerHTML = `<div class="modal-mask"><div class="modal${
    wide ? " wide" : ""
  }" role="dialog" aria-modal="true">${html}</div></div>`;
  root.querySelector(".modal-mask").addEventListener("click", (event) => {
    if (event.target.classList.contains("modal-mask")) closeModal();
  });
  root.querySelectorAll("[data-close]").forEach((node) =>
    node.addEventListener("click", closeModal)
  );
  // Escape closes the modal - the same way the close button does.
  modalKeyHandler = (event) => {
    if (event.key === "Escape") closeModal();
  };
  document.addEventListener("keydown", modalKeyHandler);
  if (onMount) onMount(root);
}

/**
 * A yes / no dialog. The promise resolves to true when the user confirms
 * and to false when they cancel, close the dialog or press Escape.
 */
export function confirmDialog(message, options = {}) {
  const { title = "确认", confirmText = "确定", cancelText = "取消" } = options;
  return new Promise((resolve) => {
    let answered = false;
    const finish = (value) => {
      if (answered) return;
      answered = true;
      resolve(value);
      closeModal();
    };
    openModal(
      `<header>${escapeHtml(title)}<button class="icon-btn" data-close>${ICONS.close}</button></header>
       <div class="body">
         <p class="confirm-text">${escapeHtml(message)}</p>
       </div>
       <footer>
         <button class="btn" data-close>${escapeHtml(cancelText)}</button>
         <button class="btn primary" data-confirm>${escapeHtml(confirmText)}</button>
       </footer>`,
      (root) => {
        root.querySelector("[data-confirm]").addEventListener("click", () => finish(true));
        root.querySelector(".btn.primary").focus();
      }
    );
    // From now on every way out of the modal counts as a cancel: the close
    // button, the mask, Escape.
    modalCloseHook = () => finish(false);
  });
}

/** Folder picker; returns the selected folder ids through the callback. */
export function openFolderPicker(folders, title, selected, onPick) {
  // Names can repeat under different parents; those entries say which
  // parent they hang under, otherwise they are impossible to tell apart.
  const nameCounts = new Map();
  for (const folder of flattenFolders(folders)) {
    nameCounts.set(folder.name, (nameCounts.get(folder.name) || 0) + 1);
  }
  const selectedIds = (selected || []).map(Number);

  // Everything starts folded, but the folders that are already selected have
  // to stay visible, so their parents are opened.
  const openIds = new Set();
  const markOpen = (nodes) => {
    let hit = false;
    for (const node of nodes || []) {
      if (selectedIds.includes(Number(node.id))) hit = true;
      if (markOpen(node.children || [])) {
        openIds.add(node.id);
        hit = true;
      }
    }
    return hit;
  };
  markOpen(folders);

  // The tree behaves like the sidebar: click a name to fold its children
  // away, click it again to bring them back.
  const renderNodes = (nodes, depth, parentName) =>
    (nodes || [])
      .map((node) => {
        const children = node.children || [];
        const ambiguous = (nameCounts.get(node.name) || 0) > 1;
        const folded = children.length > 0 && !openIds.has(node.id);
        return `<li class="picker-node">
          <div class="picker-row" style="padding-left:${6 + depth * 18}px">
            ${
              children.length
                ? `<span class="picker-caret${folded ? " collapsed" : ""}" data-toggle="${node.id}">${ICONS.chevron}</span>`
                : `<span class="picker-caret blank"></span>`
            }
            <input type="checkbox" value="${node.id}" ${
              selectedIds.includes(Number(node.id)) ? "checked" : ""
            } />
            <span class="picker-name"${
              children.length ? ` data-toggle="${node.id}"` : ""
            }>${escapeHtml(node.name)}</span>
            ${
              ambiguous && parentName
                ? `<span class="picker-parent">（${escapeHtml(parentName)}）</span>`
                : ""
            }
          </div>
          ${
            children.length
              ? `<ul class="picker-children${folded ? " collapsed" : ""}" data-children="${node.id}">${renderNodes(
                  children,
                  depth + 1,
                  node.name
                )}</ul>`
              : ""
          }
        </li>`;
      })
      .join("");

  openModal(
    `<header>${escapeHtml(title)}<button class="icon-btn" data-close>${ICONS.close}</button></header>
     <div class="body">
       <div class="picker">
         <ul class="picker-tree">${renderNodes(folders, 0, "")}</ul>
       </div>
     </div>
     <footer>
       <button class="btn" data-close>取消</button>
       <button class="btn primary" id="picker-ok">确定</button>
     </footer>`,
    (root) => {
      root.querySelector(".picker").addEventListener("click", (event) => {
        const toggle = event.target.closest("[data-toggle]");
        if (!toggle) return;
        const children = root.querySelector(`[data-children="${toggle.dataset.toggle}"]`);
        if (!children) return;
        const collapsed = children.classList.toggle("collapsed");
        toggle.classList.toggle("collapsed", collapsed);
      });
      root.querySelector("#picker-ok").addEventListener("click", () => {
        const ids = [...root.querySelectorAll(".picker input:checked")].map((i) =>
          Number(i.value)
        );
        closeModal();
        onPick(ids);
      });
    },
    true
  );
}

/**
 * How well a name matches what the user typed. -1 means "no match".
 *
 * The better matches score higher: the exact name beats a prefix, a
 * prefix beats a name that merely contains the text, and a name that only
 * has the letters in the right order comes last.
 */
export function fuzzyScore(query, name) {
  const q = String(query || "").trim().toLowerCase();
  const t = String(name || "").toLowerCase();
  if (!q) return 0;
  if (t === q) return 1000;
  const at = t.indexOf(q);
  if (at === 0) return 800 - t.length;
  if (at > 0) return 600 - at - t.length;
  // The letters are all there, but not next to each other.
  let score = 0;
  let from = 0;
  let streak = 0;
  for (const ch of q) {
    const found = t.indexOf(ch, from);
    if (found < 0) return -1;
    streak = found === from ? streak + 1 : 0;
    score += 5 + streak * 3;
    from = found + 1;
  }
  return score;
}

/**
 * The names that match the query best, at most `limit` of them.
 *
 * An empty query keeps the order it was given in, so the caller can put
 * the most used names first.
 */
export function fuzzyMatch(query, names, limit = 20) {
  const list = names || [];
  if (!String(query || "").trim()) return list.slice(0, limit);
  const scored = [];
  for (const name of list) {
    const score = fuzzyScore(query, name);
    if (score >= 0) scored.push({ name, score });
  }
  scored.sort((a, b) => b.score - a.score || a.name.localeCompare(b.name));
  return scored.slice(0, limit).map((item) => item.name);
}

/**
 * Tag picker; hands the picked tag back through the callback.
 *
 * The existing tags are searched as the user types: the best matches are
 * listed (at most 20 of them) and clicking one picks it. Whatever is
 * typed can also be added as a new tag.
 */
export function openTagPicker(knownTags, onPick) {
  const known = knownTags || [];
  openModal(
    `<header>添加标签<button class="icon-btn" data-close>${ICONS.close}</button></header>
     <div class="body">
       <div class="field">
         <label>标签名称</label>
         <input type="text" id="tag-name" placeholder="输入后回车添加，或从下面选" />
       </div>
       <div class="field">
         <label>已有标签（模糊匹配，最多 20 个）</label>
         <div class="tag-suggestions" id="tag-suggestions"></div>
       </div>
     </div>
     <footer>
       <button class="btn" data-close>取消</button>
       <button class="btn primary" id="tag-ok">添加</button>
     </footer>`,
    (root) => {
      const input = root.querySelector("#tag-name");
      const list = root.querySelector("#tag-suggestions");

      const repaint = () => {
        const matches = fuzzyMatch(input.value, known, 20);
        list.innerHTML = matches.length
          ? matches
              .map(
                (name) =>
                  `<button class="tag-suggestion" data-tag="${escapeHtml(
                    name
                  )}">${escapeHtml(name)}</button>`
              )
              .join("")
          : `<div class="tag-suggestions-empty">没有匹配的标签，回车可以直接新建</div>`;
      };
      repaint();

      input.addEventListener("input", repaint);

      list.addEventListener("click", (event) => {
        const suggestion = event.target.closest("[data-tag]");
        if (!suggestion) return;
        closeModal();
        onPick(suggestion.dataset.tag);
      });

      const submit = () => {
        const name = input.value.trim();
        if (!name) return;
        closeModal();
        onPick(name);
      };
      root.querySelector("#tag-ok").addEventListener("click", submit);
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") submit();
      });
      input.focus();
    }
  );
}
