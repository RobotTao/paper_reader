"""Uploading a file that is already in the library stops at the door."""

from __future__ import annotations

import asyncio

from harness import Browser, source_file


async def run(ctx) -> None:
    async with Browser(ctx.url) as tab:
        check = ctx.check

        rows_before = await tab.js("document.querySelectorAll('.paper-row').length")
        titles_before = await tab.js(
            "JSON.stringify([...document.querySelectorAll('.paper-row .title')].map(n=>n.textContent.trim()))"
        )

        # open the add dialog
        await tab.js("document.querySelector('[data-action=\"add\"]')?.click()")
        await asyncio.sleep(1)
        check("打开「添加文献」弹窗", bool(await tab.js("!!document.querySelector('#add-submit')")))

        # put the file into the file input - the very same bytes as the
        # paper that is already in the library
        path = source_file(ctx.root, "icp")
        await tab.open_file_input("#file-input", str(path))
        await asyncio.sleep(1)
        chip = await tab.js("document.querySelector('#file-chip')?.textContent.trim()")
        check("文件已选好", bool(chip and path.name in chip), chip)

        # submit
        await tab.js("document.querySelector('#add-submit').click()")
        await asyncio.sleep(2.5)

        header = await tab.js(
            "document.querySelector('#modal-root .modal header')?.textContent.trim() || ''"
        )
        body = await tab.js(
            "document.querySelector('#modal-root .modal .body')?.textContent.replace(/\\s+/g,' ').trim() || ''"
        )
        check("弹窗标题是「这篇已经在库里了」", "这篇已经在库里了" in header, header)
        check("弹窗里有已有文献的标题", "Point-to-Point ICP" in body, body)
        check("弹窗里有分类的完整路径", "SLAM / 点云" in body, body)
        check("弹窗有「知道了」按钮", bool(await tab.js("!!document.querySelector('#modal-root .btn.primary')")))

        # close it
        await tab.js("document.querySelector('#modal-root .btn.primary').click()")
        await asyncio.sleep(1)
        check("点「知道了」后弹窗关闭", not (await tab.js("!!document.querySelector('#modal-root .modal')")))

        rows_after = await tab.js("document.querySelectorAll('.paper-row').length")
        titles_after = await tab.js(
            "JSON.stringify([...document.querySelectorAll('.paper-row .title')].map(n=>n.textContent.trim()))"
        )
        check("列表没有多出一篇", rows_after == rows_before, f"{rows_before} -> {rows_after}")
        check("列表内容没有变化", titles_before == titles_after)
