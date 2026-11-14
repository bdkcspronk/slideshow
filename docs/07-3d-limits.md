# 7. What the TV PC's graphics can do (for 3D slides)

[Manual](README.md). Measured on the TV PC itself (Intel HD Graphics, 1920x1080, Firefox 159 kiosk) on 13 November 2026 with a
3D benchmark (since removed from the slideshow). Read this before making a slide with Three.js (or any 3D in the browser).

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

Both of the first two together are probably what a real 3D slide needs; check it on the TV itself.

## A slide in 3D: the books

The books slide (`static/books_3d.js`) is built to this budget. Its bookcase (room for 100 books, all in one mesh with one texture
holding every spine) doesn't move, so it is drawn only once and copied onto a plain canvas behind; every frame draws only the three
books taken out of it (15 draw calls, a few thousand triangles, 7 textures, no shadows) on one canvas over the whole screen, mostly see-through. The glows and
all text stay HTML. If its frames still take over 20 ms in its first seconds, it draws at 75% resolution from then on (it says so in
the browser console); without WebGL it shows the covers flat, without a bookcase. Antialiasing is on: turning books have edges that
would flicker without it; check on the TV that it doesn't fall back to 75%. Copy its approach for a new 3D slide: whatever stands
still, draw once.

## A slide in 3D: the bieruur countdown

The bieruur countdown (`static/bieruur_3d.js`) shows the time left (HH:MM:SS) on split flaps in a display hanging on the wall,
with smaller colour flaps around it that flip in waves (the canvas is see-through: the wall is the slide's background, white plaster). All flaps are one `InstancedMesh` drawn by a
small shader from one texture with every letter (each flap the black window and three thin boxes: the two fixed halves and
the falling flap). With the display's case (a box) and its soft shadow on the
wall (one small see-through plane) that is 3 draw calls and some 4,000 triangles.
It shows the right time from the first frame and only draws when a flap falls: once a second, and during the waves of the
colour flaps (about a second every few seconds; some 110 flaps in all). It reads the time from the
slide's text (the `data-live` element the player updates every second), which is shown without WebGL. Like the books it
drops to 75% resolution when its first flips are slow.
At bieruur itself the same display parties: every flap turns to a colour, then the colours flow over the flaps like a fluid (a small fluid simulation in JavaScript, some 1,000 cells, a fraction of a millisecond a step; each flap shows the colour under it),
and some 180 pieces of confetti (one more `InstancedMesh`, 4 draw calls in all) fall in front of it. Then it draws every
frame, for the two minutes until the takeover ends.
The falling flaps have motion blur (`FLAPS.blur`): each falling flap is drawn again 8 times (the time's big flaps 16), see-through, at the angles it
went through during the whole frame (a 360-degree shutter). That is one more draw call, with room for 16 ghosts on every flap: some
35,000 triangles through the vertex shader, of which some 18,000 are drawn while everything falls at once, at the burst (a small
flap's spare ghosts and the ghosts of flaps standing still are dropped before anything is drawn).
