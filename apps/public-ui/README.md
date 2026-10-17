# Moments · 拾光录 静态前端

此目录包含完整的网站源码、离线城市定位和产物审计，属于 Moments 主仓库，不需要单独的前端仓库。不包含照片标注服务；个人 JSON 与 WebP 放在被忽略的 public/data/ 和 public/media/。

在 Moments 根目录执行 pixi run release，可导入本地公开数据并构建完整网站。只开发静态前端时：

```powershell
pixi run npm --prefix apps/public-ui ci
pixi run npm --prefix apps/public-ui run import-data
pixi run npm --prefix apps/public-ui run dev
```

导入默认读取主仓库的 data/exports/public-data/；修改了配置中的导出目录时通过 import-data 的参数指定新目录，或直接运行 pixi run release。可以先运行 pixi run test，使用空的合成演示数据，不需要真实照片。dev 地址为 http://127.0.0.1:5174。

独立构建、检查：

```powershell
pixi run npm --prefix apps/public-ui run build -- --base /Moments/
pixi run npm --prefix apps/public-ui run audit
```

主仓库的 Pages 工作流仅手动触发，读取指定 Release 的公开 ZIP 和校验文件；只构建此静态前端，不启动本地服务。详见 [发布说明](../../docs/publishing.md)。绝不要将本地数据库、私密配置或真实照片目录放入静态前端。
