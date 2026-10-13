# Image Generation Brief — Litter Box Monitor

This brief defines the visual assets for `ha-litter-box-monitor`, a ChatGPT prompt to generate them, and a plan for integrating them. **Status (2026-10-13):** the assets were generated and integrated, as section 4 describes. The 6 brand images are in `custom_components/litter_box_monitor/brand/`, and `banner.png`, `sensor-placement.png` and `social-preview.png` are in `docs/images/`. The generation masters and SVG sources are in `docs/images/source/`. To regenerate the assets, keep the reference photos under the names the prompt uses: `Litter Box Front.jpg` and `Litter Box Rear.jpg`. Locally they are stored as `docs/reference/litter-box-front.jpg` and `docs/reference/litter-box-rear.jpg`.

> **Note for ChatGPT (or any image-generation assistant reading this whole document)**
>
> - **Your task is section 3**, "CHATGPT IMAGE GENERATION REQUEST". Generate the images it describes, using the two attached reference photos.
> - **Sections 1, 2 and 4 are context.** They explain where the files will be used and the exact sizes they must end up at. Use them to get the specifications right, but don't treat the repository changes, validation steps or README edits in section 4 as tasks.
> - **Post-processing (section 4.1):** if you can run code, you may apply equivalent trimming, cropping, resizing and optimization yourself, for example with Python and Pillow. Then deliver the final-size files listed in section 2 alongside the masters. If you can't run code, deliver the masters only.
> - Where this document and section 3 seem to disagree, section 3 wins.

---

## 1. Audit of the current repository

| Area | Current state | Visual need |
| --- | --- | --- |
| Images anywhere in repo | None (no PNG/SVG/JPG/WebP) | Everything below is new |
| `custom_components/litter_box_monitor/` | No `brand/` folder | Home Assistant shows a placeholder icon for the integration |
| `icons.json` | Material Design Icons (`mdi:cat`, `mdi:broom`, `mdi:alert`, …) for entity states | **No change needed.** Entity icons must stay MDI glyphs |
| Frontend | None. The integration has no custom cards, panels or dashboards | No UI artwork needed |
| `manifest.json` | No branding fields, and none exist in the schema | No change |
| `hacs.json` | `name`, `homeassistant`, `render_readme: true` | No change. HACS renders the README, so README images appear in HACS |
| `.github/workflows/validate.yml` | HACS action runs with `ignore: brands` | Remove the ignore once `brand/icon.png` exists |
| `README.md` | Text only. Uses an ASCII state-machine diagram. Section 13 lists "Brand icon" as a limitation | Header banner, sensor placement illustration, and removal of the limitation |
| GitHub repository | No social preview | Social preview image |

### Reference hardware

The project was developed using an **ELS Pet Spaceship II**, a globe-style self-cleaning box. The integration runs completely independently of the box: it never communicates with it, and only reads two contact sensors through Home Assistant. The **front/main door** is the door the cat goes in and out through. It closes during the cleaning cycle. The **bag door** at the rear covers the waste storage bay where the cleaning cycle deposits waste, and its sensor reports when the bag door is opened. The reference photos (`docs/reference/`, kept local only) show where the sensors are mounted. The artwork is deliberately a generic, unbranded interpretation: the project isn't affiliated with ELS Pet, and the HA brands rules forbid using other brands' images.

### Verified Home Assistant and HACS branding rules (October 2026)

- **Since Home Assistant 2026.3, custom integrations ship their own brand images** in a `brand/` folder inside the integration directory. The installed Home Assistant 2026.10.1 source confirms it:
  - `homeassistant/components/brands/__init__.py` serves `/api/brands/integration/{domain}/{image}` from `Path(integration.file_path) / "brand"` before falling back to the CDN.
  - `loader.py` detects the folder with `has_branding`.
- **Allowed file names** (from `homeassistant/components/brands/const.py`): `icon.png`, `icon@2x.png`, `logo.png`, `logo@2x.png`, `dark_icon.png`, `dark_icon@2x.png`, `dark_logo.png`, `dark_logo@2x.png`. Only PNG is allowed.
- **Fallbacks**: `dark_icon` → `icon`; `logo` → `icon`; `dark_logo` → `dark_icon` → `logo` → `icon`; `@2x` → 1x. Any missing variant falls back automatically.
- **Size and format rules** (home-assistant/brands README):
  - Icon: 1:1, 256×256, with @2x at 512×512.
  - Logo: landscape, shortest side 128–256 px, with @2x at 256–512.
  - Trim empty space. A transparent background is preferred. Optimize losslessly.
  - Do **not** use Home Assistant's own branded images.
