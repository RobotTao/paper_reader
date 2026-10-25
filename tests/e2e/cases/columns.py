"""The columns of the list: resizing, the title menu, the tags and the remark."""

from __future__ import annotations

import asyncio
import json

from harness import Browser


async def run(ctx) -> None:
    async with Browser(ctx.url) as tab:
        await tab.reset_view()

        check = ctx.check

        # ---------------------------------------------------------- resize
        before = await tab.js(
            "document.querySelector('#content .list-header [data-col=tag]').offsetWidth"
        )
        box = await tab.js(
            "(() => { const r = document.querySelector('[data-resize=tag]').getBoundingClientRect();"
            " return {x: r.left + r.width/2, y: r.top + r.height/2}; })()"
        )
        await tab.mouse("mousePressed", box["x"], box["y"])
        for step in range(1, 7):
            await tab.mouse("mouseMoved", box["x"] - 10 * step, box["y"])
            await asyncio.sleep(0.05)
        await tab.mouse("mouseReleased", box["x"] - 60, box["y"])
        await asyncio.sleep(0.8)
        after = await tab.js(
            "document.querySelector('#content .list-header [data-col=tag]').offsetWidth"
        )
        check("拖动后标签列变窄 60px", abs((before - after) - 60) <= 2, f"{before} -> {after}")

        stored = await tab.js("localStorage.getItem('paper-reader.column-widths')")
        check("列宽已写入 localStorage", stored and '"tag":130' in stored.replace(" ", ""), stored)

        row_tag = await tab.js("document.querySelector('.paper-row .tag-cell').offsetWidth")
        head_tag = await tab.js(
            "document.querySelector('#content .list-header [data-col=tag]').offsetWidth"
        )
        check("表头与数据行宽度一致", abs(row_tag - head_tag) <= 1, f"{row_tag} / {head_tag}")

        title_w = await tab.js(
            "document.querySelector('#content .list-header [data-col=title]').offsetWidth"
        )
        check("标题列仍然填满剩余空间", title_w > 240, title_w)

        # double click resets the column
        box2 = await tab.js(
            "(() => { const r = document.querySelector('[data-resize=tag]').getBoundingClientRect();"
            " return {x: r.left + r.width/2, y: r.top + r.height/2}; })()"
        )
        await tab.mouse("mousePressed", box2["x"], box2["y"])
        await tab.mouse("mouseReleased", box2["x"], box2["y"])
        await tab.mouse("mousePressed", box2["x"], box2["y"])
        await tab.mouse("mouseReleased", box2["x"], box2["y"])
        await asyncio.sleep(0.8)
        reset = await tab.js(
            "document.querySelector('#content .list-header [data-col=tag]').offsetWidth"
        )
        check("双击分隔线恢复默认宽度", abs(reset - 190) <= 2, reset)

        # ------------------------------------------------------- title menu
        pid = await tab.js("document.querySelector('.paper-row').dataset.paper")
        await tab.js(
            "document.querySelector('.paper-row .paper-title-cell .title')"
            ".dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,clientX:300,clientY:200}))"
        )
        await asyncio.sleep(0.6)
        menu = await tab.js(
            "document.querySelector('#context-menu')?.textContent.replace(/\\s+/g,' ').trim()"
        )
        check("右键标题弹出菜单", menu is not None and "修改标题" in menu, menu)

        await tab.js(
            "[...document.querySelectorAll('#context-menu [data-menu-index]')]"
            ".find(el=>el.textContent.includes('修改标题')).click()"
        )
        await asyncio.sleep(0.8)
        opened = await tab.js("!!document.querySelector('#paper-title-input')")
        check("菜单打开改标题弹窗", opened)

        await tab.js(
            "(() => { const i = document.querySelector('#paper-title-input');"
            " i.value = '改名测试标题'; document.querySelector('#paper-title-ok').click(); })()"
        )
        await asyncio.sleep(1.5)
        shown = await tab.js(
            "document.querySelector('.paper-row .paper-title-cell .title').textContent"
        )
        saved = await tab.js(f"fetch('/api/papers/{pid}').then(r=>r.json()).then(p=>p.title)")
        check("列表标题已改", shown == "改名测试标题", shown)
        check("服务端标题已改", saved == "改名测试标题", saved)

        # --------------------------------------------------------- tag picker
        tags_before = await tab.js(
            f"fetch('/api/papers/{pid}').then(r=>r.json()).then(p=>p.tags.map(t=>t.name))"
        )
        await tab.js("document.querySelector('.paper-row [data-role=tag-add]').click()")
        await asyncio.sleep(0.8)
        picker = await tab.js("!!document.querySelector('#paper-tag-options')")
        check("标签 + 打开标签弹窗", picker)
        options = await tab.js("document.querySelectorAll('#paper-tag-options .tag-option').length")
        check("弹窗列出已有标签", options > 0, options)

        picked = await tab.js(
            "(() => { const opts=[...document.querySelectorAll('#paper-tag-options .tag-option')];"
            f" const before = new Set({json.dumps(tags_before)});"
            " const opt = opts.find(o => !before.has(o.dataset.tagName));"
            " if (!opt) return null; opt.click(); return opt.dataset.tagName; })()"
        )
        check("能选中一个未添加的标签", picked is not None, picked)
        await tab.js("document.querySelector('#paper-tag-ok').click()")
        await asyncio.sleep(1.8)
        tags_after = await tab.js(
            f"fetch('/api/papers/{pid}').then(r=>r.json()).then(p=>p.tags.map(t=>t.name))"
        )
        check("服务端标签已更新", picked in tags_after, tags_after)
        pills = await tab.js("document.querySelector('.paper-row .tag-pills').textContent")
        check("行内标签已刷新", picked in pills, pills)

        # a brand new tag
        await tab.js("document.querySelector('.paper-row [data-role=tag-add]').click()")
        await asyncio.sleep(0.8)
        await tab.js(
            "(() => { const i = document.querySelector('#paper-tag-new');"
            " i.value = '新建测试标签'; i.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true})); })()"
        )
        await asyncio.sleep(0.5)
        await tab.js("document.querySelector('#paper-tag-ok').click()")
        await asyncio.sleep(1.8)
        tags_new = await tab.js(
            f"fetch('/api/papers/{pid}').then(r=>r.json()).then(p=>p.tags.map(t=>t.name))"
        )
        check("可以新建标签", "新建测试标签" in tags_new, tags_new)

        # ----------------------------------------------------------- remark
        await tab.js("document.querySelector('.paper-row [data-role=remark]').click()")
        await asyncio.sleep(0.6)
        editing = await tab.js("!!document.querySelector('.paper-row .remark-input')")
        check("点击备注进入编辑", editing)
        await tab.js(
            "(() => { const i = document.querySelector('.paper-row .remark-input');"
            " i.value = '备注测试内容'; i.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true})); })()"
        )
        await asyncio.sleep(1.5)
        remark_after = await tab.js(
            f"fetch('/api/papers/{pid}').then(r=>r.json()).then(p=>p.remark)"
        )
        shown_remark = await tab.js(
            "document.querySelector('.paper-row [data-role=remark]').textContent.trim()"
        )
        check("服务端备注已保存", remark_after == "备注测试内容", remark_after)
        check("行内备注已更新", shown_remark == "备注测试内容", shown_remark)
