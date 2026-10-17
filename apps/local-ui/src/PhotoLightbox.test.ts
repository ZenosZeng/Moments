// @vitest-environment jsdom
import { createApp, h, nextTick, ref } from "vue";
import { describe, expect, it, vi } from "vitest";
import PhotoLightbox from "./PhotoLightbox.vue";
import type { Photo } from "./types";

describe("annotation photo lightbox", () => {
  it("supports optional controls, keeps range keys local, traps input focus, and reloads changed URLs", async () => {
    const photos = ref<Photo[]>([1, 2].map(number => ({ relative_path: `month/${number}.jpg`, thumbnail_url: `/thumb/${number}`, preview_url: `/preview/${number}`, capture_time: "", featured: true })));
    const index = ref(0);
    const host = document.createElement("div");
    document.body.appendChild(host);
    const app = createApp({ render: () => h(PhotoLightbox, { photos: photos.value, index: index.value, date: "2024-05-02", "onUpdate:index": (value: number) => { index.value = value; } }, {
      controls: () => h("div", [h("button", { disabled: true }, "Disabled"), h("input", { type: "range", min: 0, max: 100, value: 50 })])
    }) });
    app.mount(host);
    try {
      await nextTick();
      expect(document.querySelector(".annotation-lightbox.with-controls")).not.toBeNull();
      const input = document.querySelector<HTMLInputElement>(".annotation-lightbox-controls input")!;
      input.focus();
      const arrow = new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true, cancelable: true });
      input.dispatchEvent(arrow);
      await nextTick();
      expect(index.value).toBe(0);
      expect(arrow.defaultPrevented).toBe(false);
      input.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true }));
      expect(document.activeElement).toBe(document.querySelector(".lightbox-close"));
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, cancelable: true }));
      expect(document.activeElement).toBe(input);
      document.querySelector(".annotation-lightbox > img")!.dispatchEvent(new Event("load"));
      await nextTick();
      expect(document.querySelector(".annotation-lightbox > img.pending")).toBeNull();
      photos.value[0].preview_url = "/preview/1?preset=mono";
      await nextTick();
      expect(document.querySelector(".annotation-lightbox > img.pending")).not.toBeNull();
      expect(document.querySelector(".annotation-lightbox > img")!.getAttribute("src")).toBe("/preview/1?preset=mono");
      document.querySelector(".annotation-lightbox > img")!.dispatchEvent(new Event("error"));
      await nextTick();
      expect(document.querySelector(".lightbox-loading")!.textContent).toBe("大图读取失败");
      photos.value[0].preview_url = "/preview/1?preset=original";
      await nextTick();
      expect(document.querySelector(".lightbox-loading")!.textContent).not.toContain("读取失败");
    } finally { app.unmount(); host.remove(); }
  });
  it("opens the large variant, navigates, closes and restores scroll state", async () => {
    const photos: Photo[] = [1, 2].map((number) => ({
      relative_path: `month/${number}.jpg`, thumbnail_url: `/thumb/${number}`,
      preview_url: `/preview/${number}`, capture_time: "", featured: false
    }));
    const index = ref(0);
    const close = vi.fn();
    const host = document.createElement("div");
    document.body.appendChild(host);
    document.body.style.overflow = "auto";
    const app = createApp({ render: () => h(PhotoLightbox, {
      photos, index: index.value, date: "2026-10-14", onClose: close,
      "onUpdate:index": (value: number) => { index.value = value; }
    }) });
    app.mount(host);
    try {
      await nextTick();
      expect(document.querySelector('[role="dialog"] img')?.getAttribute("src")).toBe("/preview/1");
      expect(document.body.style.overflow).toBe("hidden");
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight" }));
      await nextTick();
      expect(index.value).toBe(1);
      expect(document.querySelector('[role="dialog"] img')?.getAttribute("src")).toBe("/preview/2");
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight" }));
      await nextTick();
      expect(index.value).toBe(0);
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
      expect(close).toHaveBeenCalledTimes(1);
    } finally {
      app.unmount();
      host.remove();
      expect(document.body.style.overflow).toBe("auto");
      document.body.style.overflow = "";
    }
  });
});
