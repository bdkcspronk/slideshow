# 7. What the TV PC's graphics can do (for 3D slides)

[Manual](README.md). Measured on the TV PC itself (1920x1080, Firefox kiosk) in November 2026 with the Three.js test slide
(`providers/three.py`, the scenes are in `static/widgets.js`, `THREE_SCENES`). Read this before making a slide with Three.js
(the 3D books slide, a new 3D scene, ...).

> **These numbers are provisional.** They were read off the old test slide by eye at a pixel ratio of 2.6, so it drew only 736x414
> pixels, about a seventh of the screen; anything about pixels (overdraw, textures, shadows) was too optimistic. The benchmark runs of
> 13 November 2026 in `benchmarks/` are not usable either: the first two drew at 736x414 too, and all four waited for the graphics chip
> after every frame, which made even one textured square miss 60 fps. Both are fixed; run the benchmark again and replace the
> tables with its results.

## The budget

| What | Limit | Measured |
|---|---|---|
| Triangles per frame | **about 2 million at 60 fps; stay at 500,000 or fewer** to leave room for lighting and the browser | 4 million unlit triangles: about 30 fps. Roughly 100-120 million triangles per second in total. |
| Shadows | **a shadow pass draws everything a second time**: count the triangles double. Avoid for big scenes | 4 million triangles with shadows: 9-11 fps |
| Many separate meshes | 400 meshes (400 draw calls) with 3 lights and fog is fine | 60 fps |
| Translucent layers on top of each other (overdraw) | about 20 full-screen layers at full resolution; about twice that at 75% | 60 layers: 24 fps at 100%, 60 fps at 50% resolution |
| Lit, solid objects | 1,000 lit spheres (340,000 triangles), two lights | 60 fps |

What limits it:
- **Triangles are the bottleneck**, not pixels: lowering the resolution did not help the triangle-heavy scenes at all.
  Instancing does not help either (it saves draw calls, not triangles). Use fewer or simpler objects: a sphere of 16x12 segments is plenty.
- **Only stacked translucent layers are limited by pixels.** For those, render at a lower resolution (`renderer.setPixelRatio(0.5)`).

## The results per scene

| Scene | What it is | fps |
|---|---|---|
| Simple | a knot and a cube, one light | 60 |
| Medium | 400 meshes, fog, 3 lights, reflective floor | 60 |
| Heavy | 1,000 lit spheres, 340,000 triangles | 60 |
| Shadows | 300 spheres, 2048 shadow map | 40-45 |
| Triangles | 6,000 unlit spheres, 4 million triangles | about 30 (the same at 50% resolution) |
| Overdraw | 60 additive translucent layers | 24 (60 at 50% resolution) |
| Complex | 4 million triangles with shadows, 30,000 points, detailed knot | 9-11 (the same at 50% resolution) |

(The shadows scene is slower than its 100,000 triangles suggest: a 2048 shadow map on a floor the size of the screen costs more than the geometry.)

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
PC has changes of its own), then update the tables above with the new numbers.

Each step is drawn exactly as a slide would draw it. "Holds 60 fps" means at least 57 fps with 95% of the frames within 20 ms (no
stutter). The frame rate can't go above the screen's 60, so the headroom shows only as the step where it drops; the steps double.
The panel and the results also show which graphics chip is used ("llvmpipe" or "SwiftShader" means no GPU is used and 3D will be slow).

There is also the older "Three.js test" slide (in the rotation by default; take `three` out of `rotation.order` when you are done with it):
seven scenes you can switch between by tapping (or S and R), at 100%, 75% or 50% resolution, with a live fps panel. Handy for looking at a scene
with your own eyes. The code is in `providers/three.py`, `static/widgets.js` and `static/three_benchmark.js`.
