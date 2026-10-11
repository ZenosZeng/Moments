# 仓库迁移

## 仓库分工

- `ZenosZeng/Moments`：public，全部通用源码，全新 Git 历史，不包含个人数据。
- `ZenosZeng/moment-studio`：保持 private，迁移成功后更新 README 并 archive；保留旧标注备份与历史。
- `moment-trails-public`：现有个人站点暂时不动；后续单独迁移为 `moments-Zenos`。

新仓库上传成功后再归档旧仓库。归档不是删除，也不会移除历史里的数据库。

## 继续使用已有标注

旧目录和数据库不会自动迁移或修改。可在新项目中指定旧索引和标注数据库：

```powershell
pixi run app --source 'E:\Photos\archive' --index '..\moment-studio\data\photo_index.sqlite3' --annotations '..\moment-studio\data\annotations.sqlite3'
pixi run release --index '..\moment-studio\data\photo_index.sqlite3' --annotations '..\moment-studio\data\annotations.sqlite3' --base /moments-Zenos/
```

把照片示例路径替换成自己的路径。第一次刷新索引可能需要重新扫描，标注仍沿用旧文件。操作前关闭旧程序并备份数据库，避免两个服务同时写入。

如需迁移到新项目的 `data/`，关闭程序后自行复制数据库，新目录数据仍被 Git 忽略。不要复制 `.git/`。

## 个人网站的数据方案

现有方式把 `public/data/*.json` 和 `public/media/*.webp` 提交到 Git。计划的新方式：

1. Moments 本地导出并审计 `public-data.zip`。
2. 经用户确认，将数据包上传到个人 public 仓库的 Release，使用明确版本标签。
3. 个人仓库只跟踪前端和部署配置；手动触发 Pages 工作流下载指定版本附件。
4. 导入数据、构建并审计网站，再部署 Pages artifact。

该流程尚未配置，本次主仓库迁移不上传数据、不部署。附件和最终页面仍公开；不进入 Git 历史不等于隐私保护。

直接将旧个人站点改名或添加 .gitignore 无法清除历史照片。需要干净代码历史时，应新建前端发布实例；旧网站退出与归档单独安排。
