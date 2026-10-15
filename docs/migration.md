# 仓库迁移

## 仓库分工

- `ZenosZeng/Moments`：public，全部通用源码，全新 Git 历史，不包含个人数据。
- `ZenosZeng/moment-studio`：已归档，保持 private；保留旧标注备份与历史，README 指向 Moments。
- `ZenosZeng/moment-trails-public`：已归档，保持 public；保留旧站点与历史，README 指向 Moments。

不再新建 `moments-Zenos`。源码和 Pages 工作流统一在 Moments，公开数据放在它的 Release 附件中。

归档不是删除，不会移除历史里的数据库和照片，也不保证旧 Pages 立即停止。旧私有仓库不可直接改为 public。

## 本地数据独立存放

Moments 不再使用旧仓库数据库或前端。先配置 `config/local.yaml` 的照片源，运行时数据统一位于 [data 目录](../data/README.md)。原图仍保留在仓库外，只读访问。

已经完成本地迁移的电脑直接执行 `pixi run app`；增加新手机目录后点击刷新索引，旧精选引用不变。`pixi run release` 从本仓库数据库读取标注，不需要指向旧路径。

其他旧版本用户需迁移时，先关闭新旧程序并完成本机配置；给旧照片源添加 `legacy_paths: true`（最多一个），新源保持默认 `false`。该标记和源 ID 都不要再改，确保将来重建索引时旧精选仍能对应。仅对空的目标数据目录运行一次：

```powershell
pixi run python scripts/migrate_legacy_data.py --studio '../moment-studio' --public '../moment-trails-public' --legacy-source old-phone
```

`old-phone` 换成配置中旧照片源的固定 ID。该一次性脚本：

- 使用 SQLite backup API 复制一致性快照，校验表内容、外键与精选原图引用；不覆盖既有目标。
- 将标注和索引迁入 `data/db/`，修正改名后的原图路径，删除已退役的同行人表；保留其他字段、界面设置和精选引用。
- 将本地缩略图迁入 `data/cache/thumbnails/`，有效且无 EXIF/XMP 的 WebP 迁入 `data/exports/public-data/media/`，以后继续增量复用。
- 不迁入旧公开 JSON、旧网站构建或临时导出，避免复用包含同行人的数据；下一次 release 重新生成白名单 JSON。
- 将原始数据库及旧快照保存在 `data/backups/legacy-时间/`，记录校验报告；这些备份仍可能包含同行人，必须私密保管。
- 将两个旧仓库分别打包为 `_archive/仓库名-时间.zip`，包含隐藏的 `.git/`、代码及旧数据，生成 SHA-256 并完整校验 ZIP。排除可重装的 `.pixi/`、`node_modules/`、构建与临时目录、浏览器测试缓存。

脚本不启动应用、不运行导出、不上传任何内容，也不移动、删除旧目录或原图。旧目录保留作额外保险，但应用不再依赖它们。归档 ZIP 与迁移备份全部被 Git 忽略，不可上传到公开仓库或 Release。

## 个人网站的数据方案

旧方式把 `public/data/*.json` 和 `public/media/*.webp` 提交到 Git。新方式：

1. Moments 本地导出并审计 `public-data.zip`，生成 SHA-256 校验文件。
2. 用户检查后，将两份附件手动上传到 Moments 的 `data-*` Release。
3. 仓库只跟踪完整通用源码和部署配置；手动触发 Pages 工作流下载指定版本附件。
4. 导入数据、构建并审计网站，再部署 Pages artifact。

工作流仅支持手动触发；本地 `release` 不上传数据、不部署。附件和最终页面仍公开；不进入 Git 历史不等于隐私保护。具体操作见 [发布说明](publishing.md)。

Moments 使用全新 Git 历史，不复制旧 `.git/` 或个人产物。旧站点中曾公开的照片仍存在于归档仓库历史中；如需撤下旧页面或处理历史数据，另行确认操作。
