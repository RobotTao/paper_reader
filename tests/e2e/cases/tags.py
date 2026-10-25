"""Adding tags: on a row of the list and on the reading page."""

from __future__ import annotations

import asyncio

from harness import Browser, api_json


async def run(ctx) -> None:
    # Enough tags to see the picker stop at 20.
    for index in range(25):
        api_json(ctx.url, "/api/tags", {"name": f"标签-{index:02d}"})
    api_json(ctx.url, "/api/tags", {"name": "Zebra-Marking"})

    # The second paper carries no tag, so nothing is hidden from the
    # list of suggestions.
    paper = ctx.seeded["papers"][1]
    row = f'.paper-row[data-paper="{paper["id"]}"]'

    async with Browser(ctx.url) as tab:
        check = ctx.check
        await tab.send("Page.navigate", {"url": ctx.url})
        await asyncio.sleep(3)

        # The sidebar lists the tags; that panel is closed by default.
        await tab.js("document.querySelector('[data-action=toggle-tags]').click()")
        await asyncio.sleep(0.6)
        sidebar_tags = (
            "[...document.querySelectorAll('.unfiled-item[data-tag]')].map(n => n.dataset.tag)"
        )
        before = await tab.js(sidebar_tags)
        check("侧栏列出了已有的标签", "Transformer" in before, before)

        # ------------------------------------------- an existing tag
        await tab.js(f"document.querySelector('{row} [data-role=tag-add]').click()")
        await asyncio.sleep(0.8)
        check(
            "标签弹窗打开了",
            bool(await tab.js("!!document.querySelector('#paper-tag-options')")),
        )
        options = await tab.js(
            "document.querySelectorAll('#paper-tag-options .tag-option').length"
        )
        check("已有的标签最多列 20 个", options == 20, options)

        await tab.js(
            "(() => { const o = [...document.querySelectorAll('#paper-tag-options .tag-option')]"
            ".find(o => o.dataset.tagName === 'Transformer'); o.click(); })()"
        )
        await asyncio.sleep(0.4)
        await tab.js("document.querySelector('#paper-tag-ok').click()")
        await asyncio.sleep(2)

        pills = await tab.js(f"document.querySelector('{row} .tag-pills').textContent")
        check("行里出现了这个标签", "Transformer" in pills, pills)
        server = await tab.js(
            f"fetch('/api/papers/{paper['id']}').then(r => r.json())"
            ".then(p => p.tags.map(t => t.name))"
        )
        check("服务端也记下了", "Transformer" in server, server)
        count = await tab.js(
            "(() => { const n = [...document.querySelectorAll('.unfiled-item[data-tag]')]"
            ".find(n => n.dataset.tag === 'Transformer');"
            " return n ? n.querySelector('.count').textContent.trim() : null; })()"
        )
        check("侧栏里的计数跟着更新", count == "2", count)

        # ------------------------------------------- a brand new tag
        await tab.js(f"document.querySelector('{row} [data-role=tag-add]').click()")
        await asyncio.sleep(0.8)
        await tab.js(
            "(() => { const i = document.querySelector('#paper-tag-new');"
            " i.value = '测试新标签';"
            " i.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true})); })()"
        )
        await asyncio.sleep(0.4)
        await tab.js("document.querySelector('#paper-tag-ok').click()")
        await asyncio.sleep(2)

        pills = await tab.js(f"document.querySelector('{row} .tag-pills').textContent")
        check("新建的标签出现在行里", "测试新标签" in pills, pills)
        server = await tab.js(
            f"fetch('/api/papers/{paper['id']}').then(r => r.json())"
            ".then(p => p.tags.map(t => t.name))"
        )
        check("服务端存下了新标签", "测试新标签" in server, server)
        after = await tab.js(sidebar_tags)
        check("新建的标签出现在侧栏里", "测试新标签" in after, after)

        # ------------------------------------------------ taking it off
        await tab.js(f"document.querySelector('{row} [data-role=tag-add]').click()")
        await asyncio.sleep(0.8)
        await tab.js(
            "(() => { const o = [...document.querySelectorAll('#paper-tag-options .tag-option')]"
            ".find(o => o.dataset.tagName === '测试新标签'); o.click(); })()"
        )
        await asyncio.sleep(0.4)
        await tab.js("document.querySelector('#paper-tag-ok').click()")
        await asyncio.sleep(2)

        pills = await tab.js(f"document.querySelector('{row} .tag-pills').textContent")
        check("再去掉标签，行里就没有了", "测试新标签" not in pills, pills)

        # ------------------------------------- the search in the modal
        await tab.js(f"document.querySelector('{row} [data-role=tag-add]').click()")
        await asyncio.sleep(0.8)
        # The letters are there, but not next to each other.
        await tab.js(
            "(() => { const i = document.querySelector('#paper-tag-new');"
            " i.value = 'zmark';"
            " i.dispatchEvent(new Event('input', {bubbles: true})); })()"
        )
        await asyncio.sleep(0.4)
        names = await tab.js(
            "[...document.querySelectorAll('#paper-tag-options .tag-option')]"
            ".map(o => o.dataset.tagName)"
        )
        # The tag the paper already carries is always listed; the rest is
        # what the search found.
        check(
            "模糊匹配能找到已有的标签",
            "Zebra-Marking" in names and "标签-00" not in names,
            names,
        )

        check("页面没有报错", not tab.errors, "; ".join(tab.errors[:3]))

    # --------------------------------------------- the reading page
    async with Browser(ctx.url) as tab:
        check = ctx.check
        await tab.send("Page.navigate", {"url": f"{ctx.url}/paper/{paper['id']}"})
        await asyncio.sleep(3)

        await tab.js("document.querySelector('#toggle-side').click()")
        await asyncio.sleep(0.6)
        await tab.js("document.querySelector('#add-tag').click()")
        await asyncio.sleep(0.8)
        check(
            "阅读页的标签弹窗打开了",
            bool(await tab.js("!!document.querySelector('#tag-suggestions')")),
        )
        count = await tab.js(
            "document.querySelectorAll('#tag-suggestions .tag-suggestion').length"
        )
        check("已有的标签最多显示 20 个", count == 20, count)

        # The letters are there, but not next to each other.
        await tab.js(
            "(() => { const i = document.querySelector('#tag-name');"
            " i.value = 'zmark';"
            " i.dispatchEvent(new Event('input', {bubbles: true})); })()"
        )
        await asyncio.sleep(0.4)
        names = await tab.js(
            "[...document.querySelectorAll('#tag-suggestions .tag-suggestion')]"
            ".map(n => n.textContent.trim())"
        )
        check("模糊匹配能找到已有的标签", names == ["Zebra-Marking"], names)

        # Clicking a suggestion takes the tag.
        await tab.js("document.querySelector('#tag-suggestions .tag-suggestion').click()")
        await asyncio.sleep(1.5)
        chips = await tab.js("document.querySelector('#tag-list').textContent")
        check("点建议就把这个标签加上", "Zebra-Marking" in chips, chips)

        check("页面没有报错", not tab.errors, "; ".join(tab.errors[:3]))
