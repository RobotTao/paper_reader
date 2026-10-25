# Paper Reader — AI 准则 / AI working rules

本项目是一个本地部署的 readpaper 克隆：FastAPI + SQLite 后端，原生 ES module 前端，
依赖用 uv 管理，PDF 用 pdf.js 渲染。

## 准则一：`local_data/` 是用户的数据，未经确认不得改动

`local_data/` 目录里装的是用户自己的文献库，是这个项目唯一不可再生的资产：

```
local_data/
├── data.json   # readpaper 导出的原始数据（只读来源）
├── pdfs/       # 唯一的 PDF 库（可写）：导入的在 pdfs/<id>/，上传的在 pdfs/ 根下
└── db/
    └── library.db  # SQLite：文献、标签、分类、标注、已读状态、垃圾箱(trash)
```

一篇文献的 PDF 只存一份，分类是虚拟的（`paper_folders` 多对多表），
所以删掉一个分类可能连带影响只属于它的文献。

**删除走垃圾箱，不直接删文件**：删除文献（或删掉只属于它的分类）时，
文献的元数据整体移入 `trash` 表，`papers` 行被删除，**PDF 文件仍留在 `local_data/pdfs/`**。
只有「彻底删除 / 清空垃圾箱」才会真正从磁盘删掉 PDF；「恢复」会把文献放回「未分类」列表
（分类归属不恢复，因为分类可能已被删除）。

**任何会写入或删除 `local_data/` 里面数据的操作，都必须先让用户手动确认。**
包括但不限于：

- 直接用 SQL 改 `library.db`（`UPDATE` / `DELETE` / `INSERT`）
- 跑 `make import-reset`，或者 `import_readpaper(..., reset=True)`
- 删改 `local_data/pdfs/` 里的文件
- 调 `drop_from_trash()` 之类的接口真正删掉 PDF 文件
- 改代码里的迁移逻辑，导致 `init_db()` / 导入流程去改写已有数据
  （例如新增列时带 `UPDATE ... ` 回填）

### 确认时必须说明三件事

在动手之前，先把下面这些讲清楚，然后等用户明确回复确认：

1. **改动范围** —— 具体改什么：哪些文件、哪些表、哪些行（给出条数/ID 范围），
   会影响哪些字段。
2. **影响** —— 用户能感知到什么变化：哪几篇文献的标题/备注/标签/已读状态会变，
   导入的 PDF 路径会不会失效，统计数字会怎么变。
3. **能否恢复** —— 明确说清楚恢复方式：
   - 有备份（`make backup` 生成的 tar 包 / 用户自己的备份）→ 说清用哪一份、怎么还原。
   - 没有备份 → 直接说**不可恢复**，并说明这是不可逆操作。
   - 只是加列 / 加索引，不改动已有行的值 → 说明这类改动是可逆的（把文件恢复即可）。

### 替代做法

如果只是为了验证代码，**不要**动 `local_data/`：

- **先把 `local_data/` 整体拷一份到临时目录**，用副本跑服务做浏览器/接口验证：
  `cp -R local_data /tmp/testdb && cd backend && DATA_DIR=/tmp/testdb/db PDF_ROOT=/tmp/testdb ./.venv/bin/uvicorn app.main:app --port 8099`
  （用备用端口，别占用用户正在用的 8080。脚本点一下「已读」或打开阅读页都会写库，
  所以脚本连的必须是副本实例。）
- 用临时目录跑：`DATA_DIR=/tmp/test/db PDF_ROOT=/tmp/test uv run python -m app.cli import ...`
- 用 `DATA_DIR` / `PDF_ROOT` 环境变量把数据指向别处（见 `backend/app/config.py`）
- 只读的检查（`SELECT`、`SELECT COUNT(*)`）不需要确认

## 准则二：其它

- 改动后跑 `cd backend && uv run ruff check .`（lint）；连同 `tests/` 一起检查用 `make lint`。
- 验证功能优先跑自动化测试，它们都在临时数据上跑，不会碰 `local_data/`：
  - `make test` —— 后端（pytest），秒级
  - `make test-e2e` —— 浏览器（真实 Chrome，需要 `--remote-debugging-port=9333`）
- 前端没有打包步骤，改完静态文件刷新页面即可；不要引入 Node 工具链。
- 用户说“写个 commit”时才提交，提交前先跑一遍验证。
