# ADR 0022 — 桌面端数据目录分离 + 本地存储选型（JSON vs SQLite）

- 日期：2026-10-30
- 状态：已采纳
- 相关：用户反馈「重启之后配置/用量/会话全丢」；`src/core/data_dir.py`、`providers_store.py`、`projects_store.py`、`usage_store.py`

## 背景（实测）

桌面端把数据写在**安装目录下**的 `.clawd/`：

- Electron 每次升级/重装会替换 `resources/`，用户数据跟着没了 —— 表现就是"配好的 provider、看过的用量、
  聊过的会话，重启一次全空"；
- 而 CLI 模式一直用"工作目录下的 `.clawd/`"，两边语义混在一起，谁也说不清数据到底在哪。

同时，provider 配置存在 SQLite 的 `providers` 表里：改一条要写 SQL，用户想手改、想备份、想看一眼都不敢动。

## 决策

1. **数据目录唯一入口 `src/core/data_dir.py`**：
   - 有 `CLAWD_DATA_DIR` 环境变量 → 用它（Electron 启动 Host 时注入 `app.getPath('userData')/data`）；
   - 否则 `<workdir>/.clawd`（CLI / 服务端模式）。
   - **禁止**任何新代码再拼 `Path.cwd() / '.clawd'` —— `/api/sessions` 曾因此永远返回空
     （引擎写到 userData，端点读 cwd）。
2. **存储按访问模式选型，不搞"统一数据库"**：

   | 数据 | 形态 | 理由 |
   |:---|:---|:---|
   | `usage`（每轮一行，面板要按小时/模型/调用方聚合） | SQLite 表 | 高频聚合查询，需要索引 |
   | `providers.json` / `projects.json` | JSON 文件 | 低频、少量、**用户可手改可备份**，改坏能肉眼修 |
   | `sessions/*.json` | JSON 文件（一会话一文件） | 归档属性，单条损坏不影响其他 |
   | `uploads/` | 原始文件 | 二进制大对象不进库 |

3. **写入原子化**：JSON 一律"写临时文件 → `os.replace`"，避免半截文件；SQLite 开 WAL。
4. **密钥只进不出**：`providers.json` 里的 key 对外接口只返回掩码（`sk-ab…1234`）或环境变量名；
   表单里密钥留空 = 保留原值（不是"清空"）。
5. **一次性迁移**：桌面端首次启动把旧 `<安装目录>/.clawd` 拷到新的 userData/data（`migrateLegacyData()`），
   只做一次且不删旧数据。
6. **会话带 `workdir`**：落盘时写入 `metadata.workdir`，侧栏据此按项目分组
   （没有它就只能把所有会话平铺成一列，用户分不清哪个项目）。

## 代价

- **实际目录名是 `%APPDATA%\clawd-desktop`**（Electron 的 `userData` 取 `package.json` 的
  `name`，**不是** `productName` "Clawd Desktop"）。排障、写 E2E 断言、写文档时都要用这个名字 ——
  按产品名猜目录会让"附件落盘数 = 0"这类检查得到假阴性（真实踩过）。
- 两套路径存在（env 注入 vs 默认 `.clawd`），**测试必须显式设 `CLAWD_DATA_DIR`**，
  否则会往真实目录写脏数据（已有教训：37 个会话里 17 个是 MagicMock）。
- JSON 没有事务与并发保护：只适合"单进程、低频写"的配置类数据，写之前必须整份读。
- 迁移只做一次，若用户在迁移后又手动改回旧目录，新代码不会再迁（可接受，README 已说明位置）。

## 边界（不要越界使用本 ADR）

- 不要把 `usage` 也改回 JSON：柱状图/按模型聚合会退化成全量扫描。
- 不要把 provider/projects 塞回 SQLite：用户要能手改、能复制给同事。
- 不要为"统一"造一个存储抽象层：两种形态的差异（事务/索引 vs 可读性）是真实需求，抽象只会把差异藏起来。
