/* Paper Reader - library page (the reading view lives on its own page). */

import {
  $,
  el,
  api,
  apiJson,
  escapeHtml,
  toast,
  ICONS,
  flattenFolders,
  folderPaths,
  openModal,
  closeModal,
  confirmDialog,
  openFolderPicker,
  fuzzyMatch,
} from "/static/common.js";

const state = {
  papers: [],
  folders: [],
  // folderId -> full path ("CV / 点云 / 地图"), for showing a folder outside
  // of the tree where the name alone would be ambiguous.
  folderPaths: new Map(),
  tags: [],
  stats: { total: 0 },
  // How many of the papers in the current view are read / unread. The filter
  // dropdown shows these, not the counts of the whole library.
  readCounts: { read: 0, unread: 0 },
  query: "",
  // Text currently in the search box. Kept apart from `query` (the query that
  // was actually submitted) so that a re-render never wipes what is being typed.
  searchText: "",
  folder: "all",
  tag: "",
  read: "all",
  sort: "lastRead",
  order: "desc",
  page: 1,
  pageSize: 40,
  total: 0,
  unfiled: [],
  unfiledTotal: 0,
  showTags: false,
  // The widths of the columns of the paper list, in pixels. The title
  // column is not in here while it is flexible: it then takes whatever
  // the other columns leave over.
  colWidths: { tag: 190, remark: 150, stars: 120, read: 64 },
  titleFlexible: true,
  // Folders whose tree node is expanded (sub-folders + papers are shown).
  expanded: new Set(),
  // folderId -> papers filed directly in that folder (lazily loaded).
  folderPapers: new Map(),
  loadingFolders: new Set(),
  // "library" shows the paper list, "trash" the bin.
  view: "library",
  trash: [],
  trashSize: 0,
};

const star = (filled) => `<span class="${filled ? "on" : ""}">${filled ? "★" : "☆"}</span>`;

const starsHtml = (value) => {
  let out = "";
  for (let i = 1; i <= 5; i += 1) out += star(i <= value);
  return `<div class="stars" data-role="stars">${out}</div>`;
};

/* ------------------------------ loading ------------------------------- */

function papersQuery() {
  const params = new URLSearchParams();
  if (state.query) params.set("q", state.query);
  if (state.folder && state.folder !== "all") params.set("folder", state.folder);
  if (state.tag) params.set("tag", state.tag);
  if (state.read && state.read !== "all") params.set("read", state.read);
  params.set("sort", state.sort);
  params.set("order", state.order);
  params.set("limit", String(state.pageSize));
  params.set("offset", String((state.page - 1) * state.pageSize));
  return params;
}

async function loadAll() {
  const [page, folders, tags, stats, unfiled] = await Promise.all([
    api(`/api/papers?${papersQuery()}`),
    api("/api/folders"),
    api("/api/tags"),
    api("/api/stats"),
    api("/api/papers?folder=unfiled&limit=60"),
  ]);
  state.total = page.total;
  state.readCounts = {
    read: page.readCount || 0,
    unread: page.unreadCount || 0,
  };

  const maxPage = Math.max(1, Math.ceil(state.total / state.pageSize));
  if (state.page > maxPage) {
    // The result set shrank under us (filter changed, papers deleted), so the
    // page we asked for is now past the end. Jump to the last page that still
    // has rows and load it - otherwise the list renders empty.
    state.page = maxPage;
    const retry = await api(`/api/papers?${papersQuery()}`);
    state.papers = retry.items;
    state.total = retry.total;
    state.readCounts = {
      read: retry.readCount || 0,
      unread: retry.unreadCount || 0,
    };
  } else {
    state.papers = page.items;
  }

  state.unfiled = unfiled.items;
  state.unfiledTotal = unfiled.total || unfiled.items.length;
  state.folders = folders;
  state.folderPaths = folderPaths(folders);
  state.tags = tags;
  state.stats = stats;
}

async function refresh() {
  await loadAll();
  render();
}

// The list of tags changed (one was added or lost its last paper): the
// sidebar and the tag picker have to know.
async function refreshTags() {
  try {
    state.tags = await api("/api/tags");
    // The sidebar lists the tags, so it has to be drawn again: a tag that
    // was just added belongs in there.
    renderSidebar();
  } catch {
    // the tags are only used for picking, a failure here is not fatal
  }
}

function scrollListTop() {
  const content = $("#content");
  if (content) content.scrollTop = 0;
}

/* ------------------------------ rendering ----------------------------- */

/** Load the papers of one folder (lazily, when the folder is expanded). */
async function loadFolderPapers(folderId) {
  if (state.folderPapers.has(folderId) || state.loadingFolders.has(folderId)) return;
  state.loadingFolders.add(folderId);
  renderSidebar();
  try {
    const data = await api(`/api/folders/${folderId}/papers`);
    state.folderPapers.set(folderId, {
      items: data.items || [],
      total: data.total || 0,
      exclusive: data.exclusive || 0,
    });
  } catch {
    state.folderPapers.set(folderId, { items: [], total: 0, exclusive: 0 });
  }
  state.loadingFolders.delete(folderId);
  renderSidebar();
}

/** Drop the cached folder contents; called after anything that moves papers. */
function invalidateFolderPapers() {
  state.folderPapers.clear();
}

/** Load the trash bin (the papers that were deleted but kept their file). */
async function loadTrash() {
  try {
    const data = await api("/api/trash");
    state.trash = data.items || [];
    state.trashSize = data.totalSize || 0;
  } catch {
    state.trash = [];
    state.trashSize = 0;
  }
}

