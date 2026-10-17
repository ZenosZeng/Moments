// @vitest-environment jsdom
import { createApp, nextTick } from "vue";
import { afterEach, describe, expect, it, vi } from "vitest";
import CompositionManager from "./CompositionManager.vue";
import { api } from "./api";
import { dateRange, editPhoto, imageUrl, localDate, movePhoto, nextPublishDate, splitLocations } from "./compositions";
import type { CompositionDate, CompositionGroup, CompositionPhoto } from "./compositions";

vi.mock("./api", () => ({ api: vi.fn() }));
const days: CompositionDate[] = [
  { captureDate: "2024-05-03", date: "2024-05-03", cities: ["上海"], places: ["外滩，南京路、街巷, 公园"], count: 1 },
  { captureDate: "2024-05-02", date: "2024-05-01", cities: ["深圳"], places: ["海边", "公园"], count: 2 }
];
const sourcePhoto = (id: string, captureDate: string): CompositionPhoto => ({ id, captureDate, relativePath: `month/${id}.jpg`, src: `/api/compositions/source-image?date=${captureDate}&path=month%2F${id}.jpg`, thumbnail: `/thumb/${id}`, preset: "original", strength: 100 });
const dailyPhotos = { "2024-05-03": [sourcePhoto("c", "2024-05-03")], "2024-05-02": [sourcePhoto("a", "2024-05-02"), sourcePhoto("b", "2024-05-02")] };
async function settle() { for (let index = 0; index < 16; index++) await nextTick(); }

async function mount() {
  let stored: CompositionGroup | null = null;
  const sourceOverrides: Record<string, Partial<CompositionDate>> = {};
  vi.mocked(api).mockImplementation(async (path, options) => {
    if (path === "/api/compositions/sources") return { dates: days, presets: [{ id: "original", name: "原色" }, { id: "warm-film", name: "暖调胶片" }, { id: "mono", name: "黑白纪实" }], presetNames: { sunset: "落日暖金" } };
    if (path.startsWith("/api/compositions/sources/")) {
      const date = path.split("/").pop() as keyof typeof dailyPhotos;
      return { ...days.find(day => day.captureDate === date), ...sourceOverrides[date], photos: dailyPhotos[date] };
    }
    if (path.endsWith("/agent-request")) return { directory: "data/compositions/group1", requestFile: "agent-request.md", prompt: "读取图文组" };
    if (options?.method === "POST" || options?.method === "PUT") {
      const body = JSON.parse(String(options.body));
      const createdAt = options.method === "PUT" ? stored?.createdAt || new Date().toISOString() : new Date().toISOString();
      const publishDate = body.autoPublishDate !== false ? stored?.autoPublishDate !== false && options.method === "PUT" ? stored?.publishDate : localDate(new Date(createdAt)) : body.publishDate;
      stored = { ...body, createdAt, publishDate, autoPublishDate: body.autoPublishDate ?? true, id: "group1", directory: "/workspace/data/compositions/group1", schemaVersion: 1, etag: "v1", updatedAt: "2024-05-04", days, cities: body.autoFill?.cities === false ? body.cities : ["上海", "深圳"], time: body.autoFill?.time === false ? { ...body.time, dates: [body.time.start, body.time.end] } : { start: "2024-05-01", end: "2024-05-03", dates: ["2024-05-01", "2024-05-03"] }, photos: body.photos.map((photo: CompositionPhoto) => ({ ...sourcePhoto(photo.id, photo.captureDate), filter: { preset: photo.preset, strength: photo.strength, version: 1 } })) };
      return stored;
    }
    if (path === "/api/compositions/group1" && options?.method === "DELETE") { stored = null; return { deleted: true }; }
    if (path === "/api/compositions/group1") return stored;
    if (path === "/api/compositions") return { groups: stored ? [stored] : [] };
    throw new Error(`Unexpected path ${path}`);
  });
  const host = document.createElement("div");
  document.body.appendChild(host);
  const app = createApp(CompositionManager);
  app.mount(host);
  await settle();
  return { host, app, changeSource: (date: string, metadata: Partial<CompositionDate>) => { sourceOverrides[date] = metadata; }, changeStored: (caption: string) => { if (stored) { stored.caption = caption; stored.etag = "agent-version"; } }, retireFilter: () => { if (stored) stored.photos[0].filter = { version: 1, preset: "sunset", strength: 55 }; } };
}

