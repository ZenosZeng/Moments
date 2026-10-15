# 发布与更新

## 边界

一个 Moments 仓库保存全部通用代码和 Pages 工作流。数据库、原图、缓存、公开 JSON、精选图片和构建产物不进入 Git；公开数据只作为 Release 附件。

**上传附件和运行 Pages 工作流都是真正的公开发布。** ZIP、照片、日期和地点均可被他人下载。不要上传 SQLite、私密备注、路径配置或原图；公开 ZIP 不是标注数据库备份。

本地界面的“导出公开产物”与 `pixi run release` 都只生成文件，不连接 GitHub、不上传、不部署。代码 push 和 Release 创建也不会触发部署。

## 1. 本地检查与导出

在本地工具中点击顶部 **导出公开产物**，查看进度；完成后可下载 ZIP 和 SHA-256，原文件位于 `data/exports/`。此按钮只生成数据附件，网站由 Pages Actions 构建，不必在本地再构建一次。

需要完整测试或同时构建本地静态网站时，在 Moments 根目录执行：

```powershell
pixi run test
pixi run release
```

本机参数统一从 `config/local.yaml` 读取；数据库和缓存位于 Moments 的 `data/` 内，导出不依赖旧仓库。首次配置及多照片源设置见 [使用指南](../user_guide.md)。

生成的附件及可选网站：

| 文件 | 用途 |
| --- | --- |
| `data/exports/public-data.zip` | 白名单 JSON、脱敏 WebP 和缩略图 |
| `data/exports/public-data.zip.sha256` | ZIP 的 SHA-256 校验和 |
| `data/exports/site/`、`data/exports/site.zip` | 仅命令行 release 生成的完整静态网站 |

公开记录需勾选允许公开且至少有一张精选照片。导出会复用缓存、纠正方向、缩放并删除 EXIF/GPS/XMP；ZIP 不包含缓存标记或本地数据库。上传前自行检查记录、地点和精选照片。单个 ZIP 小于 2 GiB。

界面导出基于数据库快照；期间保存标注或更新索引后会提示重新导出。图片增量缓存不会跳过隐私审计、完整打包与校验。界面和命令行通过同一个本地锁防止同时导出。

同行人功能已移除，公开 JSON、ZIP 和最终产物均拒绝同行人及昵称字段。旧数据版本须重新导出后才能部署；旧附件或旧 Pages 中的信息不会因此自动删除。照片画面和自由填写的地点文字仍需人工确认是否适合公开。

默认静态路径为 `/Moments/`；其他仓库在配置的 `publish:` 下设置 `base_path: "/仓库名/"`，根域名使用 `"/"`。Actions 部署时会自动使用 Pages 配置的路径。

## 2. 手动上传公开附件

确认要公开后，在 GitHub 的 Releases 页面创建 `data-*` 标签的 Release，例如 `data-2026-10-12`，只附加 ZIP 和校验文件。每次更新使用新标签，便于回退；不要替换旧版本。

已安装并登录 GitHub CLI 时也可运行以下命令。它会立即上传到 public 仓库，不是预览命令：

```powershell
$repo = 'ZenosZeng/Moments'
$tag = 'data-2026-10-12'
gh release create $tag data/exports/public-data.zip data/exports/public-data.zip.sha256 --repo $repo --target main --title "公开数据 $tag" --notes '经检查的公开记录与脱敏精选照片。' --latest=false
```

没有把 `gh` 加入 PATH 时，可用实际安装路径代替 `gh`。两份附件必须同属一个已经发布、非草稿的 Release。附件仍是完整公开快照；增量缓存只加快本地图片生成，不是拆分上传。

## 3. 手动部署 Pages

代码和 `.github/workflows/pages.yml` 需先提交到远端默认分支。

1. 首次在仓库 **Settings → Pages → Source** 选择 **GitHub Actions**。
2. 打开 **Actions → Publish Moments Pages → Run workflow**。
3. 选择 `main`，在 `data_tag` 中填写刚上传的完整标签，确认运行。
4. 工作流成功后，从 `github-pages` 环境或部署任务打开页面。

也可在确认部署时手动执行：

```powershell
gh workflow run pages.yml --repo $repo --ref main -f "data_tag=$tag"
```

工作流下载所选 ZIP，校验 SHA-256，白名单安全解压，审计 JSON/图片，离线生成城市中心，然后只测试、构建和审计公开前端。最终仅上传 `apps/public-ui/dist`；数据库、本地服务和完整仓库不会成为 Pages 内容。

Python 和 Node 使用独立的 Linux CI Pixi 环境；本地仍保留 `app`、`test`、`release` 三个任务。地图无需 API Key。工作流的临时 GitHub Token 只用于下载本仓库附件，不进入网站。

本仓库预期地址为 `https://zenoszeng.github.io/Moments/`，实际以 GitHub 显示的地址为准。没有运行工作流不代表网站已经发布。

## 4. 更新、回退与备份

保存标注后重新导出，检查数据，创建新的 `data-*` Release，再手动部署该标签。只修改代码时，也须手动选择已有数据版本重新部署。

回退时重新运行工作流，选择一个仍保留附件的旧标签。删除附件不会自动删除已经部署的网站或浏览器缓存；撤下 Pages 是独立操作。

数据库和原图继续在本地单独备份。不要为方便备份把它们加入 public 仓库，也不要依赖 `.gitignore` 清除旧 Git 历史。源码 MIT 许可不授予他人使用你的个人照片和旅行记录的权利。
