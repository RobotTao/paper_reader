"""The reading page: the hidden menu, the side panel, the page counter."""

from __future__ import annotations

import asyncio

from harness import (
    MULTI_PAGE_PDF_BYTES,
    MULTILINE_PDF_BYTES,
    OUTLINE_PDF_BYTES,
    TEXT_PDF_BYTES,
    Browser,
    upload_pdf,
)


async def click_highlight(tab, selector: str) -> None:
    """Click on a highlight, the way a reader does: with the mouse."""
    spot = await tab.js(
        f"(() => {{ const h = document.querySelector('{selector}');"
        " const r = h.getBoundingClientRect();"
        " return {x: r.left + r.width / 2, y: r.top + r.height / 2}; })()"
    )
    await tab.send(
        "Input.dispatchMouseEvent",
        {
            "type": "mousePressed",
            "x": spot["x"],
            "y": spot["y"],
            "button": "left",
            "buttons": 1,
            "clickCount": 1,
        },
    )
    await tab.send(
        "Input.dispatchMouseEvent",
        {
            "type": "mouseReleased",
            "x": spot["x"],
            "y": spot["y"],
            "button": "left",
            "buttons": 0,
            "clickCount": 1,
        },
    )


async def run(ctx) -> None:
    paper_id = ctx.seeded["papers"][0]["id"]
    async with Browser(ctx.url) as tab:
        check = ctx.check

        await tab.send("Page.navigate", {"url": f"{ctx.url}/paper/{paper_id}"})
        await asyncio.sleep(3)

        check("阅读页打开了", bool(await tab.js("!!document.querySelector('.reader')")))
        check("PDF 渲染出来了", bool(await tab.js("!!document.querySelector('.pdf-page canvas')")))

        # The tab says which paper is open.
        title = ctx.seeded["papers"][0]["title"]
        tab_title = await tab.js("document.title")
        check("标签页标题是论文标题", tab_title == title, f"{tab_title} != {title}")

        # The top bar is gone; a small button in the corner downloads the
        # paper - there is no menu to open first.
        check("没有顶部的工具栏", not (await tab.js("!!document.querySelector('.reader-toolbar')")))
        check(
            "没有菜单了",
            not (await tab.js("!!document.querySelector('#reader-menu')"))
            and not (await tab.js("!!document.querySelector('#menu-toggle')")),
        )
        box = await tab.js(
            "JSON.stringify(document.querySelector('#download-paper').getBoundingClientRect())"
        )
        check("左上角的小控件看得见", '"width":26' in box.replace(" ", ""), box)
        check(
            "左上角就是下载按钮",
            await tab.js(
                "document.querySelector('#download-paper').tagName.toLowerCase()"
            )
            == "button",
        )
        check(
            "阅读页没有删除按钮",
            not (await tab.js("!!document.querySelector('#delete-paper')")),
        )
        check(
            "信息侧栏有自己的悬浮按钮",
            await tab.js(
                "JSON.stringify((() => { const b = document.querySelector('#toggle-side');"
                " return !!b && getComputedStyle(b).position === 'absolute'; })())"
            )
            == "true",
        )

        # The side panel starts closed: the PDF gets the whole width.
        display = await tab.js(
            "getComputedStyle(document.querySelector('.reader-side')).display"
        )
        columns = await tab.js(
            "getComputedStyle(document.querySelector('.reader')).gridTemplateColumns"
        )
        check("侧栏默认是关着的", display == "none", display)
        check("默认只有一列", columns.count("px") == 1, columns)

        # The handle of the side panel: a small flat button on the right
        # edge, half way down.
        check(
            "侧栏按钮在右侧、竖直居中",
            await tab.js(
                "(() => { const b = document.querySelector('#toggle-side')"
                ".getBoundingClientRect();"
                " const r = document.querySelector('.reader').getBoundingClientRect();"
                " return b.left > r.left + r.width / 2"
                " && Math.abs((b.top + b.bottom) / 2 - (r.top + r.bottom) / 2) < 5; })()"
            )
            is True,
        )
        check(
            "按钮是长扁的小条",
            await tab.js(
                "(() => { const b = document.querySelector('#toggle-side')"
                ".getBoundingClientRect();"
                " return b.width > b.height && b.width < 60 && b.height < 28; })()"
            )
            is True,
        )
        check(
            "关闭时贴在窗口右边缘",
            await tab.js(
                "(() => { const b = document.querySelector('#toggle-side')"
                ".getBoundingClientRect();"
                " const r = document.querySelector('.reader').getBoundingClientRect();"
                " return Math.abs(b.right - r.right) < 2; })()"
            )
            is True,
        )
        check(
            "关闭时箭头朝左",
            await tab.js("!!document.querySelector('#toggle-side svg.chev-left')") is True,
        )

        # Open it with its own button.
        await tab.js("document.querySelector('#toggle-side').click()")
        await asyncio.sleep(0.6)
        display = await tab.js(
            "getComputedStyle(document.querySelector('.reader-side')).display"
        )
        columns = await tab.js(
            "getComputedStyle(document.querySelector('.reader')).gridTemplateColumns"
        )
        check("点一下侧栏就打开了", display != "none", display)
        check("打开后变成两列", columns.count("px") == 2, columns)
        check(
            "按钮标记为展开",
            (await tab.js("document.querySelector('#toggle-side').getAttribute('aria-expanded')"))
            == "true",
        )
        check(
            "打开后箭头朝右",
            await tab.js("!!document.querySelector('#toggle-side svg.chev-right')") is True,
        )
        check(
            "打开后按钮骑在分隔线上",
            await tab.js(
                "(() => { const b = document.querySelector('#toggle-side')"
                ".getBoundingClientRect();"
                " const r = document.querySelector('.reader').getBoundingClientRect();"
                " return Math.abs((b.left + b.right) / 2 - (r.right - 360)) < 3; })()"
            )
            is True,
        )

        # And close it again.
        await tab.js("document.querySelector('#toggle-side').click()")
        await asyncio.sleep(0.6)
        display = await tab.js(
            "getComputedStyle(document.querySelector('.reader-side')).display"
        )
        check("再点一下又关上了", display == "none", display)
        check(
            "收起后箭头又朝左",
            await tab.js("!!document.querySelector('#toggle-side svg.chev-left')") is True,
        )

        # The bar at the bottom of the PDF: where to go, how big, what to do.
        check("底部有工具条", bool(await tab.js("!!document.querySelector('.pdf-toolbar')")))
        floating = await tab.js(
            "getComputedStyle(document.querySelector('.pdf-toolbar')).position"
        )
        check("工具条是浮在 PDF 上的", floating == "absolute", floating)
        check(
            "工具条上有查找、框选",
            await tab.js(
                "JSON.stringify(['#pdf-find-btn','#frame-toggle']"
                ".every(s => !!document.querySelector(s)))"
            )
            == "true",
        )
        check(
            "工具条上没有目录（左边那个按钮就够了）",
            await tab.js("!document.querySelector('#pdf-outline-btn')") is True,
        )
        check(
            "工具条上有页码和缩放",
            await tab.js(
                "JSON.stringify(['#pdf-page-input','#pdf-page-total','#pdf-zoom-level']"
                ".every(s => !!document.querySelector(s)))"
            )
            == "true",
        )
        page_value = await tab.js("document.querySelector('#pdf-page-input').value")
        check("页码是第 1 页", page_value == "1", page_value)
        total = await tab.js("document.querySelector('#pdf-page-total').textContent.trim()")
        check("总页数是 1", total == "/ 1", total)
        zoom = await tab.js("document.querySelector('#pdf-zoom-level').textContent.trim()")
        check("工具条上写着缩放的百分比", zoom.endswith("%"), zoom)

        check("页面没有报错", not tab.errors, "; ".join(tab.errors[:3]))

    # A document with several pages: the counter follows the scroll.
    multi = upload_pdf(
        ctx.url, ctx.root, "multi.pdf", "multi", data=MULTI_PAGE_PDF_BYTES, title="多页文献"
    )
    async with Browser(ctx.url) as tab:
        check = ctx.check
        await tab.send("Page.navigate", {"url": f"{ctx.url}/paper/{multi['id']}"})
        await asyncio.sleep(3)

        page_value = "document.querySelector('#pdf-page-input').value"
        check("页码是第 1 页", (await tab.js(page_value)) == "1", await tab.js(page_value))
        total = "document.querySelector('#pdf-page-total').textContent.trim()"
        check("总页数是 3", (await tab.js(total)) == "/ 3", await tab.js(total))

        await tab.js(
            "(() => { const pages = document.querySelectorAll('.pdf-page');"
            " document.querySelector('#pdf-container').scrollTop = pages[1].offsetTop + 20;"
            " })()"
        )
        await asyncio.sleep(1.5)
        check("往下滚，页码变成第 2 页", (await tab.js(page_value)) == "2", await tab.js(page_value))

        await tab.js(
            "(() => { document.querySelector('#pdf-container').scrollTop = 0; })()"
        )
        await asyncio.sleep(1.5)
        check("滚回顶部，页码回到第 1 页", (await tab.js(page_value)) == "1", await tab.js(page_value))

        # Typing a page number jumps to it.
        await tab.js(
            "(() => { const i = document.querySelector('#pdf-page-input');"
            " i.focus(); i.value = '3';"
            " i.dispatchEvent(new KeyboardEvent('keydown',"
            " {key: 'Enter', bubbles: true})); })()"
        )
        await asyncio.sleep(1.8)
        check("输入页码后跳到第 3 页", (await tab.js(page_value)) == "3", await tab.js(page_value))

        # The zoom controls sit in the bar at the bottom.
        check(
            "工具条上有缩小、放大、适宽",
            await tab.js(
                "JSON.stringify(['#pdf-zoom-out','#pdf-zoom-in','#pdf-fit-width']"
                ".every(s => !!document.querySelector(s)))"
            )
            == "true",
        )
        width = "document.querySelector('.pdf-page').offsetWidth"
        level = "document.querySelector('#pdf-zoom-level').textContent.trim()"

        # The reader opens with the page as wide as the window, and the
        # size on the screen is always a whole ten per cent.
        opened = await tab.js(level)
        check(
            "打开时的大小是 10 的倍数",
            opened.endswith("%") and int(opened[:-1]) % 10 == 0,
            opened,
        )
        container = await tab.js("document.querySelector('#pdf-container').clientWidth")
        check(
            "打开时页面就是适宽",
            await tab.js(width) <= container,
            f"page {await tab.js(width)} / window {container}",
        )

        # Every step is ten per cent.
        before = await tab.js(width)
        await tab.js("document.querySelector('#pdf-zoom-in').click()")
        await asyncio.sleep(1.5)
        after = await tab.js(width)
        check("点「放大」页面变大了", after > before, f"{before} -> {after}")
        zoomed = await tab.js(level)
        check(
            "放大一次是 10",
            int(zoomed[:-1]) - int(opened[:-1]) == 10,
            f"{opened} -> {zoomed}",
        )
        await tab.js("document.querySelector('#pdf-zoom-out').click()")
        await asyncio.sleep(1.5)
        check(
            "缩小一次又是 10",
            await tab.js(level) == opened,
            f"{zoomed} -> {await tab.js(level)}",
        )

        # "Fit width" lands on a round number as well.
        await tab.js("document.querySelector('#pdf-fit-width').click()")
        await asyncio.sleep(1.5)
        fitted_level = await tab.js(level)
        check(
            "「适宽」的大小是 10 的倍数",
            int(fitted_level[:-1]) % 10 == 0,
            fitted_level,
        )
        container = await tab.js("document.querySelector('#pdf-container').clientWidth")
        fitted = await tab.js(width)
        check("「适宽」时页面在窗口里", fitted <= container, f"page {fitted} / window {container}")

        check("页面没有报错", not tab.errors, "; ".join(tab.errors[:3]))

    # ------------------------------------------------- making a highlight
    text_paper = upload_pdf(
        ctx.url, ctx.root, "text.pdf", "text", data=TEXT_PDF_BYTES, title="可标注文献"
    )
    async with Browser(ctx.url) as tab:
        check = ctx.check
        await tab.send("Page.navigate", {"url": f"{ctx.url}/paper/{text_paper['id']}"})
        await asyncio.sleep(3)

        # The text of the page is there: invisible, but selectable.
        spans = await tab.js("document.querySelectorAll('.pdf-page .textLayer span').length")
        check("PDF 有文字层", spans > 0, spans)
        words = await tab.js(
            "document.querySelector('.pdf-page .textLayer span')?.textContent || ''"
        )
        check("文字层里有那句话", "Hello" in words, words)

        # Selecting the text brings up the bar with the colours.
        await tab.js(
            "(() => { const span = document.querySelector('.pdf-page .textLayer span');"
            " const range = document.createRange(); range.selectNodeContents(span);"
            " const sel = getSelection(); sel.removeAllRanges(); sel.addRange(range);"
            " document.querySelector('#pdf-container')"
            ".dispatchEvent(new MouseEvent('mouseup', {bubbles: true})); })()"
        )
        await asyncio.sleep(0.8)
        check("选中文字后工具条出现了", not (await tab.js("document.querySelector('#sel-bar').hidden")))
        colors = await tab.js(
            "[...document.querySelectorAll('#sel-bar .sel-dot')].map(b => b.dataset.color)"
        )
        check(
            "工具条上有五种颜色",
            colors == ["blue", "green", "yellow", "orange", "red"],
            colors,
        )
        check(
            "工具条上有写想法的按钮",
            await tab.js("!!document.querySelector('#sel-bar #sel-idea-btn')") is True,
        )
        dark = await tab.js(
            "getComputedStyle(document.querySelector('#sel-bar')).backgroundColor"
        )
        check("工具条是深色的", dark in ("rgb(57, 60, 62)", "rgba(57, 60, 62, 1)"), dark)

        # The bar hangs at the bottom-right of the last character: its left
        # edge sits on the right edge of that character, five pixels above
        # its bottom - the way readpaper puts it. The selection is measured
        # where the browser draws the text; the line box around the letters
        # is taller than the letters themselves, so the bar may sit a little
        # below them.
        anchor = await tab.js(
            "(() => { const span = document.querySelector('.pdf-page .textLayer span');"
            " const bar = document.querySelector('#sel-bar');"
            " const s = span.getBoundingClientRect(), b = bar.getBoundingClientRect();"
            " const rects = [...getSelection().getRangeAt(0).getClientRects()];"
            " const sel = rects[rects.length - 1];"
            " return { textRight: s.right, textBottom: s.bottom, textHeight: s.height,"
            " selRight: sel.right, selBottom: sel.bottom,"
            " barLeft: b.left, barTop: b.top }; })()"
        )
        check(
            "工具条挂在最后一个字的右下角",
            abs(anchor["barLeft"] - anchor["selRight"]) < 8
            and abs(anchor["barTop"] - (anchor["selBottom"] - 5)) < 4,
            anchor,
        )
        check(
            "工具条就贴在文字边上",
            abs(anchor["barTop"] - (anchor["textBottom"] - 5))
            < max(8, anchor["textHeight"] * 0.25),
            anchor,
        )

        # Hovering a colour shows what the text will look like.
        await tab.js(
            "document.querySelector('#sel-bar .sel-dot.green')"
            ".dispatchEvent(new MouseEvent('mouseenter'))"
        )
        await asyncio.sleep(0.4)
        check(
            "悬停绿色时选区预览绿色",
            await tab.js(
                "document.querySelector('#pdf-container')"
                ".classList.contains('preview-green')"
            )
            is True,
        )
        await tab.js(
            "document.querySelector('#sel-bar .sel-dot.green')"
            ".dispatchEvent(new MouseEvent('mouseleave'))"
        )
        await asyncio.sleep(0.4)
        check(
            "移开鼠标预览就还原",
            await tab.js(
                "document.querySelector('#pdf-container')"
                ".classList.contains('preview-green')"
            )
            is False,
        )

        # An orange highlight.
        await tab.js("document.querySelector('#sel-bar .sel-dot.orange').click()")
        await asyncio.sleep(2)
        server = await tab.js(
            f"fetch('/api/papers/{text_paper['id']}').then(r => r.json())"
            ".then(p => p.annotations.map(a => [a.color, a.text, a.rects.length]))"
        )
        check("服务端记下了这条高亮", server == [["orange", "Hello Paper Reader", 1]], server)
        check(
            "PDF 上画出了橙色的高亮",
            bool(await tab.js("!!document.querySelector('.pdf-highlight.orange')")),
        )

        # The highlight stays on the text when the page is zoomed.
        ratio = (
            "(() => { const h = document.querySelector('.pdf-highlight.orange');"
            " const p = document.querySelector('.pdf-page');"
            " const hr = h.getBoundingClientRect(), pr = p.getBoundingClientRect();"
            " return (hr.left - pr.left) / pr.width; })()"
        )
        before = await tab.js(ratio)
        await tab.js("document.querySelector('#pdf-zoom-in').click()")
        await asyncio.sleep(2)
        after = await tab.js(ratio)
        check("放大之后高亮还在原处", abs(before - after) < 0.02, f"{before} -> {after}")
        spans = await tab.js("document.querySelectorAll('.pdf-page .textLayer span').length")
        check("放大之后文字层还在", spans > 0, spans)

        # The side panel shows it.
        await tab.js("document.querySelector('#toggle-side').click()")
        await asyncio.sleep(0.8)
        panel = await tab.js("document.querySelector('#annot-list').textContent")
        check("侧栏列出了这条高亮", "Hello Paper Reader" in panel, panel)

        # A thought next to it.
        await tab.js(
            "(() => { const t = document.querySelector('.annot-idea');"
            " t.value = '这个方法值得一看';"
            " t.dispatchEvent(new Event('blur')); })()"
        )
        await asyncio.sleep(1.5)
        idea = await tab.js(
            f"fetch('/api/papers/{text_paper['id']}').then(r => r.json())"
            ".then(p => p.annotations[0].idea)"
        )
        check("想法存下来了", idea == "这个方法值得一看", idea)

        # --------------------------------- the popup on the highlight
        # Clicking a highlight that is already there opens a small window
        # on it: a dashed frame, an × to delete it, and the colours.
        await click_highlight(tab, ".pdf-highlight.orange")
        await asyncio.sleep(0.8)
        check(
            "点已有的高亮会弹出小窗",
            not (await tab.js("document.querySelector('#annot-popup').hidden")),
        )
        frame = await tab.js(
            "(() => { const p = document.querySelector('#annot-popup').getBoundingClientRect();"
            " const h = document.querySelector('.pdf-highlight.orange').getBoundingClientRect();"
            " return { dLeft: p.left - h.left, dTop: p.top - h.top,"
            " dWidth: p.width - h.width, dHeight: p.height - h.height }; })()"
        )
        check(
            "虚线框正好框住高亮",
            abs(frame["dLeft"]) < 2
            and abs(frame["dTop"]) < 2
            and abs(frame["dWidth"]) < 2
            and abs(frame["dHeight"]) < 2,
            frame,
        )
        corners = await tab.js(
            "(() => { const h = document.querySelector('.pdf-highlight.orange').getBoundingClientRect();"
            " const x = document.querySelector('#annot-popup-x').getBoundingClientRect();"
            " const t = document.querySelector('#annot-popup-tools').getBoundingClientRect();"
            " return { xRight: x.right - h.right, xTop: x.top - h.top,"
            " tRight: t.right - h.right, tBelow: t.top - h.bottom }; })()"
        )
        check("× 在虚线框的右上角", abs(corners["xRight"] - 9) < 3 and abs(corners["xTop"] + 9) < 3, corners)
        check(
            "颜色在虚线框的右下角",
            abs(corners["tRight"]) < 3 and corners["tBelow"] > 0,
            corners,
        )
        check(
            "小窗里有五个颜色和笔记按钮",
            await tab.js(
                "JSON.stringify({"
                " colors: [...document.querySelectorAll('#annot-popup-tools .sel-dot')]"
                "   .map(b => b.dataset.color),"
                " idea: !!document.querySelector('#annot-popup-idea') })"
            )
            == '{"colors":["blue","green","yellow","orange","red"],"idea":true}',
        )

        # This highlight has a thought (it was written in the side panel):
        # the box above the frame shows it right away.
        shown = await tab.js(
            "(() => { const n = document.querySelector('#annot-popup-note');"
            " const p = document.querySelector('#annot-popup').getBoundingClientRect();"
            " const r = n.getBoundingClientRect();"
            " const m = document.querySelector('.reader-main').getBoundingClientRect();"
            " return { hidden: n.hidden,"
            "   value: document.querySelector('#annot-popup-note-input').value,"
            "   above: r.bottom <= p.top + 2,"
            "   inside: r.top >= m.top - 1 && r.bottom <= m.bottom + 1,"
            "   dLeft: r.left - p.left, dRight: r.right - p.right }; })()"
        )
        check(
            "有想法时输入框带着想法",
            shown["hidden"] is False and shown["value"] == "这个方法值得一看",
            shown,
        )
        check("输入框在虚线框的上方", shown["above"] is True, shown)
        check(
            "输入框和虚线框一样长",
            abs(shown["dLeft"]) < 1 and abs(shown["dRight"]) < 1,
            shown,
        )
        check("输入框没有跑出窗口", shown["inside"] is True, shown)

        # Another colour for the same highlight.
        await tab.js("document.querySelector('#annot-popup-tools .sel-dot.blue').click()")
        await asyncio.sleep(2)
        recoloured = await tab.js(
            f"fetch('/api/papers/{text_paper['id']}').then(r => r.json())"
            ".then(p => p.annotations[0].color)"
        )
        check("服务端记下了新颜色", recoloured == "blue", recoloured)
        check(
            "PDF 上的高亮换成了蓝色",
            bool(await tab.js("!!document.querySelector('.pdf-highlight.blue')")),
        )

        # A thought, written in the popup.
        await tab.js("document.querySelector('#annot-popup-idea').click()")
        await asyncio.sleep(0.4)
        await tab.js(
            "(() => { const i = document.querySelector('#annot-popup-note-input');"
            " i.value = '在小窗里写的想法';"
            " i.dispatchEvent(new Event('blur')); })()"
        )
        await asyncio.sleep(2)
        thought = await tab.js(
            f"fetch('/api/papers/{text_paper['id']}').then(r => r.json())"
            ".then(p => p.annotations[0].idea)"
        )
        check("小窗里的想法存下来了", thought == "在小窗里写的想法", thought)

        # The thought stays in the box, and it is there when the highlight
        # is clicked again.
        shown = await tab.js(
            "(() => { const n = document.querySelector('#annot-popup-note');"
            " return { hidden: n.hidden,"
            "   value: document.querySelector('#annot-popup-note-input').value }; })()"
        )
        check(
            "有想法时输入框带着想法",
            shown["hidden"] is False and shown["value"] == "在小窗里写的想法",
            shown,
        )
        await tab.js("getSelection().removeAllRanges()")
        await tab.js("document.body.click()")
        await asyncio.sleep(0.5)
        check(
            "小窗关上了",
            await tab.js("document.querySelector('#annot-popup').hidden") is True,
        )
        await click_highlight(tab, ".pdf-highlight.blue")
        await asyncio.sleep(0.8)
        again = await tab.js(
            "(() => { const n = document.querySelector('#annot-popup-note');"
            " return { hidden: n.hidden,"
            "   value: document.querySelector('#annot-popup-note-input').value }; })()"
        )
        check(
            "再点高亮，想法直接显示出来",
            again["hidden"] is False and again["value"] == "在小窗里写的想法",
            again,
        )

        # ------------------------------------------- drawing a frame
        await tab.js("document.querySelector('#frame-toggle').click()")
        await asyncio.sleep(0.5)
        check(
            "进入框选模式",
            (await tab.js("document.querySelector('#frame-toggle').getAttribute('aria-pressed')"))
            == "true",
        )
        # The real thing: the mouse is pressed, moved and let go. The click
        # that the browser sends at the end of such a drag must not take
        # anything away. The frame is drawn in the lower half of the page,
        # where the text - and the popup on it - is not.
        corner = await tab.js(
            "(() => { const p = document.querySelector('.pdf-page');"
            " const r = p.getBoundingClientRect();"
            " return {x: r.left + 30, y: r.top + r.height * 0.6,"
            "  dx: r.width * 0.4, dy: r.height * 0.25}; })()"
        )
        await tab.mouse("mousePressed", corner["x"], corner["y"])
        await tab.mouse("mouseMoved", corner["x"] + corner["dx"] / 2, corner["y"] + corner["dy"] / 2)
        await tab.mouse("mouseMoved", corner["x"] + corner["dx"], corner["y"] + corner["dy"])
        await tab.mouse("mouseReleased", corner["x"] + corner["dx"], corner["y"] + corner["dy"])
        await asyncio.sleep(2.5)
        check(
            "框选之后不用再挑颜色",
            bool(await tab.js("document.querySelector('#sel-bar').hidden")),
        )
        check(
            "PDF 上画出了这个框",
            bool(await tab.js("!!document.querySelector('.pdf-highlight.area')")),
        )
        frames = await tab.js(
            f"fetch('/api/papers/{text_paper['id']}').then(r => r.json())"
            ".then(p => p.annotations.map(a => [a.color, (a.rects[0] || {}).kind]))"
        )
        check("服务端记下了这个框", frames[-1][1] == "area", frames)
        # The colour is changed afterwards, by clicking on the frame.
        await click_highlight(tab, ".pdf-highlight.area")
        await asyncio.sleep(1)
        await tab.js("document.querySelector('#annot-popup-tools .sel-dot.green').click()")
        await asyncio.sleep(2)
        frames = await tab.js(
            f"fetch('/api/papers/{text_paper['id']}').then(r => r.json())"
            ".then(p => p.annotations.map(a => [a.color, (a.rects[0] || {}).kind]))"
        )
        check("框换成了绿色", frames[-1] == ["green", "area"], frames)
        check(
            "PDF 上画出了绿色的框",
            bool(await tab.js("!!document.querySelector('.pdf-highlight.green.area')")),
        )

        # This one has no thought: no box, until the button is used.
        await click_highlight(tab, ".pdf-highlight.green.area")
        await asyncio.sleep(0.8)
        check(
            "没有想法时不显示输入框",
            await tab.js("document.querySelector('#annot-popup-note').hidden") is True,
        )
        await tab.js("document.querySelector('#annot-popup-idea').click()")
        await asyncio.sleep(0.4)
        note_box = await tab.js(
            "(() => { const n = document.querySelector('#annot-popup-note');"
            " return { hidden: n.hidden,"
            "   empty: document.querySelector('#annot-popup-note-input').value === '' }; })()"
        )
        check(
            "点「写想法」弹出空输入框",
            note_box["hidden"] is False and note_box["empty"] is True,
            note_box,
        )

        # The box is five lines high, and grows when the thought needs
        # more room.
        rows = await tab.js("document.querySelector('#annot-popup-note-input').rows")
        check("输入框一开始是 5 行", rows == 5, rows)
        grown = await tab.js(
            "(() => { const i = document.querySelector('#annot-popup-note-input');"
            " const before = i.clientHeight;"
            " i.value = Array.from({length: 12}, (unused, k) => 'line ' + k).join('\\n');"
            " i.dispatchEvent(new Event('input'));"
            " return { before: before, after: i.clientHeight }; })()"
        )
        check("note 长了输入框会自己变高", grown["after"] > grown["before"] + 40, grown)
        await tab.js(
            "(() => { const i = document.querySelector('#annot-popup-note-input');"
            " i.value = ''; i.dispatchEvent(new Event('input')); })()"
        )

        # Deleting a highlight.
        await tab.js("document.querySelectorAll('.annot-del')[1].click()")
        await asyncio.sleep(0.8)
        await tab.js("document.querySelector('[data-confirm]').click()")
        await asyncio.sleep(2)
        left = await tab.js(
            f"fetch('/api/papers/{text_paper['id']}').then(r => r.json())"
            ".then(p => p.annotations.length)"
        )
        check("标注被删掉了", left == 1, left)
        check(
            "PDF 上的框也没了",
            not (await tab.js("!!document.querySelector('.pdf-highlight.green.area')")),
        )

        # --------------------------------------- selecting with the mouse
        # The real thing: drag the mouse over the text. The click that ends
        # such a drag must not take the bar away again.
        await tab.js("document.querySelector('#frame-toggle').click()")
        await asyncio.sleep(0.4)
        span_box = await tab.js(
            "(() => { const s = document.querySelector('.pdf-page .textLayer span');"
            " const r = s.getBoundingClientRect();"
            " return {x: r.left, y: r.top, w: r.width, h: r.height}; })()"
        )
        line_y = span_box["y"] + span_box["h"] / 2
        await tab.send(
            "Input.dispatchMouseEvent",
            {
                "type": "mousePressed",
                "x": span_box["x"] + 1,
                "y": line_y,
                "button": "left",
                "buttons": 1,
                "clickCount": 1,
            },
        )
        for step in range(1, 7):
            await tab.send(
                "Input.dispatchMouseEvent",
                {
                    "type": "mouseMoved",
                    "x": span_box["x"] + (span_box["w"] - 2) * step / 6,
                    "y": line_y,
                    "button": "left",
                    "buttons": 1,
                },
            )
            await asyncio.sleep(0.05)
        await tab.send(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseReleased",
                "x": span_box["x"] + span_box["w"] - 1,
                "y": line_y,
                "button": "left",
                "buttons": 0,
                "clickCount": 1,
            },
        )
        await asyncio.sleep(0.8)
        picked = await tab.js("getSelection().toString()")
        check("鼠标拖选选中了文字", "Hello" in picked, picked)
        check(
            "鼠标拖选后工具条出现了",
            not (await tab.js("document.querySelector('#sel-bar').hidden")),
        )

        # The × in the popup throws the highlight away.
        await tab.js("getSelection().removeAllRanges()")
        await click_highlight(tab, ".pdf-highlight.blue")
        await asyncio.sleep(0.8)
        check(
            "小窗又打开了",
            not (await tab.js("document.querySelector('#annot-popup').hidden")),
        )
        await tab.js("document.querySelector('#annot-popup-x').click()")
        await asyncio.sleep(2)
        check(
            "删高亮没有弹确认框",
            not (await tab.js("!!document.querySelector('[data-confirm]')")),
        )
        left = await tab.js(
            f"fetch('/api/papers/{text_paper['id']}').then(r => r.json())"
            ".then(p => p.annotations.length)"
        )
        check("小窗里的 × 把标注删掉了", left == 0, left)
        check(
            "PDF 上的高亮也没了",
            not (await tab.js("!!document.querySelector('.pdf-highlight')")),
        )

        check("页面没有报错", not tab.errors, "; ".join(tab.errors[:3]))

    # ------------------------------- the catalog and the search
    outline_paper = upload_pdf(
        ctx.url, ctx.root, "outline.pdf", "outline", data=OUTLINE_PDF_BYTES, title="有目录的文献"
    )
    async with Browser(ctx.url) as tab:
        check = ctx.check
        await tab.send("Page.navigate", {"url": f"{ctx.url}/paper/{outline_paper['id']}"})
        await asyncio.sleep(3)

        # The catalog opens on the left.
        await tab.js("document.querySelector('#toggle-left').click()")
        await asyncio.sleep(1.5)
        check(
            "左边出现了目录抽屉",
            await tab.js(
                "document.querySelector('.reader').classList.contains('left-open')"
            )
            is True,
        )
        titles = await tab.js(
            "[...document.querySelectorAll('.outline-item')].map(a => a.textContent.trim())"
        )
        check("目录里有 Introduction 和 Method", titles == ["Introduction", "Method"], titles)

        # Clicking an entry jumps to its page.
        await tab.js(
            "(() => { const item = [...document.querySelectorAll('.outline-item')]"
            ".find(a => a.textContent.trim() === 'Method'); item.click(); })()"
        )
        await asyncio.sleep(2)
        page_value = await tab.js("document.querySelector('#pdf-page-input').value")
        check("点「Method」跳到第 2 页", page_value == "2", page_value)

        # The search finds the text and marks where it is.
        await tab.js("document.querySelector('#pdf-find-btn').click()")
        await asyncio.sleep(0.5)
        check("查找框出现了", not (await tab.js("document.querySelector('#find-bar').hidden")))
        await tab.js(
            "(() => { const i = document.querySelector('#find-input');"
            " i.value = 'Introduction'; i.dispatchEvent(new Event('input')); })()"
        )
        await asyncio.sleep(2.5)
        count = await tab.js("document.querySelector('#find-count').textContent.trim()")
        check("找到一处", count == "1 / 1", count)
        check(
            "PDF 上画出了查找的命中",
            bool(await tab.js("!!document.querySelector('.pdf-find')")),
        )

        # Escape puts it all away.
        await tab.js(
            "document.body.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))"
        )
        await asyncio.sleep(0.8)
        check("按 Esc 查找框关了", await tab.js("document.querySelector('#find-bar').hidden"))
        check(
            "命中被擦掉了",
            not (await tab.js("!!document.querySelector('.pdf-find')")),
        )

        check("页面没有报错", not tab.errors, "; ".join(tab.errors[:3]))

    # ------------------------------- one colour for the whole highlight
    multi_paper = upload_pdf(
        ctx.url, ctx.root, "multi.pdf", "multi", data=MULTILINE_PDF_BYTES, title="多行文献"
    )
    async with Browser(ctx.url) as tab:
        check = ctx.check
        await tab.send("Page.navigate", {"url": f"{ctx.url}/paper/{multi_paper['id']}"})
        await asyncio.sleep(3)

        # Drag over the three lines, the way a reader does.
        spots = await tab.js(
            "(() => { const spans = [...document.querySelectorAll('.pdf-page .textLayer span')];"
            " const a = spans[0].getBoundingClientRect(),"
            "       b = spans[spans.length - 1].getBoundingClientRect();"
            " return {x1: a.left + 2, y1: a.top + a.height / 2,"
            "         x2: b.right - 2, y2: b.top + b.height / 2}; })()"
        )
        await tab.send(
            "Input.dispatchMouseEvent",
            {
                "type": "mousePressed",
                "x": spots["x1"],
                "y": spots["y1"],
                "button": "left",
                "buttons": 1,
                "clickCount": 1,
            },
        )
        for step in range(1, 7):
            await tab.send(
                "Input.dispatchMouseEvent",
                {
                    "type": "mouseMoved",
                    "x": spots["x1"] + (spots["x2"] - spots["x1"]) * step / 6,
                    "y": spots["y1"] + (spots["y2"] - spots["y1"]) * step / 6,
                    "button": "left",
                    "buttons": 1,
                },
            )
            await asyncio.sleep(0.05)
        await tab.send(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseReleased",
                "x": spots["x2"],
                "y": spots["y2"],
                "button": "left",
                "buttons": 0,
                "clickCount": 1,
            },
        )
        await asyncio.sleep(1)
        await tab.js("document.querySelector('#sel-bar .sel-dot.yellow').click()")
        await asyncio.sleep(2)

        # The rectangles of the three lines lie on top of each other - the
        # box of a line reaches into the line above it.
        info = await tab.js(
            "(() => { const g = document.querySelector('.pdf-highlight-group');"
            " if (!g) return null;"
            " const boxes = [...g.querySelectorAll('.pdf-highlight')];"
            " const rs = boxes.map(b => b.getBoundingClientRect());"
            " let overlaps = 0;"
            " for (let i = 0; i < rs.length; i++)"
            "   for (let j = i + 1; j < rs.length; j++)"
            "     if (rs[i].left < rs[j].right && rs[i].right > rs[j].left"
            "         && rs[i].top < rs[j].bottom && rs[i].bottom > rs[j].top) overlaps++;"
            " return { boxes: boxes.length, overlaps,"
            "   oneGroup: boxes.every(b => b.parentElement === g),"
            "   groupOpacity: getComputedStyle(g).opacity,"
            "   boxColour: getComputedStyle(boxes[0]).backgroundColor }; })()"
        )
        check("三行的高亮画成了几块", (info or {}).get("boxes", 0) >= 3, info)
        check("这几块确实互相压着", (info or {}).get("overlaps", 0) >= 1, info)
        check("它们画在同一个组里", (info or {}).get("oneGroup") is True, info)
        # The group carries the transparency and the rectangles are opaque,
        # so a place where two of them lie does not come out darker.
        check(
            "整条高亮是一个颜色",
            (info or {}).get("oneGroup") is True
            and float((info or {}).get("groupOpacity", 1)) < 1
            and str((info or {}).get("boxColour", "")).startswith("rgb("),
            info,
        )

        # Clicking it puts a frame around the whole highlight: the smallest
        # box that holds every rectangle of it.
        await tab.js("getSelection().removeAllRanges()")
        await click_highlight(tab, ".pdf-highlight")
        await asyncio.sleep(0.8)
        check(
            "点高亮弹出了小窗",
            not (await tab.js("document.querySelector('#annot-popup').hidden")),
        )
        frame = await tab.js(
            "(() => { const p = document.querySelector('#annot-popup').getBoundingClientRect();"
            " const rs = [...document.querySelectorAll('.pdf-highlight')]"
            "   .map(b => b.getBoundingClientRect());"
            " const l = Math.min(...rs.map(r => r.left)), t = Math.min(...rs.map(r => r.top));"
            " const r = Math.max(...rs.map(r => r.right)), b = Math.max(...rs.map(r => r.bottom));"
            " const s = getComputedStyle(document.querySelector('.annot-popup-frame'));"
            " return { dLeft: p.left - l, dTop: p.top - t,"
            "   dRight: r - p.right, dBottom: b - p.bottom,"
            "   border: s.borderTopWidth + ' ' + s.borderTopStyle + ' ' + s.borderTopColor }; })()"
        )
        check(
            "虚线框正好框住整条高亮",
            abs(frame["dLeft"]) < 2
            and abs(frame["dTop"]) < 2
            and abs(frame["dRight"]) < 2
            and abs(frame["dBottom"]) < 2,
            frame,
        )
        check(
            "虚线框是 2px 的虚线，颜色和高亮一样",
            frame["border"] == "2px dashed rgb(255, 255, 0)",
            frame,
        )

        check("页面没有报错", not tab.errors, "; ".join(tab.errors[:3]))
