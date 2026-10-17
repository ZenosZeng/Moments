# 本地数据目录

此目录只有本说明与 `.gitkeep` 进入 Git，其他内容全部忽略。默认结构：

```text
data/
  db/
    annotations.sqlite3      城市、地点、公开设置、精选引用、界面设置
    photo_index.sqlite3      所有照片源的拍摄日期索引和本机路径
  cache/
    thumbnails/              本地缩略图和大图，可重建
      _previews/             按日期持久化的旅行预览 JSON 缓存，私密
  exports/
    public-data/             脱敏 JSON + WebP；media 同时作为增量缓存
    public-data.zip          公开数据附件
    public-data.zip.sha256   附件校验和
    site/                    命令行 release 生成的静态网站
    site.zip                 命令行 release 生成的网站打包文件
  backups/                   旧数据库快照及迁移报告，私密
  compositions/              本地图文组，不参与公开导出
    <日期_城市_标题>/group.json       图文信息、日期城市快照、图片顺序和滤镜
    <日期_城市_标题>/文案.txt         可直接复制的文案标题和正文
    <日期_城市_标题>/base/            去元数据的调色底图（非原图文件）
    <日期_城市_标题>/images/          顺序号_拍摄日期_v保存版本.jpg 成品
    <日期_城市_标题>/agent-request.md 可选的本地文案任务，不调用模型
    .trash/                 被删除图文组，可恢复
```

原图保持在仓库外，不会被复制进此目录；图文组只保存重编码、去元数据的派生图。一个数据库支持多个照片源；固定源 ID 区分同名照片，并且与目录顺序、目录后缀无关。

关闭应用后备份 `db/annotations.sqlite3` 和 `config/local.yaml`；原图必须另外备份。索引、缩略图和公开产物可重建。旧备份可能仍包含已经移除的同行人信息，不可公开上传。

图文管理还需单独备份整个 `compositions/`，只备份SQLite不会包含图文组、文案或调色结果。清单规范与Agent写入约定见 [图文组说明](../docs/compositions.md)。

每组首次保存用“日期_城市_标题”命名，重名加数字后缀；不使用hash，后续标题或日期修改不重命名。旧hash目录下次保存时转换，不批量修改。图文管理顶部显示实际完整目录并支持复制，尚未首次保存时显示“尚未保存”。从`images/`按文件名选图，从`文案.txt`复制文案；文本由清单生成，不直接编辑。

`../_archive/` 保存旧仓库的私密 ZIP（含旧 Git 历史和数据），也被 Git 忽略。`pixi run release` 不会把备份、配置或这些 ZIP 放入发布附件。

界面的“导出公开产物”只生成公开数据包及校验和；Pages Actions 负责构建网站。导出过程在 `exports/.private-export-*/` 创建短期数据库快照，任务结束自动清理；`.local-export.lock` 用于阻止并发导出。这些文件和全部缓存均不能上传，只上传经检查的 `public-data.zip` 与 `public-data.zip.sha256`。