/** A file size in a form a human can read. */
function formatSize(bytes) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit > 0 && value < 10 ? 1 : 0)} ${units[unit]}`;
}

function findFolder(nodes, id) {
  for (const node of nodes) {
    if (String(node.id) === String(id)) return node;
    const hit = findFolder(node.children || [], id);
    if (hit) return hit;
  }
  return null;
}

/**
 * The label of a folder outside of the tree: its full path.
 *
 * The same name can live under different parents ("CV / 点云 / 地图" and
 * "SLAM / 点云 / 地图"), so the path is what identifies a folder.
 */
function folderLabel(folder) {
  return state.folderPaths.get(folder.id) || folder.name;
}

/**
 * Delete a folder. Folders are virtual: papers that another folder still
 * points at survive, the rest go away with their PDF.
 */
async function deleteFolder(folderId) {
  const node = findFolder(state.folders, folderId);
  if (!node) return;
  const subCount = folderSubtreeIds(node).length - 1;

  let exclusive = 0;
  try {
    const data = await api(`/api/folders/${folderId}/papers`);
    exclusive = data.exclusive || 0;
  } catch {
    // preview failed - the folder can still be deleted
  }

  const losses = [`分类「${folderLabel(node)}」`];
  if (subCount) losses.push(`它的 ${subCount} 个子分类`);
  if (exclusive) losses.push(`${exclusive} 篇只属于该分类的文献（移入垃圾箱）`);

  openModal(
    `<header>删除分类<button class="icon-btn" data-close>${ICONS.close}</button></header>
     <div class="body">
       <div class="danger-note">删除后无法恢复，将失去：</div>
       <ul class="loss-list">
         ${losses.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
       </ul>
       <p class="loss-note">其它分类里仍然存在的文献不受影响；移入垃圾箱的文献可以随时恢复。</p>
     </div>
     <footer>
       <button class="btn" data-close>取消</button>
       <button class="btn danger" id="delete-folder-ok">确认删除</button>
     </footer>`,
    (root) => {
      const confirmBtn = root.querySelector("#delete-folder-ok");
      confirmBtn.addEventListener("click", async () => {
        confirmBtn.disabled = true;
        try {
          const result = await api(`/api/folders/${folderId}`, { method: "DELETE" });
          closeModal();
          state.expanded.delete(Number(folderId));
          invalidateFolderPapers();
          if (String(state.folder) === String(folderId)) state.folder = "all";
          await refresh();
          const removed = result.trashedPapers?.length || 0;
          toast(removed ? `已删除分类，${removed} 篇文献已移入垃圾箱` : "已删除分类");
        } catch (error) {
          confirmBtn.disabled = false;
          toast(`删除失败：${error.message}`);
        }
      });
    }
  );
}

/** Ask for a new name and store it. */
function renameFolder(folderId) {
  const node = findFolder(state.folders, folderId);
  if (!node) return;

  openModal(
    `<header>重命名分类<button class="icon-btn" data-close>${ICONS.close}</button></header>
     <div class="body">
       <div class="field">
         <label>分类名称</label>
         <input type="text" id="folder-name" value="${escapeHtml(node.name)}" />
         <div class="hint">当前路径：${escapeHtml(folderLabel(node))}</div>
       </div>
     </div>
     <footer>
       <button class="btn" data-close>取消</button>
       <button class="btn primary" id="rename-ok">保存</button>
     </footer>`,
    (root) => {
      const input = root.querySelector("#folder-name");
      input.focus();
      input.select();
      const submit = async () => {
        const name = input.value.trim();
        if (!name) return;
        try {
          await apiJson(`/api/folders/${folderId}`, "PATCH", { name });
          closeModal();
          await refresh();
          toast("已重命名");
        } catch (error) {
          toast(`重命名失败：${error.message}`);
        }
      };
      root.querySelector("#rename-ok").addEventListener("click", submit);
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") submit();
      });
    }
  );
}

/** Create a folder below `parentId` (top-level when it is null). */
function createFolder(parentId) {
  const parent = parentId ? findFolder(state.folders, parentId) : null;
  const title = parent ? `在「${folderLabel(parent)}」下新建子分类` : "新建分类";

  openModal(
    `<header>${escapeHtml(title)}<button class="icon-btn" data-close>${ICONS.close}</button></header>
     <div class="body">
       <div class="field">
         <label>分类名称</label>
         <input type="text" id="folder-name" placeholder="输入分类名称" />
       </div>
     </div>
     <footer>
       <button class="btn" data-close>取消</button>
       <button class="btn primary" id="create-folder-ok">创建</button>
     </footer>`,
    (root) => {
      const input = root.querySelector("#folder-name");
      input.focus();
      const submit = async () => {
        const name = input.value.trim();
        if (!name) return;
        try {
          const created = await apiJson("/api/folders", "POST", {
            name,
            parentId: parentId || null,
          });
          closeModal();
          if (parentId) {
            state.expanded.add(Number(parentId));
            loadFolderPapers(Number(parentId));
          }
          await refresh();
          toast(`已创建分类「${created.name}」`);
        } catch (error) {
          toast(`创建失败：${error.message}`);
        }
      };
      root.querySelector("#create-folder-ok").addEventListener("click", submit);
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") submit();
      });
    }
  );
}

/** The paper as one of the lists on screen knows it. */
function findPaper(paperId) {
  const inList = state.papers.find((paper) => paper.id === paperId);
  if (inList) return inList;
  const unfiled = state.unfiled.find((paper) => paper.id === paperId);
  if (unfiled) return unfiled;
  for (const entry of state.folderPapers.values()) {
    const hit = entry.items.find((paper) => paper.id === paperId);
    if (hit) return hit;
  }
  return null;
}

/** The title of a paper as it is known to the sidebar. */
function paperTitle(paperId) {
  const paper = findPaper(paperId);
  return paper ? paper.title : "该文献";
}

/**
 * Delete a paper - or take it out of some of its folders.
 *
 * A paper can sit in several folders at once, and deleting it outright
 * throws all of them away. So the window asks what should really go: the
 * folders the paper is filed in (the paper itself stays in the library) or
 * the paper (which moves to the trash).
 */
async function deletePaper(paperId) {
  // The folders the paper is in right now - the list on screen can be
  // older than the server.
  let title = paperTitle(paperId);
  let folders = findPaper(paperId)?.folders;
  try {
    const paper = await api(`/api/papers/${paperId}`);
    title = paper.title || title;
    folders = paper.folders || [];
  } catch {
    // The server does not know it (anymore); the list on screen still does.
    folders = folders || [];
  }

  const paths = state.folderPaths;
  const folderRows = folders
    .map((folder) => {
      const path = paths.get(folder.id) || folder.name;
      return `<label class="delete-option">
        <input type="checkbox" value="${folder.id}" data-folder="${folder.id}" />
        <span>${escapeHtml(path)}</span>
      </label>`;
    })
    .join("");

  openModal(
    `<header>删除文献<button class="icon-btn" data-close>${ICONS.close}</button></header>
     <div class="body">
       <p class="confirm-text">《${escapeHtml(title)}》</p>
       ${
         folders.length
           ? `<div class="delete-section">
                <div class="delete-section-title">从哪些分类里移除它？文献本身保留在库里。</div>
                <label class="delete-option">
                  <input type="checkbox" id="remove-all-folders" />
                  <span>从所有分类删除</span>
                </label>
                ${folderRows}
              </div>
              <div class="separator"></div>`
           : `<p class="loss-note">这篇文献没有分类，只能删除它本身。</p>`
       }
       <div class="delete-section">
         <div class="danger-note">删除文献本身（移入垃圾箱）将失去：</div>
         <ul class="loss-list">
           <li>文献本身</li>
           <li>它的备注、笔记与高亮标注</li>
         </ul>
         <p class="loss-note">PDF 文件仍然保留在磁盘上；之后可以在侧栏的垃圾箱里把它恢复回来（分类归属不会跟着恢复）。</p>
       </div>
     </div>
     <footer>
       <button class="btn" data-close>取消</button>
       ${
         folders.length
           ? `<button class="btn" id="remove-paper-folders" disabled>从分类移除</button>`
           : ""
       }
       <button class="btn danger" id="delete-paper-ok">移入垃圾箱</button>
     </footer>`,
    (root) => {
      const removeBtn = root.querySelector("#remove-paper-folders");
      const allBox = root.querySelector("#remove-all-folders");
      const folderBoxes = [...root.querySelectorAll("input[data-folder]")];

      // The button is only there when there is something to remove.
      const syncRemoveButton = () => {
        const picked = allBox?.checked || folderBoxes.some((box) => box.checked);
        if (removeBtn) removeBtn.disabled = !picked;
      };
      // "From all folders" covers the single folders, so they grey out.
      const syncFolderBoxes = () => {
        const all = allBox?.checked;
        folderBoxes.forEach((box) => {
          box.disabled = Boolean(all);
          if (all) box.checked = false;
        });
        syncRemoveButton();
      };
      allBox?.addEventListener("change", syncFolderBoxes);
      folderBoxes.forEach((box) => box.addEventListener("change", syncRemoveButton));
      syncRemoveButton();

      removeBtn?.addEventListener("click", async () => {
        removeBtn.disabled = true;
        const all = Boolean(allBox?.checked);
        const ids = folderBoxes.filter((box) => box.checked).map((box) => Number(box.value));
        try {
          await apiJson(`/api/papers/${paperId}`, "PATCH", {
            ...(all ? { clearFolders: true } : { removeFolderIds: ids }),
          });
          closeModal();
          invalidateFolderPapers();
          await refresh();
          toast(all ? "已移出所有分类" : "已从分类中移除");
        } catch (error) {
          removeBtn.disabled = false;
          toast(`移除失败：${error.message}`);
        }
      });

      const confirmBtn = root.querySelector("#delete-paper-ok");
      confirmBtn.addEventListener("click", async () => {
        confirmBtn.disabled = true;
        try {
          await api(`/api/papers/${paperId}`, { method: "DELETE" });
          closeModal();
          invalidateFolderPapers();
          await refresh();
          toast("已移入垃圾箱");
        } catch (error) {
          confirmBtn.disabled = false;
          toast(`删除失败：${error.message}`);
        }
      });
    }
  );
}

/**
 * Change the title of a paper. The title is what the user sees everywhere,
 * so it is the paper's name.
 */
function renamePaper(paper) {
  openModal(
    `<header>修改标题<button class="icon-btn" data-close>${ICONS.close}</button></header>
     <div class="body">
       <div class="field">
         <label>标题</label>
         <input type="text" id="paper-title-input" value="${escapeHtml(paper.title)}" />
       </div>
     </div>
     <footer>
       <button class="btn" data-close>取消</button>
       <button class="btn primary" id="paper-title-ok">保存</button>
     </footer>`,
    (root) => {
      const input = root.querySelector("#paper-title-input");
      input.focus();
      input.select();
      const submit = async () => {
        const title = input.value.trim();
        if (!title) {
          toast("标题不能为空");
          return;
        }
        if (title === paper.title) {
          closeModal();
          return;
        }
        try {
          await apiJson(`/api/papers/${paper.id}`, "PATCH", { title });
          paper.title = title;
          closeModal();
          refreshPaperRow(paper);
          toast("标题已更新");
        } catch (error) {
          toast(`保存失败：${error.message}`);
        }
      };
      root.querySelector("#paper-title-ok").addEventListener("click", submit);
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") submit();
      });
    }
  );
}

/**
 * The categories of one paper. The picker starts with the categories the
 * paper is already in, so ticking one adds it and unticking removes it.
 */
function editPaperFolders(paper) {
  openFolderPicker(
    state.folders,
    "添加分类",
    paper.folders.map((folder) => folder.id),
    async (ids) => {
      try {
        await apiJson(`/api/papers/${paper.id}`, "PATCH", { folderIds: ids });
        // The list does not show the categories, but the picker opens with
        // them ticked - so the state has to be up to date.
        const fresh = await api(`/api/papers/${paper.id}`);
        paper.folders = fresh.folders;
        invalidateFolderPapers();
        toast("分类已更新");
      } catch (error) {
        toast(`保存失败：${error.message}`);
      }
    }
  );
}

/**
 * The tags of one paper. The known tags are searched as the user types and
 * the best matches are offered (at most 20 of them), the ones the paper
 * carries are marked; a name that is not in the list yet is a new tag.
 */
function editPaperTags(paper) {
  const known = state.tags.map((tag) => tag.name);
  const chosen = new Set(paper.tags.map((tag) => tag.name));
  // Every tag that can be picked: the ones that exist plus the ones this
  // paper already carries.
  const all = new Set([...known, ...chosen]);

  const optionHtml = (name) =>
    `<button class="tag-option ${chosen.has(name) ? "on" : ""}" data-tag-name="${escapeHtml(
      name
    )}">${chosen.has(name) ? ICONS.check : ""}<span>${escapeHtml(name)}</span></button>`;

  openModal(
    `<header>修改标签<button class="icon-btn" data-close>${ICONS.close}</button></header>
     <div class="body">
       <div class="field">
         <label>标签</label>
         <input type="text" id="paper-tag-new"
                placeholder="输入标签名称后回车添加，已有的标签会模糊匹配" />
       </div>
       <div class="field">
         <label>已有标签（模糊匹配，最多 20 个）</label>
         <div class="tag-options" id="paper-tag-options"></div>
       </div>
     </div>
     <footer>
       <button class="btn" data-close>取消</button>
       <button class="btn primary" id="paper-tag-ok">保存</button>
     </footer>`,
    (root) => {
      const list = root.querySelector("#paper-tag-options");
      const input = root.querySelector("#paper-tag-new");

      const repaint = () => {
        // The tags the paper carries are always listed, so they can be
        // taken off again.
        const matches = fuzzyMatch(input.value, [...all], 20);
        const names = [...new Set([...chosen, ...matches])];
        list.innerHTML = names.map(optionHtml).join("");
      };
      repaint();
      input.addEventListener("input", repaint);

      list.addEventListener("click", (event) => {
        const option = event.target.closest("[data-tag-name]");
        if (!option) return;
        const name = option.dataset.tagName;
        if (chosen.has(name)) chosen.delete(name);
        else chosen.add(name);
        repaint();
      });

      const addNew = () => {
        const name = input.value.trim();
        if (!name) return;
        all.add(name);
        chosen.add(name);
        input.value = "";
        repaint();
      };
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          addNew();
        }
      });

      const submit = async () => {
        try {
          // The tags that were just added come first: the row only has room
          // for a few of them, and the new one is what the user is looking
          // for.
          const before = new Set(paper.tags.map((tag) => tag.name));
          const names = [...chosen].sort(
            (a, b) => (before.has(a) ? 1 : 0) - (before.has(b) ? 1 : 0)
          );
          await apiJson(`/api/papers/${paper.id}`, "PATCH", { tags: names });
          paper.tags = names.map((name) => {
            const existing = paper.tags.find((tag) => tag.name === name);
            return existing || { name };
          });
          closeModal();
          refreshPaperRow(paper);
          await refreshTags();
          toast("标签已更新");
        } catch (error) {
          toast(`保存失败：${error.message}`);
        }
      };
      root.querySelector("#paper-tag-ok").addEventListener("click", submit);
    }
  );
}

