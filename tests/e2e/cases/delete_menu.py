"""The title menu can delete a paper - into the trash, and back again.

The same window can also take the paper out of its folders while the
paper itself stays in the library.
"""

from __future__ import annotations

import asyncio

from harness import Browser, api_json


async def open_delete_window(tab, pid=None) -> None:
    """Open the delete window of a paper in the list."""
    row = (
        f"document.querySelector('.paper-row[data-paper=\"{pid}\"] .paper-title-cell .title')"
        if pid is not None
        else "document.querySelector('.paper-row .paper-title-cell .title')"
    )
    await tab.js(
        f"{row}.dispatchEvent(new MouseEvent('contextmenu',{{bubbles:true,clientX:300,clientY:200}}))"
    )
    await asyncio.sleep(0.6)
    await tab.js(
        "[...document.querySelectorAll('#context-menu [data-menu-index]')]"
        ".find(el=>el.textContent.includes('删除文献')).click()"
    )
    await asyncio.sleep(0.8)


async def run(ctx) -> None:
    async with Browser(ctx.url) as tab:
        check = ctx.check

        pid = await tab.js("document.querySelector('.paper-row').dataset.paper")
        title = await tab.js("document.querySelector('.paper-row .title').textContent")
        trash_before = await tab.js("fetch('/api/stats').then(r=>r.json()).then(s=>s.trash)")

        # the menu has the delete entry
        await tab.js(
            "document.querySelector('.paper-row .paper-title-cell .title')"
            ".dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,clientX:300,clientY:200}))"
        )
        await asyncio.sleep(0.6)
        menu = await tab.js(
            "document.querySelector('#context-menu')?.textContent.replace(/\\s+/g,' ').trim()"
        )
        check("菜单里有「删除文献」", menu is not None and "删除文献" in menu, menu)
        danger = await tab.js(
            "[...document.querySelectorAll('#context-menu button')].some(b=>"
            "b.textContent.includes('删除文献') && b.classList.contains('danger'))"
        )
        check("删除项是危险色", danger)

        # click it: the delete dialog shows the title of the paper
        await tab.js(
            "[...document.querySelectorAll('#context-menu [data-menu-index]')]"
            ".find(el=>el.textContent.includes('删除文献')).click()"
        )
        await asyncio.sleep(0.8)
        dialog = await tab.js("document.querySelector('#modal-root .modal')?.innerText || ''")
        check("弹出删除确认框", "删除文献" in dialog, dialog)
        check("确认框里写了标题", title.strip() in dialog, dialog)

        # cancel: nothing is deleted
        await tab.js("document.querySelector('#modal-root [data-close]').click()")
        await asyncio.sleep(0.8)
        check(
            "取消后文献还在",
            (await tab.js(f"fetch('/api/papers/{pid}').then(r=>r.status)")) == 200,
        )
        check(
            "取消后垃圾箱没变",
            (await tab.js("fetch('/api/stats').then(r=>r.json()).then(s=>s.trash)")) == trash_before,
        )

        # delete for real
        await tab.js(
            "document.querySelector('.paper-row .paper-title-cell .title')"
            ".dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,clientX:300,clientY:200}))"
        )
        await asyncio.sleep(0.6)
        await tab.js(
            "[...document.querySelectorAll('#context-menu [data-menu-index]')]"
            ".find(el=>el.textContent.includes('删除文献')).click()"
        )
        await asyncio.sleep(0.8)
        await tab.js("document.querySelector('#delete-paper-ok').click()")
        await asyncio.sleep(1.5)
        check("确认后文献进垃圾箱", (await tab.js(f"fetch('/api/papers/{pid}').then(r=>r.status)")) == 404)
        check(
            "垃圾箱多了一篇",
            (await tab.js("fetch('/api/stats').then(r=>r.json()).then(s=>s.trash)")) == trash_before + 1,
        )
        check("列表里没有这篇了", not await tab.js(f"!!document.querySelector('.paper-row[data-paper=\"{pid}\"]')"))

        # restore it
        restored = await tab.js(
            f"fetch('/api/trash').then(r=>r.json()).then(d=>{{"
            f" const item=(d.items||[]).find(x=>x.paperId==={pid});"
            f" return item ? fetch('/api/trash/'+item.id+'/restore',{{method:'POST'}}).then(r=>r.status) : null; }})"
        )
        await asyncio.sleep(1.0)
        check("可以恢复回来", (await tab.js(f"fetch('/api/papers/{pid}').then(r=>r.status)")) == 200, restored)

        # ---- a paper without folders: there is nothing to take it out of ----
        # A paper that is on screen and has no folder (the list on screen can
        # be older than the server - a paper restored behind its back is not
        # in the list yet).
        loose_id = await tab.js(
            "Promise.all([...document.querySelectorAll('.paper-row')].map(r=>"
            " fetch('/api/papers/'+r.dataset.paper).then(r=>r.json())"
            " .then(p=>[p.id,(p.folders||[]).length]))).then(all=>{"
            " const hit=all.find(x=>x[1]===0); return hit?hit[0]:null; })"
        )
        await open_delete_window(tab, loose_id)
        dialog = await tab.js("document.querySelector('#modal-root .modal')?.innerText || ''")
        check("没有分类的文献说明了这一点", "这篇文献没有分类" in dialog, dialog)
        check(
            "没有分类时没有「从分类移除」按钮",
            not await tab.js("!!document.querySelector('#remove-paper-folders')"),
        )
        await tab.js("document.querySelector('#modal-root [data-close]').click()")
        await asyncio.sleep(0.5)

        # ---- taking a paper out of its folders, the paper itself stays ----
        folders = ctx.seeded["folders"]
        slam_id = folders["slam"]["id"]
        cv_id = folders["cv"]["id"]
        pid2 = await tab.js("document.querySelector('.paper-row').dataset.paper")
        api_json(ctx.url, f"/api/papers/{pid2}", {"folderIds": [slam_id, cv_id]}, "PATCH")

        await open_delete_window(tab, pid2)
        dialog = await tab.js("document.querySelector('#modal-root .modal')?.innerText || ''")
        check("弹窗里列出了它的分类", "SLAM" in dialog and "CV" in dialog, dialog)
        check("弹窗里有「从所有分类删除」", "从所有分类删除" in dialog, dialog)
        check(
            "「从分类移除」一开始是灰的",
            await tab.js("document.querySelector('#remove-paper-folders').disabled"),
        )

        # out of both folders at once
        await tab.js("document.querySelector('#remove-all-folders').click()")
        await asyncio.sleep(0.3)
        check(
            "勾选之后「从分类移除」可以点了",
            not await tab.js("document.querySelector('#remove-paper-folders').disabled"),
        )
        await tab.js("document.querySelector('#remove-paper-folders').click()")
        await asyncio.sleep(1.2)
        left = await tab.js(
            f"fetch('/api/papers/{pid2}').then(r=>r.json()).then(p=>p.folders.length)"
        )
        check("文献还在库里", (await tab.js(f"fetch('/api/papers/{pid2}').then(r=>r.status)")) == 200)
        check("分类被清空了", left == 0, left)

        # out of one folder only, the other one stays
        api_json(ctx.url, f"/api/papers/{pid2}", {"folderIds": [slam_id, cv_id]}, "PATCH")
        await open_delete_window(tab, pid2)
        await tab.js(f"document.querySelector('#modal-root input[data-folder=\"{slam_id}\"]').click()")
        await asyncio.sleep(0.3)
        check(
            "勾了一个分类之后「从分类移除」可以点了",
            not await tab.js("document.querySelector('#remove-paper-folders').disabled"),
        )
        await tab.js("document.querySelector('#remove-paper-folders').click()")
        await asyncio.sleep(1.2)
        check(
            "移除后没有报错",
            "失败" not in (await tab.js("document.getElementById('toast')?.textContent || ''")),
            await tab.js("document.getElementById('toast')?.textContent || ''"),
        )
        names = await tab.js(
            f"fetch('/api/papers/{pid2}').then(r=>r.json()).then(p=>p.folders.map(f=>f.name).join(','))"
        )
        check("只从选中的分类里移出", names == "CV", names)