function setInput(host: HTMLElement, label: string, value: string) {
  const input = host.querySelector<HTMLInputElement>(`[aria-label="${label}"]`)!;
  input.value = value;
  input.dispatchEvent(new Event("input", { bubbles: true }));
}
async function selectDates(host: HTMLElement) {
  for (const checkbox of host.querySelectorAll<HTMLInputElement>(".composition-date-list input")) checkbox.dispatchEvent(new Event("change", { bubbles: true }));
  await settle();
}

async function saveNewGroup(host: HTMLElement) {
  await selectDates(host);
  host.querySelector<HTMLButtonElement>(".composition-source-photo > button:first-child")!.click();
  setInput(host, "图文组标题", "异步保存测试");
  setInput(host, "图文组地点", "街巷");
  host.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  await settle();
}

function dragEvent(type: string, after = false) {
  const event = new MouseEvent(type, { bubbles: true, cancelable: true, clientX: after ? 1 : -1 });
  Object.defineProperty(event, "dataTransfer", { value: { setData: vi.fn(), effectAllowed: "", dropEffect: "" } });
  return event;
}

function dragPhoto(host: HTMLElement, from: string, to: string, after = false) {
  const source = host.querySelector<HTMLButtonElement>(`[data-photo-id="${from}"] .composition-photo-select`)!;
  const target = host.querySelector<HTMLElement>(`[data-photo-id="${to}"]`)!;
  source.dispatchEvent(dragEvent("dragstart"));
  target.dispatchEvent(dragEvent("dragover", after));
  target.dispatchEvent(dragEvent("drop", after));
  source.dispatchEvent(dragEvent("dragend"));
}
afterEach(() => { vi.mocked(api).mockReset(); vi.restoreAllMocks(); });