/**
 * Edit the remark of a paper right in the row. Enter saves, Escape throws
 * the change away.
 */
function editPaperRemark(cell, paper) {
  if (cell.querySelector("input")) return;
  const original = paper.remark || "";
  cell.innerHTML = `<input class="remark-input" type="text" value="${escapeHtml(original)}" />`;
  const input = cell.querySelector("input");
  input.focus();
  input.select();

  const show = (value) => {
    cell.innerHTML = `<span class="remark-text">${
      value ? escapeHtml(value) : `<span class="placeholder">添加备注</span>`
    }</span>`;
  };

  let done = false;
  const save = async () => {
    if (done) return;
    done = true;
    const value = input.value.trim();
    if (value === original) {
      show(original);
      return;
    }
    try {
      await apiJson(`/api/papers/${paper.id}`, "PATCH", { remark: value });
      paper.remark = value;
      show(value);
      toast("备注已保存");
    } catch (error) {
      show(original);
      toast(`保存失败：${error.message}`);
    }
  };
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      save();
    } else if (event.key === "Escape") {
      done = true;
      show(original);
    }
  });
  input.addEventListener("blur", save);
}

// The menu of a paper in the list: renaming and opening the reading page.
function openPaperTitleMenu(paper, x, y) {
  openContextMenu(x, y, [
    { label: "修改标题", icon: ICONS.pencil, run: () => renamePaper(paper) },
    { label: "添加分类", icon: ICONS.folder, run: () => editPaperFolders(paper) },
    {
      label: "打开阅读页",
      icon: ICONS.external,
      run: () => window.open(`/paper/${paper.id}`, "_blank", "noopener"),
    },
    { sep: true },
    {
      label: "删除文献",
      icon: ICONS.trash,
      danger: true,
      run: () => deletePaper(paper.id),
    },
  ]);
}

function renderSidebar() {
  const sidebar = $("#sidebar");
  const total = state.stats.total || 0;
  const folderRows = [];

  // Returns the markup of one folder node: the row itself, its sub-folders
  // and the papers filed in it.
  const renderFolder = (node, depth) => {
    const expanded = state.expanded.has(node.id);
    const active = String(state.folder) === String(node.id);
    const papers = state.folderPapers.get(node.id);
    const loading = state.loadingFolders.has(node.id);

    const item = `
      <div class="folder-item ${active ? "active" : ""} ${expanded ? "" : "collapsed"}"
          data-folder="${node.id}" data-depth="${depth}"
          draggable="true" data-drag-kind="folder" data-drag-id="${node.id}">
        <span class="chevron-toggle" data-toggle-folder="${node.id}"
              title="${expanded ? "收起" : "展开"}">${ICONS.chevron}</span>
        ${ICONS.folder}
        <span class="name">${escapeHtml(node.name)}</span>
        <span class="count">${node.count}</span>
        <span class="actions">
          <button class="icon-btn" data-folder-menu="${node.id}" title="更多操作">${ICONS.more}</button>
        </span>
      </div>`;

    if (!expanded) return `<li class="folder-node">${item}</li>`;

    let children = "";
    if (node.children?.length) {
      children = `<ul class="folder-children">${node.children
        .map((child) => renderFolder(child, depth + 1))
        .join("")}</ul>`;
    }

    let paperList = "";
    if (loading) {
      paperList = `<li class="folder-papers-note">加载中…</li>`;
    } else if (papers?.items?.length) {
      paperList = `<ul class="folder-papers">${papers.items
        .map(
          (paper) => `<li class="tree-paper" data-paper="${paper.id}"
                      draggable="true" data-drag-kind="paper" data-drag-id="${paper.id}"
                      title="${escapeHtml(paper.title)}">
            ${paper.hasFile ? ICONS.file : ICONS.link}
            <span class="name">${escapeHtml(paper.title)}</span>
            <button class="icon-btn paper-delete" data-delete-paper="${paper.id}"
                    title="删除文献">${ICONS.trash}</button>
          </li>`
        )
        .join("")}</ul>`;
      if (papers.total > papers.items.length) {
        paperList += `<li class="folder-papers-note">还有 ${
          papers.total - papers.items.length
        } 篇未显示</li>`;
      }
    } else if (papers) {
      paperList = `<li class="folder-papers-note">此分类下暂无文献</li>`;
    }

    return `<li class="folder-node">${item}${children}${paperList}</li>`;
  };

  state.folders.forEach((node) => folderRows.push(renderFolder(node, 0)));

  const tagSection = state.showTags
    ? `<div class="separator">标签</div>
       <ul class="unfiled-list">
         ${state.tags
           .map(
             (tag) => `<li class="unfiled-item" data-tag="${escapeHtml(tag.name)}">
               ${ICONS.file}<span class="name">${escapeHtml(tag.name)}</span>
               <span class="count">${tag.count}</span>
             </li>`
           )
           .join("")}
       </ul>`
    : "";

  sidebar.innerHTML = `
    <div class="sidebar-header">
      <div class="left">${ICONS.library}<span>全部文献</span><span class="count">${total}</span></div>
      <button class="icon-btn" data-action="toggle-tags" title="标签筛选">${ICONS.filter}</button>
    </div>
    <div class="sidebar-scroll">
      <ul class="folder-list">
        <li class="folder-item ${state.folder === "all" ? "active" : ""}" data-folder="all">
          ${ICONS.library}<span class="name">全部文献</span><span class="count">${total}</span>
          <span class="actions">
            <button class="icon-btn" data-new-folder title="新建分类">${ICONS.plus}</button>
          </span>
        </li>
        ${folderRows.join("")}
      </ul>
      ${tagSection}
      <div class="separator">以下文献尚未分类</div>
      <ul class="unfiled-list" id="unfiled-papers">
        ${
          state.unfiled.length
            ? state.unfiled
                .map(
                  (paper) => `<li class="unfiled-item" data-paper="${paper.id}"
                              draggable="true" data-drag-kind="paper" data-drag-id="${paper.id}">
                    ${paper.hasFile ? ICONS.file : ICONS.link}
                    <span class="name">${escapeHtml(paper.title)}</span>
                    <button class="icon-btn paper-delete" data-delete-paper="${paper.id}"
                            title="删除文献">${ICONS.trash}</button>
                  </li>`
                )
                .join("") +
                  (state.unfiledTotal > state.unfiled.length
                    ? `<li class="folder-papers-note">还有 ${
                        state.unfiledTotal - state.unfiled.length
                      } 篇未显示</li>`
                    : "")
              : `<li class="unfiled-item" style="cursor:default"><span class="name">—</span></li>`
          }
        </ul>
      <div class="trash-link ${state.view === "trash" ? "active" : ""}" id="trash-bin"
           data-trash-open title="删除的文献会先放进垃圾箱，文件仍然保留">
        ${ICONS.trash}<span class="name">垃圾箱</span>
        <span class="count">${state.stats.trash || 0}</span>
      </div>
    </div>`;
}

