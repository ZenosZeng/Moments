# Moments 静态前端

此目录包含独立的网站源码、离线城市定位和产物审计，可作为个人站点仓库的前端来源。不包含照片标注服务；个人 JSON 与 WebP 放在被忽略的 public/data/ 和 public/media/。

在 Moments 根目录执行 pixi run release，可导入本地公开数据并构建完整网站。只开发静态前端时：

```powershell
pixi run npm --prefix apps/public-ui ci
pixi run npm --prefix apps/public-ui run import-data
pixi run npm --prefix apps/public-ui run dev
```

导入要求已生成 exports/public-data/；可以先运行 pixi run test，使用空的合成演示数据，不需要真实照片。dev 地址为 http://127.0.0.1:5174。

独立构建、检查：

```powershell
pixi run npm --prefix apps/public-ui run build -- --base /moments-Zenos/
pixi run npm --prefix apps/public-ui run audit
```

GitHub Release 附件与 Pages 部署流程另行配置，当前没有会自动发布的 workflow。绝不要将本地数据库、私密配置或真实照片目录复制到前端发布实例。
