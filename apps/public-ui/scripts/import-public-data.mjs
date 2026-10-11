import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { cp, mkdir, mkdtemp, readdir, rename, rm, stat } from "node:fs/promises";
import path from "node:path";

import { auditPublicTree } from "./audit-public-tree.mjs";

const repositoryRoot = process.cwd();
const execFileAsync = promisify(execFile);
const sourceRoot = path.resolve(
  process.argv[2] || path.join(repositoryRoot, "..", "..", "exports", "public-data")
);
const publicRoot = path.join(repositoryRoot, "public");

for (const name of ["data", "media"]) {
  const info = await stat(path.join(sourceRoot, name)).catch(() => null);
  if (!info?.isDirectory()) {
    throw new Error(`公开数据包缺少 ${name}/：${sourceRoot}`);
  }
}

const dataEntries = await readdir(path.join(sourceRoot, "data"), { withFileTypes: true });
if (dataEntries.length !== 1 || !dataEntries[0].isFile() || dataEntries[0].name !== "trips.json") {
  throw new Error("公开数据包的 data/ 只能包含 trips.json");
}
const mediaEntries = await readdir(path.join(sourceRoot, "media"), { withFileTypes: true });
if (mediaEntries.some((entry) => !entry.isFile() || path.extname(entry.name).toLowerCase() !== ".webp")) {
  throw new Error("公开数据包的 media/ 只能包含 WebP 文件");
}

const stageRoot = await mkdtemp(path.join(repositoryRoot, ".public-import-"));
try {
  for (const name of ["data", "media"]) {
    await cp(path.join(sourceRoot, name), path.join(stageRoot, name), {
      recursive: true,
      errorOnExist: true
    });
  }
  const { stdout } = await execFileAsync(
    process.env.PYTHON || "python",
    [
      path.join(repositoryRoot, "scripts", "build_city_centers.py"),
      path.join(stageRoot, "data", "trips.json"),
      path.join(stageRoot, "data", "city-centers.json")
    ],
    {
      cwd: repositoryRoot,
      encoding: "utf8",
      env: { ...process.env, PYTHONIOENCODING: "utf-8" }
    }
  );
  process.stdout.write(stdout);
  await auditPublicTree(stageRoot);
  await mkdir(publicRoot, { recursive: true });
  for (const name of ["data", "media"]) {
    const target = path.join(publicRoot, name);
    await rm(target, { recursive: true, force: true });
    await rename(path.join(stageRoot, name), target);
  }
} finally {
  await rm(stageRoot, { recursive: true, force: true });
}

console.log(`已导入公开数据包：${sourceRoot}`);
