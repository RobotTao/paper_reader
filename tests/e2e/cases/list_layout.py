"""The list itself: no multi select, the columns line up, the row still works."""

from __future__ import annotations

import asyncio

from harness import Browser


async def run(ctx) -> None:
    async with Browser(ctx.url) as tab:
        await tab.reset_view()

        check = ctx.check

        # 1. the multi select is gone
        check(
            "没有多选按钮",
            not await tab.js("!!document.querySelector('[data-action=toggle-multi]')"),
        )
        check("没有批量条", not await tab.js("!!document.querySelector('.bulk-bar')"))
        check("行里没有复选框", not await tab.js("!!document.querySelector('.paper-row .checkbox')"))

        # 2. the columns line up
        header_cols = await tab.js(
            "[...document.querySelectorAll('#content .list-header > .col')].map(c=>c.dataset.col)"
        )
        check("表头是 5 列", header_cols == ["title", "tag", "remark", "stars", "read"], header_cols)
        row_cells = await tab.js(
            "[...document.querySelector('.paper-row').children].map(c=>"
            "c.className.split(' ')[0] || c.dataset.role)"
        )
        check(
            "数据行的格子与表头一致",
            row_cells == ["paper-title-cell", "tag-cell", "remark-cell", "stars-cell", "read-cell"],
            row_cells,
        )
        widths_ok = await tab.js(
            "(() => { const h=[...document.querySelectorAll('#content .list-header > .col')];"
            " const r=[...document.querySelector('.paper-row').children];"
            " return h.every((c,i)=>Math.abs(c.getBoundingClientRect().width - r[i].getBoundingClientRect().width)<1); })()"
        )
        check("表头与数据行宽度一致", widths_ok)

        # 3. the read button still asks before it changes
        row_id = await tab.js("document.querySelector('.paper-row').dataset.paper")
        before = await tab.js(f"fetch('/api/papers/{row_id}').then(r=>r.json()).then(p=>p.isRead)")
        await tab.js("document.querySelector('.paper-row [data-role=read-toggle]').click()")
        await asyncio.sleep(0.4)
        check("已读仍然要确认", await tab.js("!!document.querySelector('#modal-root .modal')"))
        await tab.js("document.querySelector('#modal-root [data-confirm]').previousElementSibling.click()")
        await asyncio.sleep(0.6)
        after = await tab.js(f"fetch('/api/papers/{row_id}').then(r=>r.json()).then(p=>p.isRead)")
        check("取消后状态没变", before == after, f"{before} -> {after}")

        # 4. the title still opens the reader
        await tab.js("window.__opened = []; window.open = (u) => { window.__opened.push(u); return null; }")
        await tab.js("document.querySelector('.paper-row .paper-title-cell .title').click()")
        opened = await tab.js("window.__opened.slice()")
        check("点标题仍然打开阅读页", len(opened) == 1 and "/paper/" in opened[0], opened)

        # 5. no javascript errors
        await asyncio.sleep(0.5)
        check("页面没有报错", not tab.errors, tab.errors[:3])
