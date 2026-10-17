<p align="center">
  <img src="docs/assets/readme-cover.png" alt="Moments · 拾光集：照片、地图与时间线" width="100%">
</p>

# Moments · 拾光集

本地整理照片、标注城市与地点、挑选精选，再用地图和时间线回看旅行，也可以制作调色图文组。

[功能案例（PDF）](docs/Moments_拾光集_功能案例.pdf)

- 按日统计照片，支持多个照片源、增量索引和任务进度。
- 按日期标注与精选，浏览城市地图、旅行时间线和照片画廊。
- 本地保存数据，按需导出脱敏图片和公开记录，手动发布 GitHub Pages。

## 当前版本

最新版本：**v0.2.0** · 当前功能版本：**v0.2.0**。

**v0.2.0 主要功能**

- 跨日期图文组、拖拽排序、九宫格滤镜、逐图强度与大图调色。
- 可读目录与顺序图片命名、独立文案，以及 Agent 文案任务交接。
- 图文组计划发布日期：自动顺延避开已排期日期，也可手动指定；基本信息、图片、滤镜和文案分区。

完整变更见 [版本记录](docs/changelog.md)；补丁版保留当前功能版本的特性摘要。

## 快速开始

目前支持 Windows，需要 Git 和 [Pixi](https://pixi.sh/)。

```powershell
git clone https://github.com/ZenosZeng/Moments.git
cd Moments
pixi install
Copy-Item config/local.example.yaml config/local.yaml
```

编辑 `config/local.yaml`，在 `photos.sources` 中填写原图目录，然后启动：

```powershell
pixi run app
```

打开 `http://127.0.0.1:8765`。照片源需包含 `YYYYMM_名称` 格式的月份子目录，如 `202405_a`；支持 JPG、JPEG、HEIC、PNG，暂不统计视频。多目录及配置说明见 [使用指南](user_guide.md)。

## 日常使用

在 App 内完成：**更新照片索引 → 按日期标注与精选 → 生成旅行预览**。图文管理可将精选另存为图文组，不影响原标注。

需要分享网站时，再点击 **导出公开产物**，取得 `public-data.zip` 和 `public-data.zip.sha256`，默认保存在 `data/exports/`。导出只写本地，不会上传或发布。

## 发布网站

1. 检查公开记录和精选照片，将 ZIP 与校验文件上传到一个 `data-*` Release。
2. 首次在仓库 **Settings → Pages → Source** 选择 **GitHub Actions**。
3. 手动运行 **Publish Moments Pages**，选择 `main` 并填写数据 Release 标签；代码改动须先经 PR 合入。

代码推送和创建 Release 不会自动部署。公开仓库的 Release 附件本身可被下载，上传前请确认内容；完整步骤见 [发布说明](docs/publishing.md)。

## 数据与隐私

原图只读，不修改或上传；标注、图文组、配置、缓存和导出保存在本地并被 Git 忽略。公开导出会纠正图片方向、压缩为 WebP，并移除 EXIF/GPS 和本机路径。

数据布局见 [data/README.md](data/README.md)，图文操作见 [图文组说明](docs/compositions.md)，旧版本升级见 [迁移说明](docs/migration.md)。

## 开发

Python + SQLite，Vue + TypeScript + Vite；离线地图无需 API Key。运行 `pixi run test` 完成测试、构建和公开产物审计。

`main` 为生产分支，改动通过独立分支和 PR 合入，提交采用中文 Conventional Commits；版本与协作规则见 [开发规范](docs/development.md)。

## 许可

[MIT License](LICENSE)。个人照片与旅行记录不属于源码授权；第三方地图数据遵循其原有许可。