/**
 * The options of the read filter: how many of the papers in the current view
 * are read and unread. The numbers follow the current folder, tag and search
 * instead of the whole library.
 */
function readFilterOptions() {
  const { read, unread } = state.readCounts;
  return [
    ["all", `全部 (${read + unread})`],
    ["read", `已读 (${read})`],
    ["unread", `未读 (${unread})`],
  ]
    .map(
      ([value, label]) =>
        `<option value="${value}" ${state.read === value ? "selected" : ""}>${label}</option>`
    )
    .join("");
}

function paperRow(paper) {
  const meta = [paper.authors, paper.year].filter(Boolean).join(" · ");
  // The tag column shows tags only - folders live in the tree and on the
  // reading page, mixing them in here made the column unreadable.
  const allTags = [...new Set(paper.tags.map((t) => t.name))];
  return `
    <div class="paper-row" data-paper="${paper.id}">
      <div class="paper-title-cell">
        <div class="title">${escapeHtml(paper.title)}</div>
        ${meta ? `<div class="meta">${escapeHtml(meta)}</div>` : ""}
        <button class="title-menu-btn" data-role="title-menu" title="更多操作">${ICONS.more}</button>
      </div>
      <div class="tag-cell">
        <div class="tag-pills">
          ${allTags.map((name) => `<span class="pill">${escapeHtml(name)}</span>`).join("")}
          <button class="tag-add" data-role="tag-add" title="添加标签">${ICONS.plus}</button>
        </div>
      </div>
      <div class="remark-cell" data-role="remark" title="点击修改备注"><span class="remark-text">${
        paper.remark
          ? escapeHtml(paper.remark)
          : `<span class="placeholder">添加备注</span>`
      }</span></div>
      <div data-role="stars-cell">${starsHtml(paper.importance)}</div>
      <div class="read-cell">
        <button class="read-toggle ${paper.isRead ? "on" : ""}" data-role="read-toggle"
                title="点击切换已读状态">${paper.isRead ? "已读" : "未读"}</button>
      </div>
    </div>`;
}

// Put one row back into the list after it was edited. The whole list is not
// rendered again - that would throw away the scroll position of the page.
function refreshPaperRow(paper) {
  const row = document.querySelector(`.paper-row[data-paper="${paper.id}"]`);
  if (!row) return;
  const holder = document.createElement("div");
  holder.innerHTML = paperRow(paper);
  row.replaceWith(holder.firstElementChild);
}

function sortArrow(field) {
  if (state.sort !== field || state.order === "none") return "";
  return state.order === "asc" ? " ↑" : " ↓";
}

function pageNumbers(current, total) {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  const pages = new Set([1, total, current, current - 1, current + 1]);
  if (current <= 3) [2, 3, 4].forEach((p) => pages.add(p));
  if (current >= total - 2) [total - 1, total - 2, total - 3].forEach((p) => pages.add(p));
  const sorted = [...pages].filter((p) => p >= 1 && p <= total).sort((a, b) => a - b);
  const out = [];
  sorted.forEach((page, index) => {
    if (index && page - sorted[index - 1] > 1) out.push("…");
    out.push(page);
  });
  return out;
}

