import { lstat, readFile, readdir, stat } from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

const textExtensions = new Set([".html", ".js", ".css", ".json", ".xml", ".txt", ".map"]);
const forbiddenExtensions = new Set([".sqlite", ".sqlite3", ".db", ".env", ".pem", ".key", ".heic"]);
const mediaName = /^media\/[0-9a-f]{20}(?:-thumb)?\.webp$/;
const forbiddenKeys = new Set([
  "people",
  "person",
  "personId",
  "person_id",
  "companion",
  "companions",
  "publicName",
  "public_name",
  "private_name",
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
    if (entry.isSymbolicLink()) throw new Error(`公开目录包含符号链接：${filename}`);
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

function inspectWebp(content, filename) {
  if (content.length < 12 || content.toString("ascii", 0, 4) !== "RIFF" ||
      content.toString("ascii", 8, 12) !== "WEBP" || content.readUInt32LE(4) + 8 !== content.length) {
    throw new Error(`无效 WebP 文件：${filename}`);
  }
  let imageFound = false;
  for (let offset = 12; offset < content.length;) {
    if (offset + 8 > content.length) throw new Error(`无效 WebP 数据块：${filename}`);
    const type = content.toString("ascii", offset, offset + 4);
    const size = content.readUInt32LE(offset + 4);
    if (type === "EXIF" || type === "XMP ") {
      throw new Error(`WebP 包含 EXIF/XMP 元数据：${filename}`);
    }
    if (!["VP8 ", "VP8L", "VP8X", "ALPH"].includes(type)) {
      throw new Error(`WebP 包含非白名单数据块 ${type}：${filename}`);
    }
    imageFound ||= type === "VP8 " || type === "VP8L";
    offset += 8 + size + (size % 2);
    if (offset > content.length) throw new Error(`无效 WebP 数据块：${filename}`);
  }
  if (!imageFound) throw new Error(`WebP 缺少图像数据：${filename}`);
}

function inspectPhotoReferences(manifest, relativeFiles) {
  for (const trip of manifest.trips ?? []) {
    for (const photo of trip.photos ?? []) {
      for (const key of ["src", "thumbnail"]) {
        const value = photo[key];
        if (typeof value !== "string" || !mediaName.test(value) || !relativeFiles.has(value)) {
          throw new Error(`精选照片引用无效或文件缺失：${key}`);
        }
      }
    }
  }
}

export async function auditPublicTree(rootPath = "dist", { requireCityCenters = true } = {}) {
  const root = path.resolve(rootPath);
  const rootInfo = await lstat(root).catch(() => null);
  if (!rootInfo?.isDirectory() || rootInfo.isSymbolicLink()) {
    throw new Error(`公开目录不存在或为符号链接：${root}`);
  }

  const files = await filesBelow(root);
  const relativeFiles = new Set(
    files.map((filename) => path.relative(root, filename).replaceAll("\\", "/"))
  );
  const requiredFiles = ["data/trips.json"];
  if (requireCityCenters) requiredFiles.push("data/city-centers.json");
  for (const required of requiredFiles) {
    if (!relativeFiles.has(required)) throw new Error(`公开目录缺少 ${required}`);
  }
  inspectPhotoReferences(JSON.parse(await readFile(path.join(root, "data", "trips.json"), "utf8")), relativeFiles);

  let textCount = 0;
  let totalBytes = 0;
  for (const filename of files) {
    const extension = path.extname(filename).toLowerCase();
    const relative = path.relative(root, filename).replaceAll("\\", "/");
    const info = await stat(filename);
    totalBytes += info.size;
    if (forbiddenExtensions.has(extension) || path.basename(filename).startsWith(".env")) {
      throw new Error(`公开目录包含禁止文件：${relative}`);
    }
    if (relative.startsWith("media/") && !mediaName.test(relative)) {
      throw new Error(`公开图片文件名不在白名单内：${relative}`);
    }
    if (extension === ".webp") inspectWebp(await readFile(filename), relative);
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
