// @vitest-environment jsdom
import { createApp, h, nextTick, ref } from "vue";
import { describe, expect, it, vi } from "vitest";
import PhotoLightbox from "./PhotoLightbox.vue";
import type { Photo } from "./types";

describe("annotation photo lightbox", () => {
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
