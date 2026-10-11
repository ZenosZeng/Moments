import { readFile, readdir, stat } from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

const textExtensions = new Set([".html", ".js", ".css", ".json", ".xml", ".txt", ".map"]);
const forbiddenExtensions = new Set([".sqlite", ".sqlite3", ".db", ".env", ".pem", ".key", ".heic"]);
const forbiddenKeys = new Set([
  "caption",
  "description",
  "itinerary",
  "latitude",
  "longitude",
  "note",
  "privateName",
  "publicDescription",
  "relativePath",
  "relative_path",
  "sourceRoot",
  "source_root",
  "tripTitle",
  "absolutePath",
  "absolute_path"
]);
const contentPatterns = [
  [/(?:^|[^a-z])[a-z]:[\\/]/i, "Windows 绝对路径"],
  [/\\\\[^\\\s]+[\\/]/, "UNC 绝对路径"],
  [/(?:localhost|127\.0\.0\.1|file:\/\/)/i, "本地服务地址"],
  [/(?:github_pat_|ghp_)[A-Za-z0-9_]{20,}/, "GitHub Token"],
  [/AKIA[0-9A-Z]{16}/, "AWS Access Key"],
  [/-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/, "私钥"],
  [/(?:api[_-]?key|password|client[_-]?secret)\s*[=:]\s*["'][^"']{8,}/i, "疑似密钥"],
  [/D:[\\/]照片/i, "原始照片目录"]
];

async function filesBelow(directory) {
  const result = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const filename = path.join(directory, entry.name);
    if (entry.isDirectory()) result.push(...(await filesBelow(filename)));
    if (entry.isFile()) result.push(filename);
  }
  return result;
}

function inspectJson(value, location = "$") {
  if (Array.isArray(value)) {
    value.forEach((item, index) => inspectJson(item, `${location}[${index}]`));
    return;
  }
  if (!value || typeof value !== "object") return;
  for (const [key, child] of Object.entries(value)) {
    if (forbiddenKeys.has(key)) throw new Error(`公开 JSON 包含禁止字段：${location}.${key}`);
    if (/(?:secret|password|token|api[_-]?key)/i.test(key)) {
      throw new Error(`公开 JSON 包含疑似密钥字段：${location}.${key}`);
    }
    inspectJson(child, `${location}.${key}`);
  }
}

export async function auditPublicTree(rootPath = "dist") {
  const root = path.resolve(rootPath);
  const rootInfo = await stat(root).catch(() => null);
  if (!rootInfo?.isDirectory()) throw new Error(`公开目录不存在：${root}`);

  const files = await filesBelow(root);
  const relativeFiles = new Set(
    files.map((filename) => path.relative(root, filename).replaceAll("\\", "/"))
  );
  for (const required of ["data/trips.json", "data/city-centers.json"]) {
    if (!relativeFiles.has(required)) throw new Error(`公开目录缺少 ${required}`);
  }

  let textCount = 0;
  let totalBytes = 0;
  for (const filename of files) {
    const extension = path.extname(filename).toLowerCase();
    const relative = path.relative(root, filename);
    const info = await stat(filename);
    totalBytes += info.size;
    if (forbiddenExtensions.has(extension) || path.basename(filename).startsWith(".env")) {
      throw new Error(`公开目录包含禁止文件：${relative}`);
    }
    if (!textExtensions.has(extension)) continue;
    textCount += 1;
    const content = await readFile(filename, "utf8");
    for (const [pattern, label] of contentPatterns) {
      if (pattern.test(content)) throw new Error(`公开目录包含${label}：${relative}`);
    }
    if (extension === ".json") inspectJson(JSON.parse(content));
  }

  const result = { files: files.length, textFiles: textCount, totalBytes };
  console.log(
    `公开目录审计通过：${result.files} 个文件，${result.textFiles} 个文本文件，${(result.totalBytes / 1024).toFixed(1)} KiB`
  );
  return result;
}

const invokedPath = process.argv[1] ? pathToFileURL(path.resolve(process.argv[1])).href : "";
if (import.meta.url === invokedPath) await auditPublicTree(process.argv[2]);
