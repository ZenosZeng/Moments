<p align="center">
  <img src="docs/assets/readme-cover.png" alt="Moments · 方舟旅迹：照片、地图与时间线，旅行风景照片拼贴封面" width="100%">
</p>

# Moments · 方舟旅迹

方舟旅迹（Moments）是一套本地照片标注与旅行足迹展示工具。按每天的照片数量回看生活，记录城市和地点，挑选照片，再生成独立的旅行地图与时间线网站。

## 功能

- 每月每日照片数量图表，只统计具有拍摄日期的照片，不使用文件时间补齐。
- 照片标注、记录列表、实时旅行预览；支持默认城市及精选照片。
- 索引与旅行预览增量缓存，三个后台任务显示进度、缓存命中和待更新数量。
- 城市级世界地图、年份和城市筛选、旅行时间线与照片画廊。
- 增量导出 WebP 和缩略图，纠正方向，删除 EXIF/GPS 及私密字段。
- Python + SQLite 本地服务，Vue + TypeScript + Vite 前端；地图无需 API Key。

## 快速开始

目前提供 Windows + [Pixi](https://pixi.sh/) 环境。

```powershell
git clone https://github.com/ZenosZeng/Moments.git
cd Moments
pixi install
Copy-Item config/local.example.yaml config/local.yaml
# 首次使用：填写 config/local.yaml 中的原图目录，然后启动
pixi run app
```

打开 `http://127.0.0.1:8765`，刷新照片索引，然后开始标注。原图目录需要包含 `YYYYMM_名称` 格式的月份子目录，例如 `202405_a`；支持 JPG、JPEG、HEIC、PNG，当前不统计视频。

只需配置一次 `config/local.yaml`，之后始终使用 `pixi run app` / `pixi run release`。照片源、服务地址与端口、数据库与缓存路径、导出目录、网站基础路径都在该 YAML 文件中；本机配置不进入 Git。

支持多个原图目录：在 `photos.sources` 列表中增加照片源，每个源设置唯一且固定的 `id`，用 `path` 指定目录，或用 `parent` + `prefix` 自动匹配会改名的目录。所有来源按拍摄日期汇总，同名文件不会覆盖。已有源的 ID 不要改，顺序可以改。详见 [使用指南](user_guide.md)。

城市默认空白，可在界面设置中选择已有城市作为缺省值；城市、地点均选填。

## 三个任务

| 命令 | 用途 |
| --- | --- |
| `pixi run app` | 构建并启动本地标注工具 |
| `pixi run test` | 运行全部测试、构建和公开产物审计，不依赖个人数据库 |
| `pixi run release` | 在本地生成公开数据与静态网站，不上传、不推送、不部署 |

```powershell
pixi run release
```

默认输出到 `data/exports/`：`public-data/`、`public-data.zip`、`.sha256` 校验文件、`site/` 和 `site.zip`，均不进入 Git。网站路径默认 `/Moments/`，在配置的 `publish.base_path` 中调整。

## 代码与数据

```text
src/pic_timeline/       照片分析、本地服务、数据库与脱敏导出
apps/local-ui/         标注、记录列表、实时预览
apps/public-ui/        完整静态网站源码、城市定位及审计
tests/                 本地工具测试
scripts/               app / test / release 统一入口
config/                公开示例配置；local.yaml 私密且忽略
data/db/               标注与多源照片索引，Git 忽略
data/cache/            本地缩略图，Git 忽略
data/exports/          脱敏导出、增量图片缓存和网站，Git 忽略
data/backups/          本地数据库快照，Git 忽略
_archive/              旧仓库私密 ZIP 归档，Git 忽略
```

`Moments` 是唯一的通用源码仓库，同时承载 Pages 工作流，不需要第二个站点仓库。公开前端的 `demo/` 仅包含空的合成数据；克隆源码不会下载任何个人照片。

## 发布网站

1. 在本地界面点击 **导出公开产物**，下载 ZIP 和校验文件；也可执行 `pixi run release`，同时构建本地静态网站。检查公开记录及精选照片。
2. 手动将 `public-data.zip` 和 `.sha256` 上传到本仓库的一个 `data-*` Release。
3. 在 Actions 中手动运行 **Publish Moments Pages**，填写该 Release 标签。

工作流只构建静态前端，校验、导入和审计所选附件后部署。代码 push、创建 Release、本地保存标注都不会自动发布。预期地址为 `https://zenoszeng.github.io/Moments/`，实际地址以部署结果为准。

## 隐私边界

原图只读，不修改、不复制原图、不上传。数据库、原图路径配置、照片缓存及个人导出全部忽略；公开导出只包含允许公开的记录与精选图，不包含同行人或昵称字段。

旧版本升级会清理数据库中的同行人表，保留其他标注和精选照片；旧数据包须重新导出。已发布网页、附件、备份及 Git 历史不会被本地升级自动删除。

**忽略文件不等于删除历史。** 旧标注须迁入被忽略的 `data/`，旧 Git 历史只能作为私密 ZIP 放入 `_archive/`，不能合并进 Moments 历史。应用和导出不再引用旧仓库；备份也不能上传到 public Release。

GitHub Release 附件可以保存公开数据包而不进入 Git 历史，但 public 仓库的附件仍公开可下载。上传数据、部署 Pages 都需要单独决定；本地 `release` 命令不执行这些操作。

详见 [使用指南](user_guide.md)、[发布说明](docs/publishing.md) 和 [迁移说明](docs/migration.md)。

## 贡献

欢迎提交 Issue 和 Pull Request。修改后运行 `pixi run test`；不要提交个人数据库、照片、配置或真实旅行数据。提交采用 Conventional Commits，例如 `feat: 增加照片筛选`。

## 许可

源码采用 [MIT License](LICENSE)。个人照片、旅行记录和第三方地图数据不属于该源码许可的授权范围；GeoNames 数据保留来源说明。