describe("composition manager", () => {
  it("shows publication planning in copy, skips occupied days, and persists a manual override", async () => {
    const { host, app } = await mount();
    try {
      const today = localDate();
      expect(host.querySelector(".composition-metadata h2")!.textContent).toBe("基本信息");
      expect(host.querySelector<HTMLInputElement>('.composition-copy [aria-label="计划发布日期"]')!.value).toBe(today);
      expect(host.querySelector<HTMLInputElement>('[aria-label="计划发布日期自动填写"]')!.checked).toBe(true);
      expect(host.querySelector<HTMLInputElement>('[aria-label="计划发布日期"]')!.disabled).toBe(true);
      await saveNewGroup(host);
      expect(host.querySelector(".composition-group-publish")!.textContent).toContain(today);
      Array.from(host.querySelectorAll<HTMLButtonElement>(".composition-actions button")).find(button => button.textContent === "新建")!.click();
      await settle();
      const planned = host.querySelector<HTMLInputElement>('[aria-label="计划发布日期"]')!;
      expect(planned.value).toBe(nextPublishDate(today, [today]));
      const auto = host.querySelector<HTMLInputElement>('[aria-label="计划发布日期自动填写"]')!;
      auto.checked = false; auto.dispatchEvent(new Event("change", { bubbles: true }));
      await settle();
      expect(planned.disabled).toBe(false);
      setInput(host, "计划发布日期", "2028-02-29");
      await saveNewGroup(host);
      expect(host.querySelector<HTMLInputElement>('[aria-label="计划发布日期"]')!.value).toBe("2028-02-29");
      expect(host.querySelector<HTMLInputElement>('[aria-label="计划发布日期自动填写"]')!.checked).toBe(false);
      const writes = vi.mocked(api).mock.calls.filter(([_path, options]) => options?.method === "POST");
      expect(JSON.parse(String(writes[0][1]?.body))).toMatchObject({ autoPublishDate: true });
      expect(JSON.parse(String(writes[0][1]?.body))).not.toHaveProperty("publishDate");
      expect(JSON.parse(String(writes[1][1]?.body))).toMatchObject({ autoPublishDate: false, publishDate: "2028-02-29" });
      host.querySelector<HTMLButtonElement>('[title="重新载入图文组和精选来源"]')!.click();
      await settle();
      expect(host.querySelector<HTMLInputElement>('[aria-label="计划发布日期"]')!.value).toBe("2028-02-29");
    } finally { app.unmount(); host.remove(); }
  });

  it.each(["switch", "reload"])("blocks editing during a delayed %s and restores the draft if reading fails", async (action) => {
    const { host, app } = await mount();
    try {
      await saveNewGroup(host);
      setInput(host, "文案正文", "读取失败也不能丢失的草稿");
      await settle();
      vi.spyOn(window, "confirm").mockReturnValue(true);
      const originalApi = vi.mocked(api).getMockImplementation()!;
      let rejectRead!: (reason: Error) => void;
      const pending = new Promise<never>((_resolve, reject) => { rejectRead = reject; });
      vi.mocked(api).mockImplementation((path, options) => {
        if (path === (action === "switch" ? "/api/compositions/group1" : "/api/compositions/sources") && !options) return pending;
        return originalApi(path, options);
      });
      host.querySelector<HTMLButtonElement>(action === "switch" ? ".composition-group" : '[title="重新载入图文组和精选来源"]')!.click();
      await settle();
      expect(host.querySelector("form")).toBeNull();
      expect(host.querySelector<HTMLButtonElement>('[form="composition-form"]')!.disabled).toBe(true);
      rejectRead(new Error("读取暂时失败"));
      await settle();
      expect(host.querySelector<HTMLTextAreaElement>('[aria-label="文案正文"]')!.value).toBe("读取失败也不能丢失的草稿");
      expect(host.querySelector(".composition-heading i")).not.toBeNull();
      expect(host.querySelector(".composition-message")!.textContent).toContain("读取暂时失败");
      expect(host.querySelector<HTMLButtonElement>('[form="composition-form"]')!.disabled).toBe(false);
    } finally { app.unmount(); host.remove(); }
  });

  it("adopts successful save responses without another group read or a duplicate POST", async () => {
    const { host, app } = await mount();
    try {
      const originalApi = vi.mocked(api).getMockImplementation()!;
      vi.mocked(api).mockImplementation((path, options) => {
        if (path === "/api/compositions/group1" && !options) throw new Error("保存后的读取不可用");
        return originalApi(path, options);
      });
      await saveNewGroup(host);
      expect(host.querySelector(".composition-directory code")!.textContent).toBe("/workspace/data/compositions/group1");
      expect(host.querySelector(".composition-heading i")).toBeNull();
      setInput(host, "文案正文", "第二次保存应更新同一组");
      host.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await settle();
      const writes = vi.mocked(api).mock.calls.filter(([_path, options]) => ["POST", "PUT"].includes(options?.method || ""));
      expect(writes.map(([path, options]) => [path, options?.method])).toEqual([
        ["/api/compositions", "POST"], ["/api/compositions/group1", "PUT"]
      ]);
      expect(vi.mocked(api).mock.calls.some(([path, options]) => path === "/api/compositions/group1" && !options)).toBe(false);
      expect(host.querySelector(".composition-message")!.textContent).toContain("图文组已保存");
    } finally { app.unmount(); host.remove(); }
  });

  it("edits the displayed group photo in the lightbox, retains per-photo drafts, and persists them", async () => {
    const { host, app } = await mount();
    try {
      await selectDates(host);
      const source = host.querySelectorAll<HTMLButtonElement>(".composition-source-photo > button:first-child");
      source[0].click(); source[1].click();
      await settle();
      host.querySelector<HTMLButtonElement>('[title="放大第 1 张图片"]')!.click();
      await settle();
      expect(document.querySelector(".annotation-lightbox-controls")).not.toBeNull();
      document.querySelector<HTMLButtonElement>('.annotation-lightbox-controls [title="黑白纪实"]')!.click();
      await settle();
      const slider = document.querySelector<HTMLInputElement>('[aria-label="大图滤镜强度"]')!;
      slider.value = "65"; slider.dispatchEvent(new Event("input", { bubbles: true }));
      await settle();
      await vi.waitFor(() => expect(document.querySelector<HTMLImageElement>('.annotation-lightbox > img')!.src).toContain("preset=mono&strength=65"));
      expect(host.querySelector<HTMLInputElement>('[aria-label="第 1 张滤镜强度"]')!.value).toBe("65");
      expect(host.querySelector<HTMLImageElement>('[data-photo-id="a"] img')!.src).toContain("preset=original");
      document.querySelector<HTMLButtonElement>('[title="下一张照片"]')!.click();
      await settle();
      expect(slider.value).toBe("100");
      expect(slider.disabled).toBe(true);
      document.querySelector<HTMLButtonElement>('.annotation-lightbox-controls [title="暖调胶片"]')!.click();
      await settle();
      slider.value = "30"; slider.dispatchEvent(new Event("input", { bubbles: true }));
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
      await settle();
      host.querySelector<HTMLButtonElement>('[title="放大第 2 张图片"]')!.click();
      await settle();
      expect(document.querySelector<HTMLInputElement>('[aria-label="大图滤镜强度"]')!.value).toBe("30");
      expect(document.querySelector<HTMLImageElement>('.annotation-lightbox > img')!.src).toContain("preset=warm-film&strength=30");
      document.querySelector<HTMLButtonElement>('[title="关闭大图"]')!.click();
      await settle();
      setInput(host, "图文组标题", "大图调色"); setInput(host, "图文组地点", "街巷");
      host.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await settle();
      const call = vi.mocked(api).mock.calls.find(([path, options]) => path === "/api/compositions" && options?.method === "POST")!;
      expect(JSON.parse(String(call[1]?.body)).photos.map((photo: CompositionPhoto) => [photo.preset, photo.strength])).toEqual([["mono", 65], ["warm-film", 30]]);
      host.querySelector<HTMLButtonElement>('[title="放大来源照片"]')!.click();
      await settle();
      expect(document.querySelector(".annotation-lightbox-controls")).toBeNull();
      expect(document.querySelector<HTMLImageElement>('.annotation-lightbox > img')!.src).toContain("preset=original");
      document.querySelector<HTMLButtonElement>('[title="关闭大图"]')!.click();
      await settle();
    } finally { app.unmount(); host.remove(); }
  });
  it("selects a photo by clicking its image, edits only that photo, and zooms independently", async () => {
    const { host, app } = await mount();
    try {
      await selectDates(host);
      for (const button of host.querySelectorAll<HTMLButtonElement>(".composition-source-photo > button:first-child")) button.click();
      await settle();
      const first = host.querySelector<HTMLButtonElement>('[title="选中第 1 张图片"]')!;
      first.click(); await settle();
      expect(first.getAttribute("aria-pressed")).toBe("true");
      expect(document.querySelector(".annotation-lightbox")).toBeNull();
      host.querySelector<HTMLButtonElement>('.composition-presets [title="黑白纪实"]')!.click();
      await settle();
      expect(first.querySelector("img")!.src).toContain("preset=mono");
      host.querySelector<HTMLButtonElement>('[title="选中第 2 张图片"]')!.click();
      await settle();
      host.querySelector<HTMLButtonElement>('.composition-presets [title="暖调胶片"]')!.click();
      await settle();
      expect(first.querySelector("img")!.src).toContain("preset=mono");
      expect(host.querySelector<HTMLImageElement>('[data-photo-id="a"] img')!.src).toContain("preset=warm-film");
      first.click(); await settle();
      expect(host.querySelector('.composition-presets [title="黑白纪实"]')!.getAttribute("aria-pressed")).toBe("true");
      host.querySelector<HTMLButtonElement>('[title="放大第 2 张图片"]')!.click();
      await settle();
      expect(document.querySelector<HTMLImageElement>('.annotation-lightbox img')!.src).toContain("preset=warm-film");
      expect(first.getAttribute("aria-pressed")).toBe("true");
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
      await settle();
    } finally { app.unmount(); host.remove(); }
  });

  it("inserts dragged photos in either direction without swapping filters and safely cancels drags", async () => {
    const { host, app } = await mount();
    try {
      await selectDates(host);
      for (const button of host.querySelectorAll<HTMLButtonElement>(".composition-source-photo > button:first-child")) button.click();
      await settle();
      const order = () => Array.from(host.querySelectorAll<HTMLElement>(".composition-photo"), photo => photo.dataset.photoId);
      host.querySelector<HTMLButtonElement>('[title="选中第 1 张图片"]')!.click();
      await settle();
      host.querySelector<HTMLButtonElement>('.composition-presets [title="暖调胶片"]')!.click();
      await settle();
      dragPhoto(host, "c", "b", true);
      await settle();
      expect(order()).toEqual(["a", "b", "c"]);
      expect(host.querySelector(".composition-photo.active")!.getAttribute("data-photo-id")).toBe("c");
      expect(host.querySelector<HTMLImageElement>('[data-photo-id="c"] img')!.src).toContain("preset=warm-film");
      dragPhoto(host, "c", "a");
      await settle();
      expect(order()).toEqual(["c", "a", "b"]);
      const source = host.querySelector<HTMLButtonElement>('[data-photo-id="a"] .composition-photo-select')!;
      source.dispatchEvent(dragEvent("dragstart"));
      host.querySelector('[data-photo-id="b"]')!.dispatchEvent(dragEvent("dragover", true));
      await settle();
      expect(host.querySelector(".composition-photo.drop-after")).not.toBeNull();
      source.dispatchEvent(dragEvent("dragend"));
      await settle();
      expect(order()).toEqual(["c", "a", "b"]);
      expect(host.querySelector(".dragging, .drop-before, .drop-after")).toBeNull();
      host.querySelector('[data-photo-id="b"]')!.dispatchEvent(dragEvent("drop", true));
      await settle();
      expect(order()).toEqual(["c", "a", "b"]);
      expect(host.querySelector('[title="向前移动"], [title="向后移动"]')).toBeNull();
      source.focus();
      source.dispatchEvent(new KeyboardEvent("keydown", { key: "End", altKey: true, bubbles: true, cancelable: true }));
      await settle();
      expect(order()).toEqual(["c", "b", "a"]);
      expect(document.activeElement).toBe(source);
      expect(document.querySelector(".annotation-lightbox")).toBeNull();
    } finally { app.unmount(); host.remove(); }
  });
  it("shows the actual saved directory, retains it for dirty edits, and labels retired filters", async () => {
    const { host, app, retireFilter } = await mount();
    try {
      expect(host.querySelector(".composition-directory")!.textContent).toContain("尚未保存");
      await selectDates(host);
      host.querySelector<HTMLButtonElement>(".composition-source-photo > button:first-child")!.click();
      setInput(host, "图文组标题", "目录测试"); setInput(host, "图文组地点", "街巷");
      await settle();
      host.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await settle();
      expect(host.querySelector(".composition-directory code")!.textContent).toBe("/workspace/data/compositions/group1");
      setInput(host, "图文组标题", "修改标题");
      await settle();
      expect(host.querySelector(".composition-heading i")).not.toBeNull();
      expect(host.querySelector(".composition-directory")!.textContent).not.toContain("尚未保存");
      retireFilter();
      vi.spyOn(window, "confirm").mockReturnValue(true);
      host.querySelector<HTMLButtonElement>('[title="重新载入图文组和精选来源"]')!.click();
      await settle();
      expect(host.querySelector(".composition-directory code")!.textContent).toBe("/workspace/data/compositions/group1");
      expect(host.querySelector(".composition-photo-tools span")!.textContent).toBe("落日暖金");
      expect(host.querySelectorAll(".composition-presets button")).toHaveLength(3);
      host.querySelector<HTMLButtonElement>('[title="复制本地目录"]')!.click();
      await settle();
      expect(host.querySelector(".composition-message")!.textContent).toContain("剪贴板不可用");
      Array.from(host.querySelectorAll<HTMLButtonElement>(".composition-actions button")).find(button => button.textContent === "新建")!.click();
      await settle();
      expect(host.querySelector(".composition-directory")!.textContent).toContain("尚未保存");
    } finally { app.unmount(); host.remove(); }
  });
  it("refreshes annotated metadata when a previously loaded date is selected again", async () => {
    const { host, app, changeSource } = await mount();
    try {
      const checkbox = host.querySelector<HTMLInputElement>(".composition-date-list input")!;
      checkbox.dispatchEvent(new Event("change", { bubbles: true }));
      await settle();
      expect(host.querySelector<HTMLInputElement>('[aria-label="图文城市"]')!.value).toBe("上海");
      host.querySelector<HTMLInputElement>(".composition-date-list input")!.dispatchEvent(new Event("change", { bubbles: true }));
      await settle();
      changeSource("2024-05-03", { cities: ["广州"], date: "2024-05-04" });
      host.querySelector<HTMLInputElement>(".composition-date-list input")!.dispatchEvent(new Event("change", { bubbles: true }));
      await settle();
      expect(host.querySelector<HTMLInputElement>('[aria-label="图文城市"]')!.value).toBe("广州");
      expect(host.querySelector<HTMLInputElement>('[aria-label="图文开始日期"]')!.value).toBe("2024-05-04");
    } finally { app.unmount(); host.remove(); }
  });
  it("allows manual dates and cities, persists them, and resets to annotations for a new source selection", async () => {
    const { host, app } = await mount();
    try {
      await selectDates(host);
      host.querySelector<HTMLButtonElement>(".composition-source-photo > button:first-child")!.click();
      for (const label of ["时间自动填写", "城市自动填写"]) {
        const checkbox = host.querySelector<HTMLInputElement>(`[aria-label="${label}"]`)!;
        expect(checkbox.checked).toBe(true);
        checkbox.checked = false;
        checkbox.dispatchEvent(new Event("change", { bubbles: true }));
      }
      await settle();
      expect(host.querySelector<HTMLInputElement>('[aria-label="图文城市"]')!.disabled).toBe(false);
      setInput(host, "图文开始日期", "2024-06-01");
      setInput(host, "图文结束日期", "2024-06-04");
      setInput(host, "图文城市", "杭州，南京");
      setInput(host, "图文组标题", "手动信息");
      setInput(host, "图文组地点", "小街");
      host.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await settle();
      expect(host.querySelector<HTMLInputElement>('[aria-label="时间自动填写"]')!.checked).toBe(false);
      expect(host.querySelector<HTMLInputElement>('[aria-label="图文开始日期"]')!.value).toBe("2024-06-01");
      expect(host.querySelector<HTMLInputElement>('[aria-label="图文城市"]')!.value).toBe("杭州，南京");
      const call = vi.mocked(api).mock.calls.find(([path, options]) => path === "/api/compositions" && options?.method === "POST")!;
      const body = JSON.parse(String(call[1]?.body));
      expect(body.autoFill).toEqual({ time: false, cities: false });
      expect(body.time).toEqual({ start: "2024-06-01", end: "2024-06-04" });
      expect(body.cities).toEqual(["杭州", "南京"]);
      const date = host.querySelector<HTMLInputElement>(".composition-date-list input")!;
      date.dispatchEvent(new Event("change", { bubbles: true }));
      await settle();
      expect(host.querySelector<HTMLInputElement>('[aria-label="时间自动填写"]')!.checked).toBe(true);
      expect(host.querySelector<HTMLInputElement>('[aria-label="城市自动填写"]')!.checked).toBe(true);
      expect(host.querySelector<HTMLInputElement>('[aria-label="图文城市"]')!.value).toBe("深圳");
      expect(host.querySelector<HTMLInputElement>('[aria-label="图文开始日期"]')!.value).toBe("2024-05-01");
    } finally { app.unmount(); host.remove(); }
  });

  it("selects multiple dates, derives time/cities and offers location references", async () => {
    const { host, app } = await mount();
    try {
      await selectDates(host);
      expect(host.querySelectorAll(".composition-source-photo")).toHaveLength(3);
      expect(host.querySelector<HTMLInputElement>('[aria-label="图文开始日期"]')!.value).toBe("2024-05-01");
      expect(host.querySelector<HTMLInputElement>('[aria-label="图文结束日期"]')!.value).toBe("2024-05-03");
      expect(host.querySelector<HTMLInputElement>('[aria-label="图文城市"]')!.value).toBe("上海，深圳");
      expect(Array.from(host.querySelectorAll('.composition-location-hints button'), element => element.textContent)).toEqual(["外滩", "南京路", "街巷", "公园", "海边"]);
      host.querySelector<HTMLButtonElement>('[title="填入地点：外滩"]')!.click();
      await settle();
      expect(host.querySelector<HTMLInputElement>('[aria-label="图文组地点"]')!.value).toBe("外滩");
      expect(host.querySelector('[aria-label="图文组标题"]')!.hasAttribute("required")).toBe(true);
      expect(host.querySelector('[aria-label="文案标题"]')!.hasAttribute("required")).toBe(false);
    } finally { app.unmount(); host.remove(); }
  });

  it("saves ordered featured selections and per-photo filters while optional copy remains empty", async () => {
    const { host, app } = await mount();
    try {
      await selectDates(host);
      const source = host.querySelectorAll<HTMLButtonElement>(".composition-source-photo > button:first-child");
      source[0].click(); source[1].click();
      await settle();
      host.querySelector<HTMLButtonElement>('.composition-presets [title="暖调胶片"]')!.click();
      await settle();
      const slider = host.querySelector<HTMLInputElement>('[aria-label="第 2 张滤镜强度"]')!;
      slider.value = "65"; slider.dispatchEvent(new Event("input", { bubbles: true }));
      await settle();
      host.querySelector<HTMLButtonElement>('[title="将当前滤镜应用到整组，保留各图强度"]')!.click();
      dragPhoto(host, "c", "a", true);
      setInput(host, "图文组标题", "街巷小记"); setInput(host, "图文组地点", "海边");
      await settle();
      host.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await settle();
      const call = vi.mocked(api).mock.calls.find(([path, options]) => path === "/api/compositions" && options?.method === "POST")!;
      const body = JSON.parse(String(call[1]?.body));
      expect(body.photos.map((photo: CompositionPhoto) => photo.id)).toEqual(["a", "c"]);
      expect(body.photos.every((photo: CompositionPhoto) => photo.preset === "warm-film")).toBe(true);
      expect(body.photos.map((photo: CompositionPhoto) => photo.strength)).toEqual([65, 100]);
      expect(host.querySelectorAll(".composition-photo-strength input")).toHaveLength(2);
      expect(host.querySelector(".composition-filter input[type='range']")).toBeNull();
      expect(body.caption).toBe(""); expect(body.captionTitle).toBe("");
      expect(body.sourceDates).toEqual(["2024-05-02", "2024-05-03"]);
      expect(host.querySelector(".composition-heading i")).toBeNull();
    } finally { app.unmount(); host.remove(); }
  });

  it("opens every source and selected image in the large viewer with its filter", async () => {
    const { host, app } = await mount();
    try {
      await selectDates(host);
      host.querySelector<HTMLButtonElement>('[title="放大来源照片"]')!.click();
      await settle();
      expect(document.querySelector('[role="dialog"] img')?.getAttribute("src")).toContain("size=preview");
      document.querySelector<HTMLButtonElement>('[title="关闭大图"]')!.click();
      host.querySelector<HTMLButtonElement>(".composition-source-photo > button:first-child")!.click();
      await settle();
      host.querySelector<HTMLButtonElement>('.composition-presets [title="黑白纪实"]')!.click();
      await settle();
      host.querySelector<HTMLButtonElement>('[title="放大第 1 张图片"]')!.click();
      await settle();
      expect(document.querySelector('[role="dialog"] img')?.getAttribute("src")).toContain("preset=mono");
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
      await settle();
      expect(document.querySelector(".annotation-lightbox")).toBeNull();
    } finally { app.unmount(); host.remove(); }
  });

  it("rejects missing fields, removes a deselected date's photos, and retains unsaved work on cancelled navigation", async () => {
    const { host, app } = await mount();
    try {
      host.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await settle();
      expect(host.querySelector(".composition-message")!.textContent).toContain("标题和地点必填");
      await selectDates(host);
      host.querySelector<HTMLButtonElement>(".composition-source-photo > button:first-child")!.click();
      await settle();
      expect(host.querySelectorAll(".composition-photo")).toHaveLength(1);
      host.querySelector<HTMLInputElement>(".composition-date-list input")!.dispatchEvent(new Event("change"));
      await settle();
      expect(host.querySelectorAll(".composition-photo")).toHaveLength(0);
      vi.spyOn(window, "confirm").mockReturnValue(false);
      setInput(host, "图文组标题", "未保存草稿");
      const create = Array.from(host.querySelectorAll<HTMLButtonElement>(".composition-actions button")).find(button => button.textContent === "新建")!;
      create.click(); await settle();
      expect(host.querySelector<HTMLInputElement>('[aria-label="图文组标题"]')!.value).toBe("未保存草稿");
    } finally { app.unmount(); host.remove(); }
  });

  it("prepares a separate agent task after save and reloads manually edited copy", async () => {
    const { host, app, changeStored } = await mount();
    try {
      await selectDates(host);
      host.querySelector<HTMLButtonElement>(".composition-source-photo > button:first-child")!.click();
      setInput(host, "图文组标题", "一组照片"); setInput(host, "图文组地点", "街巷");
      await settle();
      Array.from(host.querySelectorAll<HTMLButtonElement>(".composition-actions button")).find(button => button.textContent === "准备文案")!.click();
      await settle();
      expect(vi.mocked(api).mock.calls.some(([path]) => path === "/api/compositions/group1/agent-request")).toBe(true);
      expect(document.querySelector<HTMLTextAreaElement>('[aria-label="Agent 指令"]')?.value).toBe("读取图文组");
      document.querySelector<HTMLButtonElement>('[title="关闭对话框"]')!.click();
      changeStored("Agent 新文案");
      host.querySelector<HTMLButtonElement>('[title="重新载入图文组和精选来源"]')!.click();
      await settle();
      expect(host.querySelector<HTMLTextAreaElement>('[aria-label="文案正文"]')!.value).toBe("Agent 新文案");
    } finally { app.unmount(); host.remove(); }
  });
});

