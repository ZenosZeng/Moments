import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import { afterEach, expect, test } from "vitest";

import { auditPublicTree } from "./audit-public-tree.mjs";

const temporaryRoots = [];

async function publicTree(manifest) {
  const root = await mkdtemp(path.join(tmpdir(), "public-audit-"));
  temporaryRoots.push(root);
  await mkdir(path.join(root, "data"));
  await writeFile(
    path.join(root, "data", "trips.json"),
    JSON.stringify(manifest),
    "utf8"
  );
  await writeFile(
    path.join(root, "data", "city-centers.json"),
    JSON.stringify({ version: 1, cities: [] }),
    "utf8"
  );
  return root;
}

afterEach(async () => {
  await Promise.all(temporaryRoots.splice(0).map((root) => rm(root, { recursive: true, force: true })));
});

test("accepts a whitelisted public manifest", async () => {
  const root = await publicTree({ trips: [{ date: "2026-01-02", city: "深圳" }] });
  await expect(auditPublicTree(root)).resolves.toMatchObject({ files: 2, textFiles: 2 });
});

test("rejects local paths in public JSON", async () => {
  const root = await publicTree({ trips: [{ source: "D:\\照片\\private.jpg" }] });
  await expect(auditPublicTree(root)).rejects.toThrow("Windows 绝对路径");
});

function webp(...types) {
  const chunks = types.map((type) => {
    const chunk = Buffer.alloc(10);
    chunk.write(type, 0, 4, "ascii");
    chunk.writeUInt32LE(2, 4);
    return chunk;
  });
  const header = Buffer.alloc(12);
  header.write("RIFF", 0, 4, "ascii");
  header.writeUInt32LE(4 + chunks.reduce((size, chunk) => size + chunk.length, 0), 4);
  header.write("WEBP", 8, 4, "ascii");
  return Buffer.concat([header, ...chunks]);
}

const photo = "media/0123456789abcdef0123.webp";
const thumbnail = "media/0123456789abcdef0123-thumb.webp";

async function photoTree() {
  const root = await publicTree({ trips: [{ photos: [{ src: photo, thumbnail }] }] });
  await mkdir(path.join(root, "media"));
  await writeFile(path.join(root, photo), webp("VP8 "));
  await writeFile(path.join(root, thumbnail), webp("VP8 "));
  return root;
}

test("audits raw data before city centers are generated", async () => {
  const root = await photoTree();
  await rm(path.join(root, "data", "city-centers.json"));
  await expect(auditPublicTree(root, { requireCityCenters: false })).resolves.toMatchObject({ files: 3 });
  await expect(auditPublicTree(root)).rejects.toThrow("city-centers.json");
});

test.each(["EXIF", "XMP "])("rejects WebP metadata: %s", async (type) => {
  const root = await photoTree();
  await writeFile(path.join(root, photo), webp("VP8 ", type));
  await expect(auditPublicTree(root)).rejects.toThrow("EXIF/XMP");
});

test("rejects invalid WebP containers", async () => {
  const root = await photoTree();
  await writeFile(path.join(root, photo), Buffer.from("not an image"));
  await expect(auditPublicTree(root)).rejects.toThrow("无效 WebP");
});

test.each(["https://example.com/private.webp", "../outside.webp", "media/missing.webp"])(
  "rejects non-whitelisted photo references: %s", async (src) => {
    const root = await publicTree({ trips: [{ photos: [{ src, thumbnail }] }] });
    await expect(auditPublicTree(root)).rejects.toThrow("照片引用");
  }
);

test("rejects missing thumbnail files", async () => {
  const root = await photoTree();
  await rm(path.join(root, thumbnail));
  await expect(auditPublicTree(root)).rejects.toThrow("文件缺失");
});

test("rejects private fields and databases", async () => {
  const root = await publicTree({ trips: [{ note: "private" }] });
  await expect(auditPublicTree(root)).rejects.toThrow("禁止字段");
  await writeFile(path.join(root, "data", "trips.json"), '{"trips":[]}');
  await writeFile(path.join(root, "annotations.sqlite3"), "private");
  await expect(auditPublicTree(root)).rejects.toThrow("禁止文件");
});