- **The home-assistant/brands `custom_integrations/` folder is now legacy.** No external submission is required. Everything is committed to this repository.
- **HACS brands check**: the check passes when the integration has a brand directory containing at least `icon.png`, and otherwise falls back to the brands repo. Create the release tag **after** the brand files are committed.

Sources: [home-assistant/brands README](https://github.com/home-assistant/brands), [HACS publishing requirements](https://www.hacs.xyz/docs/publish/include/), and the installed `homeassistant==2026.10.1` source.

---

## 2. Asset list and specifications

Seven files are committed in total, plus one optional source copy. The square project icon and the brand icon are the same image. Separate GitHub avatar or favicon versions are not needed.

### Palette

| Token | Hex | Use |
| --- | --- | --- |
| Brand Teal | `#0D9488` | Primary mark. Contrast is at least 3:1 against both white and near-black, so one icon works in both themes |
| Light Teal | `#5EEAD4` | Entrance light ring in the mark, accent text on dark backgrounds |
| Signal Amber | `#F59E0B` | Bag door (sensor 2) marker in the illustration |
| Ink | `#111827` | Wordmark on light backgrounds |
| Night | `#0F172A` | Opaque background for the banner and social preview |
| Paper | `#F8FAFC` | Light text on dark, illustration background |
| Mist | `#E2E8F0` | Light-mode secondary lines and shadows |
| Slate | `#94A3B8` | Secondary text on dark |
| White | `#FFFFFF` | Inner details of the mark |

Typeface for all text: a geometric or grotesque sans similar to **Inter SemiBold** for the wordmark and **Inter Regular** for the tagline.

### Specifications

| # | Final file | Destination | Use | Final size | Ratio | Format / background | Theme | Margins | Small-size rule |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `icon.png` | `custom_components/litter_box_monitor/brand/` | HA integration icon, HACS icon, also the logo fallback | 256×256 | 1:1 | PNG-32, transparent | One file for both themes (no `dark_icon`) | Trimmed to the artwork, then centered on a square canvas. No added padding | Must read clearly at 32×32 and 16×16 |
| 2 | `icon@2x.png` | same | hi-DPI icon | 512×512 | 1:1 | PNG-32, transparent | both | same | same |
| 3 | `logo.png` | same | HA integration logo (light theme), README fallback | height 128, width as trimmed (≈ 560–640) | ≈ 4.5:1 landscape | PNG-32, transparent | Light (Ink text) | Trimmed | Wordmark legible at 128 px height |
| 4 | `logo@2x.png` | same | hi-DPI light logo | height 256 | same | PNG-32, transparent | Light | Trimmed | — |
| 5 | `dark_logo.png` | same | HA logo in dark theme | height 128 | same | PNG-32, transparent | Dark (Paper/Light Teal text) | Trimmed | — |
| 6 | `dark_logo@2x.png` | same | hi-DPI dark logo | height 256 | same | PNG-32, transparent | Dark | Trimmed | — |
| 7 | `banner.png` | `docs/images/` | README header (also rendered by HACS) | 1280×320 | 4:1 | PNG-24, **opaque** Night background | One opaque file works on every README theme, including HACS, which may not support `<picture>` | Keep content at least 64 px from the left and right edges and at least 40 px from the top and bottom | Wordmark at least 72 px tall |
| 8 | `social-preview.png` | GitHub → Settings → Social preview (source copy kept in `docs/images/`) | Link previews | 1280×640 | 2:1 | PNG-24, opaque Night, under 1 MB | Opaque, so theme-independent | Keep content at least 80 px from all edges, because some platforms crop | Readable as a 400 px wide thumbnail |
| 9 | `sensor-placement.png` | `docs/images/` | README §2: where the two contact sensors go | 1536×1024 | 3:2 | PNG-24, opaque Paper background | Light card, which reads acceptably on dark GitHub too | At least 48 px | Markers readable at 720 px display width |

Not requested, and why:

- **`dark_icon` variants**: the single teal mark is designed to work on both backgrounds.
- **A state-machine diagram**: the README's ASCII diagram is exact. AI-generated diagrams with labels are unreliable.
- **Entity icons**: Home Assistant requires MDI glyphs.
- **Dashboard artwork**: there is no frontend.
- **Separate favicon or avatar**: `icon@2x.png` covers it.

---

## 3. ChatGPT prompt

This is the request to act on. The reference photos `Litter Box Front.jpg` and `Litter Box Rear.jpg` are attached to the conversation, and the request refers to them by those names.

---

**CHATGPT IMAGE GENERATION REQUEST — LITTER BOX MONITOR**

I need a small, consistent set of brand and documentation images for an open-source software project. The images will be shipped in the real product, so precision matters more than artistic flourish. Please generate **each image as a separate file**. Do not make a combined mockup, presentation board or collage.

**1. Project**

"Litter Box Monitor" is an open-source custom integration for Home Assistant, the smart-home platform. It turns two ordinary door contact sensors on an automated, self-cleaning cat litter box into a "virtual appliance":

- It detects cleaning cycles.
- It reports a fault when the front/main door stays closed too long.
- It tracks maintenance when the bag door over the rear waste storage bay is opened.
- It keeps statistics.

The audience is smart-home enthusiasts. The personality is reliable, practical, modern, friendly and technically polished. It must sit comfortably next to other Home Assistant integration icons.

**Reference photos (attached)**

I've attached two photos of the actual litter box, an **ELS Pet Spaceship II**: "Litter Box Front.jpg" and "Litter Box Rear.jpg". Use them **only** to understand the overall form and where the sensors are mounted:

- **Front:** the unit is a near-spherical globe on a slightly darker base. It has a large circular entrance at the lower front, surrounded by a glowing light ring. This entrance has the **front/main door**, the door the cat goes in and out through. It closes during the cleaning cycle and reopens afterwards. A white contact sensor on the top rim of the entrance detects it.
- **Rear:** the back of the globe is a large curved **bag door** marked by a seam, with a recessed grip near its top and a slot handle near its bottom. It covers the waste storage bay, where the cleaning cycle deposits waste. A two-piece white contact sensor at the bag door's lower-left edge reports when the bag door is opened. Its small magnet block sits directly above the larger sensor body.

The software never connects to the litter box itself. It only reads these two contact sensors through Home Assistant. Don't add app screens, Wi-Fi or Bluetooth symbols, or anything else implying a direct connection to the litter box.

Do **not** copy anything else from the photos: no room, pipes, floor mat or clutter, no product logos, no exact product styling, and no photographic look. Every image must be a simplified, unbranded, flat vector interpretation. This is an independent project, not affiliated with ELS Pet, so never show or write the ELS Pet name or logo, and don't make anything look like official ELS Pet product artwork.

**2. Visual identity**

- **Style**: flat, clean vector look built from simple geometric shapes, with consistent rounded corners. Use no gradients, or only an extremely subtle one. Use no textures, no photorealism, no 3D rendering, no drop shadows on the mark, and no outlines around the whole mark.
- **Tone**: friendly but not cute. No cartoon cat faces, eyes, whiskers, paws or mascots. No childish styling.
- **Palette**: use only these colors.
  - Brand Teal `#0D9488` (primary)
  - Light Teal `#5EEAD4` (the entrance light ring in the mark; accent on dark backgrounds)
  - Signal Amber `#F59E0B` (only for the bag door marker in the sensor illustration)
  - Ink `#111827` (text on light)
  - Night `#0F172A` (dark backgrounds)
  - Paper `#F8FAFC` (light text and light backgrounds)
  - Mist `#E2E8F0` (light-mode secondary lines)
  - Slate `#94A3B8` (secondary text on dark)
  - White `#FFFFFF`
- **Typography**: clean geometric sans serif similar to Inter. SemiBold for the name and Regular for taglines. Use sentence spacing with no letter-spacing tricks.
- **Things to avoid**:
  - The Home Assistant logo, its house-shaped mark, or its blue `#18BCF2` / `#03A9F4`.
  - Any real litter box brand, logo or exact product likeness. The reference photos inform the general globe shape only.
  - Brand names, watermarks, signatures or extra text beyond what is specified.

**3. The core mark (reused everywhere)**

A front-facing, simplified silhouette of the globe-style automatic litter box from the reference photos, built from a few geometric shapes:

- **Globe**: a large solid **Brand Teal** circle.
- **Base**: a short, wide, solid **Brand Teal** pill or rounded rectangle under the globe, about 80% of the globe's width. It is separated from the globe by a thin **transparent** gap, so the background shows through in both light and dark themes.
- **Cat ears**: two small, slightly rounded triangular ears rise from the top of the globe, in the same Brand Teal and merged with the globe. They make the silhouette read as "cat" at a glance.
- **Entrance**: a large circle, about 50% of the globe's diameter, placed **off-center towards the lower left** of the globe, as on the real unit. The offset is important because it stops the mark reading as a face. It has:
  - a **White** filled disc;
  - a thick **Light Teal `#5EEAD4` ring** around the disc, about 6% of the globe's diameter, echoing the real entrance's light ring and acting as the "status light".
- **Activity line**: inside the white disc, a bold **Brand Teal** line runs horizontally, like a simple heart-rate or pulse line with one sharp peak. This conveys "monitoring".

No eyes, nose, mouth, whiskers or other details. Every stroke and gap must be thick enough to stay distinct when the mark is shrunk to 32×32 pixels. The minimum feature size is about 1/16 of the mark's width.

**4. Images to create**

Your image tool may not hit exact pixel sizes. If it can't, please generate the **master canvases** listed below at the sizes your tool supports, with the subject placed as described. I will trim and resize them deterministically. For every image:

- Keep edges crisp and colors flat and exact.
- Use transparency only where requested.
- Add nothing outside the described content.

**Image A — `master_icon.png`**

- Canvas 1024×1024, **fully transparent background** with a real alpha channel, not a checkerboard pattern.
- The core mark alone, centered, filling about 90% of the canvas width. No text.
- It must look good on both white and near-black backgrounds without changes.
- Final deliverables cut from it: `icon.png` 256×256 and `icon@2x.png` 512×512, both trimmed tightly to the artwork and centered on a square transparent canvas.

**Image B — `master_logo_light.png`**

- Canvas 1536×1024, **transparent background**.
- A single horizontal lockup, centered vertically:
  - The core mark on the left.
  - The wordmark **"Litter Box Monitor"** on the right, spelled exactly like that on one line.
  - "Litter Box" is in **Ink `#111827`** and "Monitor" is in **Brand Teal `#0D9488`**.
  - The cap height is about 45% of the mark's height, and the text is vertically centered on the mark.
  - The gap between mark and text is about 35% of the mark's height.
- The lockup should span about 85% of the canvas width. No tagline.
- Final deliverables: `logo.png` at 128 px tall and `logo@2x.png` at 256 px tall, trimmed tightly, transparent, for **light** backgrounds.

**Image C — `master_logo_dark.png`**

- Identical to Image B in layout, size and position, so the two overlay perfectly.
- Only the wordmark colors change: "Litter Box" in **Paper `#F8FAFC`** and "Monitor" in **Light Teal `#5EEAD4`**.
- The mark itself is unchanged.
- Final deliverables: `dark_logo.png` at 128 px tall and `dark_logo@2x.png` at 256 px tall, for **dark** backgrounds.

**Image D — `master_banner.png`**

- Canvas 1536×1024, **opaque** solid **Night `#0F172A`** background.
- All content sits inside the **centered horizontal band 1536×384**, which spans y = 320 to y = 704. Outside that band, use only plain Night background, because it will be cropped away.
- Inside the band:
  - The core mark on the left.
  - To its right, the wordmark "Litter Box Monitor", with "Litter Box" in Paper and "Monitor" in Light Teal.
  - Below the wordmark, the tagline **"Cleaning, fault and maintenance tracking for automated litter boxes"** in Slate `#94A3B8`, spelled exactly.
  - Along the bottom of the band, a thin Brand Teal activity line with a single peak, echoing the mark and running at low emphasis across the width.
- Keep all content at least 80 px from the band's left and right edges.
- Final deliverable: `banner.png` at 1280×320.

**Image E — `master_social_preview.png`**

- Canvas 1536×1024, **opaque** Night background.
- All content sits inside the **centered band 1536×768**, which spans y = 128 to y = 896. Outside the band, use plain Night background.
- Centered composition:
  - The core mark, large, above.
  - Below it, the wordmark "Litter Box Monitor" in Paper and Light Teal.
  - Below that, the line **"A custom integration for Home Assistant"** in Slate, spelled exactly.
  - A subtle Brand Teal activity line across the lower part of the band.
- Keep everything at least 100 px from the band edges.
- Final deliverable: `social-preview.png` at 1280×640, under 1 MB.

**Image F — `sensor-placement.png`**

- Canvas 1536×1024, **opaque** Paper `#F8FAFC` background.
- A flat vector illustration in the same style and palette, based on the attached reference photos but simplified and unbranded. Show **two views side by side** of the same globe-style litter box, each occupying one half of the canvas.
- Draw the unit with:
  - a Slate `#94A3B8` globe;
  - an Ink `#111827` base;
  - Ink line details;
  - a soft Mist floor ellipse under each view.
- **Left view, three-quarter front.** The large circular entrance at the lower front, where the cat goes in and out, with a Light Teal glowing ring and an Ink interior. Show the front/main door open, as when idle.
  - **Sensor 1:** a small White rectangular contact sensor mounted on the outer rim at the **top (12 o'clock) of the entrance**.
  - Highlight it with a **Brand Teal** circular marker containing the White numeral **"1"**, connected by a short leader line.
- **Right view, three-quarter rear.** The back of the globe with the large curved bag door over the waste storage bay, outlined by a seam line, with a recessed grip near its top and a slot handle near its bottom.
  - **Sensor 2:** a two-piece White contact sensor, with a small magnet block directly above a larger sensor body, mounted at the **lower-left edge of the bag door** where it meets the housing.
  - Highlight it with a **Signal Amber** circular marker containing the Ink numeral **"2"**, connected by a short leader line.
- No other text, labels, arrows, cats, people, logos or background scenery.
- Keep everything at least 48 px from the edges.

**5. Consistency requirements**

- The core mark must be **pixel-identical in shape and color** in images A to E. Generate it once and reuse it. Do not redraw it with variations.
- Use the same corner radius language, line weights and palette everywhere.
- Text must be spelled exactly as written. If you cannot render text reliably, produce Images B to E **without text** and leave the text area empty. I will typeset the text myself.

**6. Light/dark compatibility**

- Image A must work unchanged on `#FFFFFF` and on `#111111`.
- Image B is for light backgrounds and Image C is for dark backgrounds.
- Images D, E and F are opaque and carry their own background.

**7. Delivery**

- Provide each image as an individually downloadable PNG, using exactly these file names:
  - `master_icon.png`
  - `master_logo_light.png`
  - `master_logo_dark.png`
  - `master_banner.png`
  - `master_social_preview.png`
  - `sensor-placement.png`
- Where requested, transparent images must have a true alpha channel.
- If your tool can also output the exact final sizes listed above, provide those too, named `icon.png`, `icon@2x.png`, `logo.png`, `logo@2x.png`, `dark_logo.png`, `dark_logo@2x.png`, `banner.png` and `social-preview.png`.
- If you can create a ZIP archive, also bundle all files into `litter-box-monitor-assets.zip`.
- If you can produce SVG versions of the mark and logos, include `mark.svg`, `logo_light.svg` and `logo_dark.svg` as well.

These are production assets for software distribution. Please keep them clean, crisp and free of artifacts, stray marks and extra elements.

---

## 4. Integration plan

### 4.1 Post-processing

The commands below use ImageMagick 7 and oxipng (`brew install imagemagick oxipng`). Run them in a scratch folder holding the ChatGPT downloads. These commands haven't been run yet because neither tool was installed when this brief was written. Check the outputs with `magick identify`.

```bash
REPO=~/git/ha-litter-box-monitor
B=custom_components/litter_box_monitor/brand; D=docs/images; mkdir -p "$REPO/$B" "$REPO/$D"

# Icon: trim, then pad to a square transparent canvas, then resize
for s in 256:icon 512:icon@2x; do
  magick master_icon.png -trim +repage -background none -gravity center \
    -extent "%[fx:max(w,h)]x%[fx:max(w,h)]" -resize ${s%%:*}x${s%%:*} "$REPO/$B/${s#*:}.png"
done

# Logos: trim and scale to height
magick master_logo_light.png -trim +repage -resize x128 "$REPO/$B/logo.png"
magick master_logo_light.png -trim +repage -resize x256 "$REPO/$B/logo@2x.png"
magick master_logo_dark.png  -trim +repage -resize x128 "$REPO/$B/dark_logo.png"
magick master_logo_dark.png  -trim +repage -resize x256 "$REPO/$B/dark_logo@2x.png"

# Banner and social preview: crop the band, then resize
magick master_banner.png -gravity center -crop 1536x384+0+0 +repage -resize 1280x320! "$REPO/$D/banner.png"
magick master_social_preview.png -gravity center -crop 1536x768+0+0 +repage -resize 1280x640! "$REPO/$D/social-preview.png"
cp sensor-placement.png "$REPO/$D/"

oxipng -o 4 --strip safe "$REPO/$B"/*.png "$REPO/$D"/*.png
```

If ChatGPT can't render the text correctly, typeset the wordmark and tagline in Inter onto the text-free masters, in SVG or a design tool, using the colors in §2. Then run the same commands.

### 4.2 Where each file goes

| File | Location | External submission? |
| --- | --- | --- |
| `icon.png`, `icon@2x.png`, `logo.png`, `logo@2x.png`, `dark_logo.png`, `dark_logo@2x.png` | `custom_components/litter_box_monitor/brand/` | **No.** Home Assistant 2026.3+ serves these locally, and the home-assistant/brands `custom_integrations/` folder is legacy |
| `banner.png`, `sensor-placement.png` | `docs/images/` | No |
| `social-preview.png` | `docs/images/` (source copy) | Upload manually in GitHub → Settings → General → Social preview |

### 4.3 Repository changes once the images exist

0. **Reference photos**: these are kept in `docs/reference/`, which `.gitignore` excludes. They show the room around the box and add about 4.7 MB. They contain no GPS data, only the camera model and capture time.

1. **README.md**
   - Add the banner under the title: `![Litter Box Monitor](docs/images/banner.png)`. Use a plain image with no `<picture>` element, because the banner is opaque and HACS may not support `<picture>`.
   - In section 2 (Hardware assumptions), add `![Sensor placement: 1 front/main door, 2 bag door](docs/images/sensor-placement.png)` with a legend: **1** front/main door sensor, **2** bag door sensor.
   - In section 13 (Limitations), delete the "Brand icon" bullet.
2. **`.github/workflows/validate.yml`**: remove `ignore: brands` and its comment from the HACS step.
3. **`manifest.json` and `hacs.json`: no changes.** Home Assistant detects the `brand/` folder automatically, and HACS has no image settings.
4. **Releases**: commit the brand folder first, then create the `v0.1.0` tag. Tags created before the brand files existed are seen as brand-less.
5. The release zip already includes everything in `custom_components/litter_box_monitor/`, so `brand/` ships with manual installs too.

### 4.4 Validation in both themes

- **Automated**
  - Run `docker run --rm -v "$PWD:/github/workspace:ro" ghcr.io/home-assistant/hassfest`.
  - The HACS action, with the brands check now enabled, should pass.
  - `magick identify custom_components/litter_box_monitor/brand/*.png` should show the expected sizes, with `icon*` square and logos 128 or 256 px tall.
- **Home Assistant (2026.10+)**
  1. Restart after installing.
  2. Open `http://<ha>/api/brands/integration/litter_box_monitor/icon.png` and `…/dark_logo.png` in a browser to confirm they are served locally.
  3. Look at Settings → Devices & services and the "Add integration" dialog with **Profile → Theme** set to Light and then Dark.
  4. Hard-refresh to bypass the browser cache.
- **Small sizes**
  - Run `magick icon@2x.png -resize 32x32 /tmp/i32.png` and `-resize 16x16`. Check that the ears, globe/base gap, entrance ring and activity line stay distinct on white and on `#111111`.
- **GitHub and HACS**
  - View the README with GitHub's Light, Dark and Dark dimmed themes.
  - Open the repository in HACS in both Home Assistant themes.
  - Paste the repository URL into a chat app to check the social preview.
- **Text**: confirm "Litter Box Monitor" and each tagline are spelled exactly.
