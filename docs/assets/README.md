# README 首图

`readme-cover.png` 使用内置 `image_gen` 重新生成，为 2048 × 768 的不透明 PNG，仅用于开源项目 README。没有输入个人照片、数据库、真实行程或其他项目的图片；风景照片全部为生成示意，不代表用户去过的地方，也不是应用截图。

展示名为“Moments · 方舟旅迹”，副标题为“照片 · 地图 · 时间线”。使用原有合成首图作为编辑输入，由内置 `image_gen` 替换主标题，保留摄影拼贴与轻量时间线；没有使用个人素材。

底图采用居中项目名、中文副标题、摄影拼贴与轻量时间线。参考 [Immich](https://github.com/immich-app/immich) 和 [AppFlowy](https://github.com/AppFlowy-IO/AppFlowy) README 的品牌与图片展示层次，不复制其图片、Logo 或界面。

只有这一张首图被 `.gitignore` 明确允许，其他照片仍被忽略。没有使用 SVG，也没有使用 CLI/API 回退模式。

## 底图生成提示词

```text
Use case: ads-marketing.
Asset type: a finished PNG README cover for the open-source project Moments, a local-first photo annotation and travel timeline tool. Wide panoramic banner, approximately 8:3, high resolution, fully opaque.
Primary request: design an original, exceptionally polished open-source repository header with confident typography and rich photographic imagery. It should feel curated and contemporary, not like a corporate presentation or a stock travel advertisement.
Scene and subject: an airy clean near-white editorial canvas, with an elegant contact sheet of generated travel photography across the lower portion and subtly framing the central title: dramatic alpine lake and pine trees, a sunlit rugged coastline, quiet city architecture, mountain ridges. Photographs must look photorealistic, crisp, detailed, naturally lit and distinct, with attractive balanced colors rather than an overall single-hue tint. No recognizable people or private information.
Composition: the project name is centered, large and immediately legible, with generous breathing room; the exact Chinese subtitle is immediately below, smaller but readable at GitHub README width. The photographs form a cohesive, lightly staggered horizontal composition with fine pale borders, subtle realistic paper depth, and beautifully controlled spacing. A few tiny colored nodes connected by a fine flowing timeline gently connect the imagery without crossing any text. All title and subtitle text stays within safe margins. Avoid a text-left/image-right split. Keep the overall design photographic rather than iconographic.
Text, verbatim, and the only text in the entire image:
"Moments"
"照片 · 地图 · 时间线"
Typography: bold, refined modern sans serif, charcoal title, quieter subtitle, accurate spelling and Chinese characters; do not add taglines, badges, dates, captions or pseudo-UI text.
Constraints: original generated scenery only; not a real application screenshot. No SVG or flat vector illustration appearance, no large world-map silhouette, no oversized map pins, no gradient background, no glowing orbs, no mascots, no third-party branding, no GitHub logos, no device mockups, no extra words, no watermark. Ready to use as a tasteful GitHub project masthead.
```

## 中文名编辑提示词

```text
Use case: text-localization.
Asset type: the PNG README masthead for Moments, now also named 方舟旅迹.
Input image 1: edit target, an original AI-generated photographic README banner. It contains no personal photos or actual travel records.
Primary request: update only the large main title from "Moments" to exactly "Moments · 方舟旅迹". This is a bilingual project name. Render all four Chinese characters correctly: 方 舟 旅 迹, in that order. Keep the separator as a centered dot.
Keep the existing smaller subtitle verbatim: "照片 · 地图 · 时间线".
Composition: retain the same panoramic 2048 by 768 framing, clean near-white background, centered heading, staggered photographic prints, landscape details, fine pale timeline and colored nodes, subtle paper shadows, safe margins and visual balance. Adjust only the main title typography and its font size as necessary to fit the complete bilingual name on one centered line; it must remain bold, elegant, prominent and readable when the banner is displayed at 900 pixels wide. Use a refined sans-serif typeface supporting Chinese, charcoal text; no clipping or overlap with photos. The subtitle stays on its own line beneath it with breathing room.
Invariants: preserve the generated photographs, their positions and lighting, borders, colors and the overall composition. Opaque PNG output, no SVG or flat vector substitution. No extra text, badges, watermark, logos, boats, people, new decorative objects, personal data, or new imagery. Only replace the main project name.
```
