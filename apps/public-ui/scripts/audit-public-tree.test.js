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