function renderPagination() {
  const maxPage = Math.max(1, Math.ceil(state.total / state.pageSize));
  const page = state.page;
  const from = state.total === 0 ? 0 : (page - 1) * state.pageSize + 1;
  const to = Math.min(state.total, page * state.pageSize);

  return `
    <div class="pagination">
      <div class="page-size">
        每页
        <select class="btn small" id="page-size">
          ${[20, 40, 100]
            .map(
              (size) =>
                `<option value="${size}" ${
                  state.pageSize === size ? "selected" : ""
                }>${size}</option>`
            )
            .join("")}
        </select>
        条
      </div>
      <div class="page-info">
        ${state.total ? `显示第 ${from}-${to} 条，共 ${state.total} 条` : "共 0 条"}
      </div>
      <div class="pager">
        <button class="btn small" data-action="page-first" ${page <= 1 ? "disabled" : ""}>«</button>
        <button class="btn small" data-action="page-prev" ${page <= 1 ? "disabled" : ""}>‹</button>
        ${pageNumbers(page, maxPage)
          .map((item) =>
            item === "…"
              ? `<span class="page-gap">…</span>`
              : `<button class="btn small ${
                  item === page ? "primary" : ""
                }" data-page="${item}">${item}</button>`
          )
          .join("")}
        <button class="btn small" data-action="page-next" ${
          page >= maxPage ? "disabled" : ""
        }>›</button>
        <button class="btn small" data-action="page-last" ${
          page >= maxPage ? "disabled" : ""
        }>»</button>
      </div>
    </div>`;
}

function renderLibrary() {
  const sortOptions = [
    ["lastRead", "最近阅读"],
    ["created", "添加时间"],
    ["updated", "更新时间"],
    ["title", "标题"],
    ["importance", "重要性"],
    ["isRead", "已读"],
  ];
  const orderOptions = [
    ["asc", "升序"],
    ["desc", "降序"],
    ["none", "无序"],
  ];

  const list = state.papers.length
    ? state.papers.map(paperRow).join("")
    : `<div class="empty">没有匹配的文献</div>`;

  $("#main").innerHTML = `
    <div class="topbar">
      <div class="search-box">${ICONS.search}
        <input id="search" type="text" placeholder="搜索标题、笔记、备注...（回车搜索）" value="${escapeHtml(
          state.searchText
        )}" />
      </div>
      <div class="spacer"></div>
      <select class="btn" id="read-filter">
        ${readFilterOptions()}
      </select>
      <select class="btn" id="sort">
        ${sortOptions
          .map(
            ([value, label]) =>
              `<option value="${value}" ${state.sort === value ? "selected" : ""}>${label}</option>`
          )
          .join("")}
      </select>
      <select class="btn" id="sort-order">
        ${orderOptions
          .map(
            ([value, label]) =>
              `<option value="${value}" ${state.order === value ? "selected" : ""}>${label}</option>`
          )
          .join("")}
      </select>
      <button class="btn primary" data-action="add">${ICONS.plus} 添加</button>
    </div>
    <div class="content" id="content">
      <div class="list-header">
        <div class="col" data-col="title" data-action="sort-title">标题${sortArrow("title")}<span class="col-resize" data-resize="title" title="拖动调整宽度"></span></div>
        <div class="col" data-col="tag">标签<span class="col-resize" data-resize="tag" title="拖动调整宽度"></span></div>
        <div class="col hide-sm" data-col="remark">备注<span class="col-resize" data-resize="remark" title="拖动调整宽度"></span></div>
        <div class="col" data-col="stars" data-action="sort-importance">重要性${sortArrow("importance")}<span class="col-resize" data-resize="stars" title="拖动调整宽度"></span></div>
        <div class="col" data-col="read" data-action="sort-isRead">已读${sortArrow("isRead")}<span class="col-resize" data-resize="read" title="拖动调整宽度"></span></div>
      </div>
      ${list}
      ${renderPagination()}
    </div>`;

  applyColumnWidths();
}

function render() {
  // The topbar lives inside #main, so every render replaces the search input.
  // Remember whether it was focused (and where the caret was) and restore it,
  // otherwise typing in the search box breaks after the first keystroke.
  const active = document.activeElement;
  const keepSearchFocus = active && active.id === "search";
  const caret = keepSearchFocus ? active.selectionStart : null;

  if (state.view === "trash") renderTrash();
  else renderLibrary();
  renderSidebar();

  if (keepSearchFocus) {
    const input = $("#search");
    if (input) {
      input.focus();
      if (caret !== null) {
        try {
          input.setSelectionRange(caret, caret);
        } catch {
          /* not a text input - ignore */
        }
      }
    }
  }
}

/* -------------------------------- modal -------------------------------- */

/* -------------------------------- trash -------------------------------- */

function renderTrash() {
  const items = state.trash
    .map(
      (item) => `
      <div class="trash-item" data-trash="${item.id}">
        <div class="trash-info">
          <div class="title">${escapeHtml(item.title)}</div>
          <div class="meta">${escapeHtml(
            [item.authors, item.year].filter(Boolean).join(" · ")
          )}</div>
          <div class="meta">${escapeHtml(item.deletedAt)} 删除 · ${formatSize(item.sizeBytes)}${
            item.annotationCount ? ` · ${item.annotationCount} 条标注` : ""
          }</div>
        </div>
        <div class="trash-actions">
          <button class="btn small" data-trash-action="restore" data-trash="${item.id}">恢复</button>
          <button class="btn small danger" data-trash-action="purge" data-trash="${item.id}">彻底删除</button>
        </div>
      </div>`
    )
    .join("");

  $("#main").innerHTML = `
    <div class="topbar">
      <div class="topbar-title">${ICONS.trash} 垃圾箱</div>
      <div class="spacer"></div>
      <button class="btn danger" data-trash-action="empty" ${state.trash.length ? "" : "disabled"}>
        清空垃圾箱
      </button>
    </div>
    <div class="content" id="content">
      <div class="trash-head">
        共 ${state.trash.length} 项 · 占用 ${formatSize(state.trashSize)}
        <span class="trash-hint">恢复后的文献会回到「以下文献尚未分类」</span>
      </div>
      ${items || `<div class="empty">垃圾箱是空的</div>`}
    </div>`;
}

/** Ask before something irreversible happens in the trash. */
function confirmTrashAction(title, lines, okLabel, run) {
  openModal(
    `<header>${escapeHtml(title)}<button class="icon-btn" data-close>${ICONS.close}</button></header>
     <div class="body">
       <div class="danger-note">删除后无法恢复，将失去：</div>
       <ul class="loss-list">
         ${lines.map((line) => `<li>${escapeHtml(line)}</li>`).join("")}
       </ul>
     </div>
     <footer>
       <button class="btn" data-close>取消</button>
       <button class="btn danger" id="trash-confirm-ok">${escapeHtml(okLabel)}</button>
     </footer>`,
    (root) => {
      const confirmBtn = root.querySelector("#trash-confirm-ok");
      confirmBtn.addEventListener("click", async () => {
        confirmBtn.disabled = true;
        try {
          await run();
          closeModal();
        } catch (error) {
          confirmBtn.disabled = false;
          toast(`操作失败：${error.message}`);
        }
      });
    }
  );
}

async function trashRestore(trashId) {
  try {
    await api(`/api/trash/${trashId}/restore`, { method: "POST" });
  } catch (error) {
    // Restoring may be refused when the same file was uploaded again, so
    // the paper already exists in the library (the server says which one).
    toast(`恢复失败：${error.message}`);
    return;
  }
  invalidateFolderPapers();
  await loadTrash();
  await refresh();
  toast("已恢复文献，回到未分类");
}

async function trashPurge(trashId) {
  const item = state.trash.find((entry) => entry.id === trashId);
  confirmTrashAction(
    "彻底删除",
    [
      `文献「${item?.title || ""}」`,
      item?.hasFile ? "它的 PDF 文件" : "",
    ].filter(Boolean),
    "彻底删除",
    async () => {
      await api(`/api/trash/${trashId}`, { method: "DELETE" });
      await loadTrash();
      await refresh();
      toast("已彻底删除");
    }
  );
}

async function trashEmpty() {
  const count = state.trash.length;
  confirmTrashAction(
    "清空垃圾箱",
    [`垃圾箱里的 ${count} 项`, "它们的 PDF 文件", "全部元数据（备注、笔记、高亮标注）"],
    "清空",
    async () => {
      await api("/api/trash/empty", { method: "POST" });
      await loadTrash();
      await refresh();
      toast("垃圾箱已清空");
    }
  );
}

/**
 * Tell the user that the file they added is already in the library.
 *
 * The paper that is already there is named, with the folders it sits in, so
 * that it is clear which one was hit. The upload itself is dropped: the
 * backend did not keep the file and did not create a second paper.
 */
function showDuplicateDialog(paper) {
  const paths = folderPaths(state.folders);
  const folders = (paper.folders || []).map((folder) => paths.get(folder.id) || folder.name);
  const meta = [paper.authors, paper.year].filter(Boolean).join(" · ");
  openModal(
    `<header>这篇已经在库里了<button class="icon-btn" data-close>${ICONS.close}</button></header>
     <div class="body">
       <p class="confirm-text">《${escapeHtml(paper.title)}》已经在库里了，没有再添加一份。</p>
       <ul class="loss-list">
         <li>分类：${escapeHtml(folders.length ? folders.join("、") : "未分类")}</li>
         ${meta ? `<li>${escapeHtml(meta)}</li>` : ""}
       </ul>
     </div>
     <footer>
       <button class="btn primary" data-close>知道了</button>
     </footer>`,
    (root) => root.querySelector(".btn.primary").focus()
  );
}

function openAddModal() {
  const flat = flattenFolders(state.folders);
  // A name can repeat under different parents, so those entries say which
  // parent they hang under.
  const nameCounts = new Map();
  for (const folder of flat) {
    nameCounts.set(folder.name, (nameCounts.get(folder.name) || 0) + 1);
  }
  const folderOptions = flat
    .map((folder) => {
      const ambiguous = (nameCounts.get(folder.name) || 0) > 1;
      const parent = folder.parentPath.split(" / ").pop();
      const hint = ambiguous && parent ? `（${escapeHtml(parent)}）` : "";
      return `<option value="${folder.id}">${"&nbsp;".repeat(folder.depth * 3)}${
        escapeHtml(folder.name)
      }${hint}</option>`;
    })
    .join("");

  openModal(
    `<header>添加文献<button class="icon-btn" data-close>${ICONS.close}</button></header>
     <div class="body">
       <div class="drop-zone" id="drop-zone">
         点击选择或拖拽 PDF 到此处
         <input type="file" id="file-input" accept="application/pdf" hidden />
       </div>
       <div id="file-chip"></div>
       <div class="spacer-lg"></div>
       <div class="field">
         <label>标题</label>
         <input type="text" id="add-title" placeholder="留空则使用文件名" />
       </div>
       <div class="field">
         <label>分类</label>
         <select id="add-folder">
           <option value="">未分类</option>
           ${folderOptions}
         </select>
       </div>
       <div class="field">
         <label>标签（逗号分隔）</label>
         <input type="text" id="add-tags" placeholder="Transformer, NLP" />
       </div>
     </div>
     <footer>
       <button class="btn" data-close>取消</button>
       <button class="btn primary" id="add-submit">添加</button>
     </footer>`,
    (root) => {
      const zone = root.querySelector("#drop-zone");
      const input = root.querySelector("#file-input");
      const chip = root.querySelector("#file-chip");
      let file = null;

      zone.addEventListener("click", () => input.click());
      zone.addEventListener("dragover", (event) => {
        event.preventDefault();
        zone.classList.add("drag");
      });
      zone.addEventListener("dragleave", () => zone.classList.remove("drag"));
      zone.addEventListener("drop", (event) => {
        event.preventDefault();
        zone.classList.remove("drag");
        if (event.dataTransfer.files.length) setFile(event.dataTransfer.files[0]);
      });
      input.addEventListener("change", () => {
        if (input.files.length) setFile(input.files[0]);
      });

      function setFile(value) {
        file = value;
        chip.innerHTML = `<div class="file-chip">${ICONS.file} ${escapeHtml(
          file.name
        )} (${(file.size / 1024 / 1024).toFixed(2)} MB)</div>`;
        const titleInput = root.querySelector("#add-title");
        if (!titleInput.value) titleInput.value = file.name.replace(/\.pdf$/i, "");
      }

      root.querySelector("#add-submit").addEventListener("click", async () => {
        const title = root.querySelector("#add-title").value.trim();
        const folder = root.querySelector("#add-folder").value;
        const tags = root
          .querySelector("#add-tags")
          .value.split(",")
          .map((t) => t.trim())
          .filter(Boolean);
        if (!file) {
          toast("请先选择一个 PDF");
          return;
        }
        const body = new FormData();
        body.append("file", file);
        body.append("title", title);
        body.append("tags", JSON.stringify(tags));
        body.append("folderIds", JSON.stringify(folder ? [Number(folder)] : []));
        try {
          await api("/api/papers", { method: "POST", body });
          closeModal();
          toast("已添加");
          await refresh();
        } catch (error) {
          if (error.data?.code === "duplicate") {
            showDuplicateDialog(error.data.paper);
            return;
          }
          toast(`添加失败：${error.message}`);
        }
      });
    }
  );
}

/* ------------------------------- actions ------------------------------ */

/* -------------------------------- events ------------------------------ */

document.addEventListener("click", async (event) => {
  // The chevron toggles the tree node. It sits inside the <li data-folder>,
  // so it has to be handled before the folder filter below.
  const toggleEl = event.target.closest("[data-toggle-folder]");
  if (toggleEl) {
    event.stopPropagation();
    const id = Number(toggleEl.dataset.toggleFolder);
    if (state.expanded.has(id)) {
      state.expanded.delete(id);
    } else {
      state.expanded.add(id);
      loadFolderPapers(id);
    }
    renderSidebar();
    return;
  }

  const pageButton = event.target.closest("[data-page]");
  if (pageButton) {
    event.stopPropagation();
    state.page = Number(pageButton.dataset.page) || 1;
    await refresh();
    scrollListTop();
    return;
  }

  // The resize handle sits inside a sortable column: clicking it must not
  // sort the list.
  if (event.target.closest("[data-resize]")) return;

  const actionEl = event.target.closest("[data-action]");
  const action = actionEl?.dataset.action;

  if (action) {
    event.stopPropagation();
    switch (action) {
      case "toggle-tags":
        state.showTags = !state.showTags;
        render();
        return;
      case "add":
        openAddModal();
        return;
      case "sort-isRead": {
        const same = state.sort === "isRead";
        state.sort = "isRead";
        state.order = same && state.order === "desc" ? "asc" : "desc";
        state.page = 1;
        await refresh();
        return;
      }
      case "sort-title": {
        const same = state.sort === "title";
        state.sort = "title";
        state.order = same && state.order === "asc" ? "desc" : "asc";
        state.page = 1;
        await refresh();
        return;
      }
      case "sort-importance": {
        const same = state.sort === "importance";
        state.sort = "importance";
        state.order = same && state.order === "desc" ? "asc" : "desc";
        state.page = 1;
        await refresh();
        return;
      }
      case "page-first":
        state.page = 1;
        await refresh();
        scrollListTop();
        return;
      case "page-prev":
        state.page = Math.max(1, state.page - 1);
        await refresh();
        scrollListTop();
        return;
      case "page-next":
        state.page += 1;
        await refresh();
        scrollListTop();
        return;
      case "page-last":
        state.page = Math.max(1, Math.ceil(state.total / state.pageSize));
        await refresh();
        scrollListTop();
        return;
      default:
        return;
    }
  }

  const starsCell = event.target.closest("[data-role='stars-cell']");
  if (starsCell) {
    event.stopPropagation();
    const row = starsCell.closest(".paper-row");
    const paper = state.papers.find((p) => p.id === Number(row.dataset.paper));
    const stars = starsCell.querySelector(".stars");
    const index = [...stars.children].indexOf(event.target.closest(".stars > *"));
    if (paper && index >= 0) {
      const previous = paper.importance;
      const next = index + 1 === previous ? 0 : index + 1;
      paper.importance = next;
      starsCell.innerHTML = starsHtml(next);
      try {
        await apiJson(`/api/papers/${paper.id}`, "PATCH", { importance: next });
      } catch (error) {
        // The server refused it: put the old value back, the row must not
        // show a state the database does not have.
        paper.importance = previous;
        starsCell.innerHTML = starsHtml(previous);
        toast(`保存失败：${error.message}`);
      }
    }
    return;
  }

  const readToggle = event.target.closest("[data-role='read-toggle']");
  if (readToggle) {
    event.stopPropagation();
    const row = readToggle.closest(".paper-row");
    const paper = state.papers.find((p) => p.id === Number(row.dataset.paper));
    if (!paper) return;
    const previous = paper.isRead;
    const next = !previous;
    // The button is small and sits at the end of a row, so a stray click
    // marks a paper as read. Ask first.
    const ok = await confirmDialog(
      next
        ? `确定把《${paper.title}》标记为已读？`
        : `确定把《${paper.title}》标记为未读？`,
      { title: "更改已读状态", confirmText: next ? "标记已读" : "标记未读" }
    );
    if (!ok) return;
    paper.isRead = next;
    readToggle.classList.toggle("on", next);
    readToggle.textContent = next ? "已读" : "未读";
    try {
      await apiJson(`/api/papers/${paper.id}`, "PATCH", { isRead: next });
    } catch (error) {
      paper.isRead = previous;
      readToggle.classList.toggle("on", previous);
      readToggle.textContent = previous ? "已读" : "未读";
      toast(`保存失败：${error.message}`);
      return;
    }

    // The paper left the current view when the filter is "read" or "unread"
    // and the new state does not match it any more - reload so the list and
    // its counts are right.
    if ((state.read === "read" && !next) || (state.read === "unread" && next)) {
      await refresh();
      return;
    }
    // Otherwise the row stays where it is: move the paper from one count to
    // the other instead of re-rendering the list.
    if (next) {
      state.readCounts.read += 1;
      state.readCounts.unread -= 1;
    } else {
      state.readCounts.unread += 1;
      state.readCounts.read -= 1;
    }
    const label = $("#read-filter");
    if (label) label.innerHTML = readFilterOptions();
    return;
  }

  const folderMenuEl = event.target.closest("[data-folder-menu]");
  if (folderMenuEl) {
    // The "more" button sits inside the folder row, so it has to be
    // handled before the row itself.
    event.stopPropagation();
    const rect = folderMenuEl.getBoundingClientRect();
    openFolderMenu(Number(folderMenuEl.dataset.folderMenu), rect.left, rect.bottom + 4);
    return;
  }

  const newFolderEl = event.target.closest("[data-new-folder]");
  if (newFolderEl) {
    // The "new folder" button sits inside the 全部文献 row, so it has to be
    // handled before the row itself.
    event.stopPropagation();
    createFolder(null);
    return;
  }

  const deletePaperEl = event.target.closest("[data-delete-paper]");
  if (deletePaperEl) {
    // The trash button sits inside the paper row, which opens the paper.
    event.stopPropagation();
    deletePaper(Number(deletePaperEl.dataset.deletePaper));
    return;
  }

  const trashOpenEl = event.target.closest("[data-trash-open]");
  if (trashOpenEl) {
    event.stopPropagation();
    state.view = "trash";
    state.folder = "all";
    state.tag = "";
    await loadTrash();
    render();
    return;
  }

  const trashActionEl = event.target.closest("[data-trash-action]");
  if (trashActionEl) {
    event.stopPropagation();
    const action = trashActionEl.dataset.trashAction;
    const trashId = Number(trashActionEl.dataset.trash);
    if (action === "restore") await trashRestore(trashId);
    else if (action === "purge") await trashPurge(trashId);
    else if (action === "empty") await trashEmpty();
    return;
  }

  const folderEl = event.target.closest("[data-folder]");
  if (folderEl) {
    event.stopPropagation();
    const id = folderEl.dataset.folder;
    state.view = "library";
    state.folder = id;
    state.page = 1;
    if (id !== "all") {
      const num = Number(id);
      if (!state.expanded.has(num)) {
        state.expanded.add(num);
        loadFolderPapers(num);
      }
    }
    await refresh();
    return;
  }

  const tagEl = event.target.closest("[data-tag]");
  if (tagEl) {
    event.stopPropagation();
    state.view = "library";
    state.tag = state.tag === tagEl.dataset.tag ? "" : tagEl.dataset.tag;
    state.page = 1;
    await refresh();
    return;
  }

  const tagAddEl = event.target.closest("[data-role='tag-add']");
  if (tagAddEl) {
    // The "+" sits inside the paper row, which opens the paper.
    event.stopPropagation();
    const row = tagAddEl.closest(".paper-row");
    const paper = state.papers.find((p) => p.id === Number(row.dataset.paper));
    if (paper) editPaperTags(paper);
    return;
  }

  const titleMenuEl = event.target.closest("[data-role='title-menu']");
  if (titleMenuEl) {
    event.stopPropagation();
    const row = titleMenuEl.closest(".paper-row");
    const paper = state.papers.find((p) => p.id === Number(row.dataset.paper));
    if (paper) {
      const rect = titleMenuEl.getBoundingClientRect();
      openPaperTitleMenu(paper, rect.left, rect.bottom + 4);
    }
    return;
  }

  const remarkEl = event.target.closest("[data-role='remark']");
  if (remarkEl) {
    // The remark is edited in place, so the row must not open the paper.
    event.stopPropagation();
    const row = remarkEl.closest(".paper-row");
    const paper = state.papers.find((p) => p.id === Number(row.dataset.paper));
    if (paper) editPaperRemark(remarkEl, paper);
    return;
  }

  const titleEl = event.target.closest(".paper-title-cell");
  if (titleEl) {
    // Only the title opens the paper. The other columns have their own
    // meaning - a click there should not take the reader away.
    const row = titleEl.closest(".paper-row");
    if (row) {
      window.open(`/paper/${row.dataset.paper}`, "_blank", "noopener");
    }
    return;
  }

  const sidePaperEl = event.target.closest(
    ".tree-paper[data-paper], .unfiled-item[data-paper]"
  );
  if (sidePaperEl) {
    // reading happens on its own page, opened in a new tab so the library
    // stays where it was
    window.open(`/paper/${sidePaperEl.dataset.paper}`, "_blank", "noopener");
  }
});

/* ----------------------------- drag & drop ------------------------------ */

// Folders are virtual: dragging a folder moves it in the tree, dragging a
// paper files it under the folder it is dropped on.

let dragPayload = null;

function folderSubtreeIds(node, out = []) {
  out.push(node.id);
  (node.children || []).forEach((child) => folderSubtreeIds(child, out));
  return out;
}

/** True when `folderId` is `ancestorId` itself or lives below it. */
function isSelfOrDescendant(folderId, ancestorId) {
  const node = findFolder(state.folders, ancestorId);
  if (!node) return false;
  return folderSubtreeIds(node).some((id) => Number(id) === Number(folderId));
}

/** Where a drop would land, or null when it is not a valid target. */
function dropTargetFor(event, payload) {
  const folderEl = event.target.closest(".folder-item[data-folder]");
  if (folderEl) {
    const id = folderEl.dataset.folder;
    if (id === "all") return { el: folderEl, type: "root" };
    // A folder cannot be dropped into itself.
    if (payload.kind === "folder" && isSelfOrDescendant(Number(id), payload.id)) return null;
    return { el: folderEl, type: "folder", id: Number(id) };
  }
  if (payload.kind === "paper") {
    const unfiled = event.target.closest("#unfiled-papers");
    if (unfiled) return { el: unfiled, type: "unfiled" };
  }
  return null;
}

function clearDragMarks() {
  document
    .querySelectorAll(".drag-over, .dragging")
    .forEach((el) => el.classList.remove("drag-over", "dragging"));
}

document.addEventListener("dragstart", (event) => {
  const el = event.target.closest("[data-drag-kind]");
  if (!el) return;
  if (event.target.closest("button")) {
    event.preventDefault();
    return;
  }
  dragPayload = { kind: el.dataset.dragKind, id: Number(el.dataset.dragId) };
  event.dataTransfer.effectAllowed = "move";
  event.dataTransfer.setData("text/plain", JSON.stringify(dragPayload));
  el.classList.add("dragging");
});

document.addEventListener("dragover", (event) => {
  if (!dragPayload) return;
  const target = dropTargetFor(event, dragPayload);
  if (!target) return;
  event.preventDefault();
  event.dataTransfer.dropEffect = "move";
  document.querySelectorAll(".drag-over").forEach((el) => el.classList.remove("drag-over"));
  target.el.classList.add("drag-over");
});

document.addEventListener("dragleave", (event) => {
  const el = event.target.closest(".drag-over");
  if (el) el.classList.remove("drag-over");
});

document.addEventListener("drop", async (event) => {
  if (!dragPayload) return;
  const payload = dragPayload;
  const target = dropTargetFor(event, payload);
  dragPayload = null;
  clearDragMarks();
  if (!target) return;
  event.preventDefault();
  try {
    if (payload.kind === "folder") {
      const parentId = target.type === "root" ? null : target.id;
      await apiJson(`/api/folders/${payload.id}`, "PATCH", { parentId });
      if (parentId) state.expanded.add(parentId);
      invalidateFolderPapers();
      await refresh();
      toast(parentId ? "已移动分类" : "已移到顶层");
    } else if (target.type === "unfiled") {
      await apiJson(`/api/papers/${payload.id}`, "PATCH", { clearFolders: true });
      invalidateFolderPapers();
      await refresh();
      toast("已移出分类");
    } else {
      const current = await api(`/api/papers/${payload.id}`);
      const already = (current.folders || []).some((folder) => folder.id === target.id);
      await apiJson(`/api/papers/${payload.id}`, "PATCH", { addFolderIds: [target.id] });
      invalidateFolderPapers();
      await refresh();
      toast(already ? "文献已在此分类下" : "已加入分类");
    }
  } catch (error) {
    toast(`操作失败：${error.message}`);
  }
});

document.addEventListener("dragend", () => {
  dragPayload = null;
  clearDragMarks();
});

/* --------------------------- folder context menu ------------------------ */

// Right-click (or the "more" button) on a folder in the sidebar: rename it,
// add a sub-folder, delete it. Right-click on a paper: open or delete it.

function closeContextMenu() {
  const menu = $("#context-menu");
  if (menu) menu.remove();
}

/**
 * Show a menu at (x, y). `items` are `{label, icon, danger, sep, run}`.
 */
function openContextMenu(x, y, items) {
  closeContextMenu();

  const entries = items.filter((item) => !item.sep);
  const menu = el(`
    <div class="context-menu" id="context-menu">
      ${items
        .map((item) =>
          item.sep
            ? '<div class="sep"></div>'
            : `<button class="${item.danger ? "danger" : ""}" data-menu-index="${
              entries.indexOf(item)
            }">
          ${item.icon || ""}${escapeHtml(item.label)}
        </button>`
        )
        .join("")}
    </div>`);
  document.body.appendChild(menu);

  // Keep the menu inside the window.
  const rect = menu.getBoundingClientRect();
  menu.style.left = `${Math.max(8, Math.min(x, window.innerWidth - rect.width - 8))}px`;
  menu.style.top = `${Math.max(8, Math.min(y, window.innerHeight - rect.height - 8))}px`;

  menu.addEventListener("click", (event) => {
    const button = event.target.closest("[data-menu-index]");
    if (!button) return;
    const item = entries[Number(button.dataset.menuIndex)];
    closeContextMenu();
    item.run();
  });
}

function openFolderMenu(folderId, x, y) {
  if (!findFolder(state.folders, folderId)) return;
  openContextMenu(x, y, [
    { label: "重命名", icon: ICONS.pencil, run: () => renameFolder(folderId) },
    { label: "添加子文件夹", icon: ICONS.plus, run: () => createFolder(folderId) },
    { sep: true },
    {
      label: "删除分类",
      icon: ICONS.trash,
      danger: true,
      run: () => deleteFolder(folderId),
    },
  ]);
}

function openRootFolderMenu(x, y) {
  openContextMenu(x, y, [
    { label: "新建分类", icon: ICONS.plus, run: () => createFolder(null) },
  ]);
}

function openPaperMenu(paperId, x, y) {
  openContextMenu(x, y, [
    {
      label: "打开阅读页",
      icon: ICONS.external,
      run: () => window.open(`/paper/${paperId}`, "_blank", "noopener"),
    },
    { sep: true },
    {
      label: "删除文献",
      icon: ICONS.trash,
      danger: true,
      run: () => deletePaper(paperId),
    },
  ]);
}

document.addEventListener("contextmenu", (event) => {
  const folderEl = event.target.closest(".folder-item[data-folder]");
  if (folderEl) {
    event.preventDefault();
    if (folderEl.dataset.folder === "all") {
      openRootFolderMenu(event.clientX, event.clientY);
    } else {
      openFolderMenu(Number(folderEl.dataset.folder), event.clientX, event.clientY);
    }
    return;
  }
  const titleEl = event.target.closest(".paper-title-cell");
  if (titleEl) {
    // Right click on a title in the list: rename it or open the reader.
    event.preventDefault();
    const row = titleEl.closest(".paper-row");
    const paper = state.papers.find((p) => p.id === Number(row.dataset.paper));
    if (paper) openPaperTitleMenu(paper, event.clientX, event.clientY);
    return;
  }
  const paperEl = event.target.closest(".tree-paper[data-paper], .unfiled-item[data-paper]");
  if (paperEl) {
    event.preventDefault();
    openPaperMenu(Number(paperEl.dataset.paper), event.clientX, event.clientY);
    return;
  }
  closeContextMenu();
});

// Clicking anywhere else closes the menu. The "more" button that opens the
// menu must not close it again on the very same click.
document.addEventListener("click", (event) => {
  if (event.target.closest(".context-menu")) return;
  if (event.target.closest("[data-folder-menu]")) return;
  if (event.target.closest("[data-role='title-menu']")) return;
  closeContextMenu();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeContextMenu();
});

document.addEventListener(
  "input",
  (event) => {
    if (event.target.id === "search") {
      // Only remember the text here; the search itself runs on Enter.
      state.searchText = event.target.value;
    }
  },
  true
);

document.addEventListener("keydown", async (event) => {
  if (event.key !== "Enter" || event.target.id !== "search") return;
  event.preventDefault();
  state.query = state.searchText.trim();
  state.page = 1;
  await refresh();
});

document.addEventListener("change", async (event) => {
  if (event.target.id === "read-filter") {
    state.read = event.target.value;
    state.page = 1;
    await refresh();
    return;
  }
  if (event.target.id === "sort") {
    state.sort = event.target.value;
    state.page = 1;
    await refresh();
    return;
  }
  if (event.target.id === "sort-order") {
    state.order = event.target.value;
    state.page = 1;
    await refresh();
    return;
  }
  if (event.target.id === "page-size") {
    state.pageSize = Number(event.target.value) || 40;
    state.page = 1;
    await refresh();
    scrollListTop();
  }
});

/* ----------------------------- sidebar resizer ------------------------- */

const SIDEBAR_DEFAULT = 240;
const SIDEBAR_MIN = 160;
const SIDEBAR_MAX = 520;
const SIDEBAR_KEY = "paper-reader.sidebar-width";

// The sidebar may never take more than half of the window, otherwise the
// paper list has no room left.
const sidebarCeiling = () =>
  Math.max(SIDEBAR_MIN, Math.floor(window.innerWidth / 2));

const clampSidebar = (px) =>
  Math.max(
    SIDEBAR_MIN,
    Math.min(SIDEBAR_MAX, sidebarCeiling(), Math.round(px))
  );

function setSidebarWidth(px, persist = true) {
  const width = clampSidebar(px);
  document.documentElement.style.setProperty("--sidebar-width", `${width}px`);
  if (persist) {
    try {
      localStorage.setItem(SIDEBAR_KEY, String(width));
    } catch {
      // private mode / disabled storage — the width just won't persist
    }
  }
  return width;
}

function initSidebarResizer() {
  const resizer = document.querySelector("#sidebar-resizer");
  const sidebar = document.querySelector("#sidebar");
  if (!resizer || !sidebar) return;

  const currentWidth = () => sidebar.getBoundingClientRect().width;

  // Keep the handle on the actual right edge of the sidebar.
  const placeResizer = () => {
    const right = sidebar.getBoundingClientRect().right;
    resizer.style.left = `${Math.round(right - 3)}px`;
  };

  try {
    const saved = Number(localStorage.getItem(SIDEBAR_KEY));
    if (saved) setSidebarWidth(saved, false);
  } catch {
    // ignore unreadable storage
  }
  placeResizer();

  let startX = 0;
  let startWidth = 0;
  let dragging = false;

  resizer.addEventListener("pointerdown", (event) => {
    dragging = true;
    startX = event.clientX;
    startWidth = currentWidth();
    resizer.setPointerCapture(event.pointerId);
    document.body.style.userSelect = "none";
    document.body.style.cursor = "col-resize";
    event.preventDefault();
  });

  resizer.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    setSidebarWidth(startWidth + (event.clientX - startX));
    placeResizer();
  });

  const stop = (event) => {
    if (!dragging) return;
    dragging = false;
    if (event.pointerId !== undefined && resizer.hasPointerCapture(event.pointerId)) {
      resizer.releasePointerCapture(event.pointerId);
    }
    document.body.style.userSelect = "";
    document.body.style.cursor = "";
  };
  resizer.addEventListener("pointerup", stop);
  resizer.addEventListener("pointercancel", stop);

  resizer.addEventListener("dblclick", () => {
    setSidebarWidth(SIDEBAR_DEFAULT);
    placeResizer();
  });

  resizer.addEventListener("keydown", (event) => {
    const step = event.shiftKey ? 48 : 16;
    const current = currentWidth();
    let next = null;
    if (event.key === "ArrowLeft") next = current - step;
    else if (event.key === "ArrowRight") next = current + step;
    else if (event.key === "Home") next = SIDEBAR_MIN;
    else if (event.key === "End") next = SIDEBAR_MAX;
    if (next === null) return;
    event.preventDefault();
    setSidebarWidth(next);
    placeResizer();
  });

  window.addEventListener("resize", () => {
    // The ceiling depends on the window width, so re-clamp on every resize.
    setSidebarWidth(currentWidth(), false);
    placeResizer();
  });
}

/* ---------------------------- column widths ---------------------------- */

const COLUMNS_KEY = "paper-reader.column-widths";

// The columns of the paper list, in the order they appear.
const COLUMN_ORDER = ["title", "tag", "remark", "stars", "read"];

// The width every column starts with. The title column has none of its own:
// it fills whatever the other columns leave over.
const COL_WIDTH_DEFAULTS = {
  tag: 190,
  remark: 150,
  stars: 120,
  read: 64,
};

const COL_WIDTH_LIMITS = {
  title: [120, 1200],
  tag: [80, 600],
  remark: [80, 600],
  stars: [80, 300],
  read: [50, 200],
};

function applyColumnWidths() {
  const content = document.getElementById("content");
  if (!content) return;
  for (const [key, value] of Object.entries(state.colWidths)) {
    content.style.setProperty(`--w-${key}`, `${value}px`);
  }
  content.style.setProperty(
    "--w-title",
    state.titleFlexible || !state.colWidths.title
      ? "minmax(240px, 1fr)"
      : `${state.colWidths.title}px`
  );
}

function loadColumnWidths() {
  try {
    const saved = JSON.parse(localStorage.getItem(COLUMNS_KEY) || "{}");
    let titleOk = false;
    for (const [key, limits] of Object.entries(COL_WIDTH_LIMITS)) {
      const value = Number(saved[key]);
      if (!Number.isFinite(value) || value <= 0) continue;
      state.colWidths[key] = Math.round(
        Math.max(limits[0], Math.min(limits[1], value))
      );
      if (key === "title") titleOk = true;
    }
    // A stored title width only counts when the title is not flexible any
    // more - otherwise the title fills the window again.
    state.titleFlexible = !titleOk;
  } catch {
    // unreadable storage - the defaults are fine
  }
}

function saveColumnWidths() {
  try {
    const saved = { ...state.colWidths };
    if (state.titleFlexible) delete saved.title;
    localStorage.setItem(COLUMNS_KEY, JSON.stringify(saved));
  } catch {
    // private mode: the widths just won't persist
  }
}

/**
 * The title column is the flexible one until the first column is dragged:
 * it then takes the space the other columns leave over. Once a column is
 * dragged, every column gets the width it has on screen and the list
 * behaves like a table with fixed columns.
 */
function freezeColumnWidths(cells) {
  if (!state.titleFlexible) return;
  const widths = {};
  for (const cell of cells) {
    const key = cell.dataset.col;
    if (!key) continue;
    widths[key] = Math.round(cell.getBoundingClientRect().width);
  }
  for (const key of COLUMN_ORDER) {
    if (widths[key]) state.colWidths[key] = widths[key];
  }
  state.titleFlexible = false;
}

// Dragging the border on the right of a column changes the width of that
// column; the columns behind it move along.
let columnDrag = null;
let lastResizeClick = { key: null, at: 0 };

document.addEventListener("pointerdown", (event) => {
  const handle = event.target.closest("[data-resize]");
  if (!handle) return;
  const header = document.querySelector("#content .list-header");
  if (!header) return;
  const cells = [...header.querySelectorAll(":scope > .col")];
  const key = handle.dataset.resize;
  if (!COLUMN_ORDER.includes(key)) return;
  event.preventDefault();
  event.stopPropagation();

  // Two clicks on the same border put the column back to its default width.
  // The browser's own double click does not arrive here: cancelling the
  // pointer down also cancels the mouse events it would come from.
  const now = Date.now();
  if (lastResizeClick.key === key && now - lastResizeClick.at < 500) {
    lastResizeClick = { key: null, at: 0 };
    if (key === "title") {
      // The title fills the window again.
      state.titleFlexible = true;
    } else {
      state.colWidths[key] = COL_WIDTH_DEFAULTS[key];
    }
    applyColumnWidths();
    saveColumnWidths();
    return;
  }
  lastResizeClick = { key, at: now };

  freezeColumnWidths(cells);
  applyColumnWidths();
  columnDrag = {
    key,
    startX: event.clientX,
    startWidth: state.colWidths[key],
  };
  document.body.style.userSelect = "none";
  document.body.style.cursor = "col-resize";
});

document.addEventListener("pointermove", (event) => {
  if (!columnDrag) return;
  const delta = event.clientX - columnDrag.startX;
  const [min, max] = COL_WIDTH_LIMITS[columnDrag.key];
  state.colWidths[columnDrag.key] = Math.round(
    Math.max(min, Math.min(max, columnDrag.startWidth + delta))
  );
  applyColumnWidths();
});

function endColumnDrag() {
  if (!columnDrag) return;
  columnDrag = null;
  document.body.style.userSelect = "";
  document.body.style.cursor = "";
  saveColumnWidths();
}

document.addEventListener("pointerup", endColumnDrag);
document.addEventListener("pointercancel", endColumnDrag);

/* --------------------------------- boot ------------------------------- */

loadColumnWidths();
initSidebarResizer();
await refresh().catch((error) => {
  // The server is unreachable or answered with an error: say so instead of
  // leaving an empty page behind.
  const main = $("#main");
  if (main) {
    main.innerHTML = `<div class="empty">加载失败：${escapeHtml(error.message)}</div>
      <div style="text-align:center"><button class="btn" id="retry-load">重试</button></div>`;
    $("#retry-load")?.addEventListener("click", () => location.reload());
  }
});