describe("composition helpers", () => {
  it("plans calendar days across leap days and years without changing the input", () => {
    expect(nextPublishDate("2024-02-28", ["2024-02-28", "2024-02-29"])).toBe("2024-03-01");
    expect(nextPublishDate("2025-12-31", ["2025-12-31", "2026-01-01"])).toBe("2026-01-02");
    expect(nextPublishDate("2024-05-02", ["2024-05-03"])).toBe("2024-05-02");
    expect(localDate(new Date(2024, 0, 2, 23, 59))).toBe("2024-01-02");
  });
  it("splits comma-separated locations individually while preserving words and removing duplicates", () => {
    expect(splitLocations(["外滩， 南京路、街巷,公园；河边", "公园;海边\nOld Town"])).toEqual(["外滩", "南京路", "街巷", "公园", "河边", "海边", "Old Town"]);
  });
  it("keeps single dates short, handles empty and noncontiguous dates, and does not mutate order", () => {
    expect(dateRange([])).toBe("—");
    expect(dateRange([days[0]])).toBe("2024-05-03");
    const values = [sourcePhoto("a", "2024-05-02"), sourcePhoto("b", "2024-05-02"), sourcePhoto("c", "2024-05-02")];
    expect(movePhoto(values, 0, 2).map(photo => photo.id)).toEqual(["b", "c", "a"]);
    expect(movePhoto(values, 2, 0).map(photo => photo.id)).toEqual(["c", "a", "b"]);
    expect(movePhoto(values, 0, 0)).toEqual(values);
    expect(movePhoto(values, -1, 0)).toEqual(values);
    expect(movePhoto(values, 0, 3)).toEqual(values);
    expect(values[0].id).toBe("a");
    expect(movePhoto(values, 0, -1)).toEqual(values);
    expect(imageUrl(editPhoto({ ...values[0], filter: { version: 1, preset: "mono", strength: 40 } }), "preview")).toContain("preset=mono&strength=40");
  });
});
