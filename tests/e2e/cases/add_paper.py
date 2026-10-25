"""The add-paper dialog: a file is needed, a link is not an option."""

from __future__ import annotations

import asyncio

from harness import Browser


async def run(ctx) -> None:
    async with Browser(ctx.url) as tab:
        check = ctx.check

        await tab.js("document.querySelector('[data-action=\"add\"]')?.click()")
        await asyncio.sleep(1)

        check("弹窗打开了", bool(await tab.js("!!document.querySelector('#add-submit')")))
        check(
            "没有「链接 / 标题」这个 tab",
            not (await tab.js(
                "[...document.querySelectorAll('#modal-root [data-tab]')].some(n => n.textContent.includes('链接'))"
            )),
        )
        check("没有链接输入框", not (await tab.js("!!document.querySelector('#link-url')")))
        check("有文件选择区", bool(await tab.js("!!document.querySelector('#drop-zone')")))

        # submitting without a file must be refused
        await tab.js("document.querySelector('#add-submit').click()")
        await asyncio.sleep(1)
        check("没选文件时弹窗不关闭", bool(await tab.js("!!document.querySelector('#add-submit')")))
        toast = await tab.js("document.querySelector('#toast')?.textContent.trim() || ''")
        check("提示要选 PDF", "PDF" in toast, toast)
