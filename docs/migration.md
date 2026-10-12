# 仓库迁移

## 仓库分工

- `ZenosZeng/Moments`：public，全部通用源码，全新 Git 历史，不包含个人数据。
- `ZenosZeng/moment-studio`：已归档，保持 private；保留旧标注备份与历史，README 指向 Moments。
- `ZenosZeng/moment-trails-public`：已归档，保持 public；保留旧站点与历史，README 指向 Moments。

不再新建 `moments-Zenos`。源码和 Pages 工作流统一在 Moments，公开数据放在它的 Release 附件中。

归档不是删除，不会移除历史里的数据库和照片，也不保证旧 Pages 立即停止。旧私有仓库不可直接改为 public。

## 继续使用已有标注

旧目录和数据库不会自动迁移或修改。可在新项目中指定旧索引和标注数据库：

```powershell
pixi run app --source 'E:\Photos\archive' --index '..\moment-studio\data\photo_index.sqlite3' --annotations '..\moment-studio\data\annotations.sqlite3'
pixi run release --index '..\moment-studio\data\photo_index.sqlite3' --annotations '..\moment-studio\data\annotations.sqlite3'
```

把照片示例路径替换成自己的路径。第一次刷新索引可能需要重新扫描，标注仍沿用旧文件。操作前关闭旧程序并备份数据库，避免两个服务同时写入。

如需迁移到新项目的 `data/`，关闭程序后自行复制数据库，新目录数据仍被 Git 忽略。不要复制 `.git/`。

## 个人网站的数据方案

旧方式把 `public/data/*.json` 和 `public/media/*.webp` 提交到 Git。新方式：

1. Moments 本地导出并审计 `public-data.zip`，生成 SHA-256 校验文件。
2. 用户检查后，将两份附件手动上传到 Moments 的 `data-*` Release。
3. 仓库只跟踪完整通用源码和部署配置；手动触发 Pages 工作流下载指定版本附件。
4. 导入数据、构建并审计网站，再部署 Pages artifact。

工作流仅支持手动触发；本地 `release` 不上传数据、不部署。附件和最终页面仍公开；不进入 Git 历史不等于隐私保护。具体操作见 [发布说明](publishing.md)。

Moments 使用全新 Git 历史，不复制旧 `.git/` 或个人产物。旧站点中曾公开的照片仍存在于归档仓库历史中；如需撤下旧页面或处理历史数据，另行确认操作。
