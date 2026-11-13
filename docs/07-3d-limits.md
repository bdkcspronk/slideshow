# 7. What the TV PC's graphics can do (for 3D slides)

[Manual](README.md). Measured on the TV PC itself (Intel HD Graphics, 1920x1080, Firefox 159 kiosk) on 13 November 2026 with the
3D benchmark: [benchmarks/3d-2026-11-13-1657.md](../benchmarks/3d-2026-11-13-1657.md) has every number. Read this before making a slide
with Three.js (or any 3D in the browser).

**In short: the TV PC is weak at 1920x1080, and what limits it is pixels.** A 3D slide that should stay smooth needs a small scene,
antialiasing off, and preferably fewer pixels (`renderer.setPixelRatio(0.5)` or `0.75`; on a TV seen from across the room that barely shows).

## The budget at full resolution (1920x1080, antialiasing on)

| What | Still smooth (60 fps) | Too much |
|---|---|---|
| See-through layers covering the whole screen (glows, fades, fog planes) | 1 | 2: 53 fps; 5: 32 fps |
| Triangles (a cube of spheres filling much of the screen) | under 50,000 | 50,000: 53-56 fps with stutter |
| Separate meshes (draw calls) | 100 | 250: 58 fps with stutter |
| Different 512x512 pictures (like book covers) | 10 | 40: 58 fps with stutter |
| One big texture | 2048x2048 | 4096x4096 and up: stutter (8192 takes half a second to upload) |
| Shadows | none | even 100,000 lit triangles on a lit floor without shadows: 41 fps; a 512 shadow map: 29 fps |
| Moving objects from JavaScript every frame | 20,000 (2 ms) | 60,000 (6 ms) |

## What helps

| Change | Measured |
|---|---|
| **Half the resolution** (`renderer.setPixelRatio(0.5)`) | 2 full-screen layers: 53 -> 60 fps |
| **Antialiasing off** (`new THREE.WebGLRenderer({ antialias: false })`) | 100,000 lit triangles: 46 -> 55 fps; 5 full-screen layers: 32 -> 49 fps |
| Fewer, simpler objects | instancing saves draw calls, not pixels or triangles |
| No shadows, no full-screen see-through effects | the two most expensive things here |

Both of the first two together are probably what a real 3D slide needs; check it with the "Three.js test" slide (below), which has
buttons for the resolution.

Earlier numbers on this page (from the "Three.js test" slide by eye) were too optimistic: that slide drew at 736x414 pixels then
(the PC had display scaling of 2.6), a seventh of the screen. The benchmark runs before `3d-2026-11-13-1657` in `benchmarks/` are not
usable either (too few pixels, or a way of measuring that made everything look slower than it is).

## A slide in 3D: the books

The books slide (`static/books_3d.js`) is built to this budget. Its bookcase (room for 100 books, all in one mesh with one texture
holding every spine) doesn't move, so it is drawn only once and copied onto a plain canvas behind; every frame draws only the three
books taken out of it (15 draw calls, a few thousand triangles, 7 textures, no shadows) on one canvas over the whole screen, mostly see-through. The glows and
all text stay HTML. If its frames still take over 20 ms in its first seconds, it draws at 75% resolution from then on (it says so in
the browser console); without WebGL it shows the covers flat, without a bookcase. Antialiasing is on: turning books have edges that
would flicker without it; check on the TV that it doesn't fall back to 75%. Copy its approach for a new 3D slide: whatever stands
still, draw once.

## A slide in 3D: the activities

The activities slide (`static/activities_3d.js`) is a split-flap display per activity. All flaps of a display are one
`InstancedMesh` drawn by a small shader from one texture with every letter (each flap 5 quads: the black window, the two
fixed halves and the falling flap's two sides), so with its housing and its shadow on the wall (a blurred picture, not
a shadow map) a display costs 3 draw calls: at most about 30 for the slide, some 10,000 triangles, 2 textures. The white
wall behind is the slide's CSS background. Where each display goes and how big it is comes from the cards in
the HTML (hidden in 3D, shown without WebGL). Like the books it drops to 75% resolution when its first seconds are slow.

## The benchmark: measuring again (a new PC, a new browser, a new slideshow version)

On the TV PC press Esc -> Fun -> "3D benchmark" and tap **Start** (or press Enter). It takes about 3 minutes; leave the PC alone
(and not near bieruur: that takes over the screen). It runs these tests, each getting heavier until a step no longer holds 60 fps:

| Test | Finds out |
|---|---|
| Triangles, unlit and lit | the most triangles per frame |
| Separate meshes | the most draw calls (many small objects) |
| Shadows | what a shadow map of 512 to 4096 costs on a 100,000 triangle scene |
| Overdraw | the most full-screen see-through layers, and whether half the resolution helps |
| Textures, one big texture | how many pictures (like book covers) can be loaded, flown into until one is shown 1:1, and how long uploading them takes |
| Antialiasing on and off | what the smoothing of edges costs (it is on in the slides; off is the cheapest way to win back speed) |
| Moving instances | how many objects JavaScript can move every frame |

At the end the results are saved in [benchmarks/](../benchmarks/README.md) as `3d-<date>.json` and `3d-<date>.md`. **Commit them
from the TV PC** (`git add benchmarks && git commit -m "3D benchmark" && git push`; until then the automatic updates wait, because the
PC has changes of its own), then update the tables above with the new numbers and the link to the results file.

Each step is drawn exactly as a slide would draw it. "Holds 60 fps" means at least 57 fps with 95% of the frames within 20 ms (no
stutter). The frame rate can't go above the screen's 60, so the headroom shows only as the step where it drops; the steps double.
The panel and the results also show which graphics chip is used ("llvmpipe" or "SwiftShader" means no GPU is used and 3D will be slow).

There is also the older "Three.js test" slide (not in the rotation; Esc -> Fun -> "Three.js test"):
seven scenes you can switch between by tapping (or S and R), at 100%, 75% or 50% resolution, with a live fps panel. Handy for looking at a scene
with your own eyes. The code is in `providers/three.py`, `static/widgets.js` and `static/three_benchmark.js`.
