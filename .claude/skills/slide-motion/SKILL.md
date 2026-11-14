---
name: slide-motion
description: Motion, interaction and shape rules for the Francken TV slideshow. Use when making or changing a slide's animations, transitions, easing or timing; when giving anything corners (cards, buttons, covers, photos: continuous corners, not border-radius); when building or reviewing anything people tap on the TV (buttons, puzzles, Spotify, news, the pet, the menu); when a tap redraws a slide; when adding 3D or other heavy visuals; or when asked to review or polish a slide's motion ("review the news slide", "does this feel right", "make this snappier").
argument-hint: "[slide name or file] [review]"
---

# Slide motion

Rules for how things move on the Francken TV. They are adapted from Emil Kowalski's design-engineering
skills (github.com/emilkowalski/skill: emil-design-eng, animate, choreograph, animation-performance).
His rules are written for apps people work in. This slideshow differs in four ways, and every rule below
follows from them:

1. **It's watched from across the room.** Most slides are posters that play to people who aren't touching
   anything. Here motion is the point, and it may be long, theatrical and springy.
2. **It's also a touchscreen.** When someone walks up and taps, they are using an app, and Emil's rules for
   apps apply: answer at once, keep it short, and never make them wait for an animation.
3. **Every tap goes to the server.** `sendAction()` in `static/player.js` posts the action and swaps in the
   slide's new HTML. Without care, every tap replays every entrance animation on the slide.
4. **The TV PC is weak.** Intel HD Graphics at 1920x1080 in Firefox kiosk, limited by pixels
   (`docs/07-3d-limits.md`). Your development machine is not a test of smoothness.

If `$ARGUMENTS` names a slide, work on that slide: its template in `francken_tv/templates/slides/`, its
section in `francken_tv/static/style.css` and its provider in `francken_tv/providers/`. If it says
"review", follow **Reviewing** at the end.

## First: is this the Show or the Use?

Decide this for every animation before choosing a curve or a duration.

| | **Show**: the slide playing to the room | **Use**: someone at the screen |
|---|---|---|
| Examples | posters, promos (Compucie, Borrelcie, MScie...), charts growing, cards coming in when the slide appears | pressing a button, typing, switching a tab or outlet, a puzzle's answer, a pop-up message |
| Duration | 0.5-1.5 s per element; a sequence may take several seconds | 0.1 s press, 0.15-0.3 s response, at most 0.6 s for content that changes |
| Delay | fine, for choreography | none: the first frame of the answer moves |
| Curves | springy overshoot allowed and welcome | `ease-out`, or a small overshoot only for a celebration (a win, a high score) |
| Repeats | once per showing | as often as people tap, so it has to stay pleasant the 50th time |

A slide is often both. The news slide's cards wave in when the slide comes round (Show), but switching
outlet is Use. The same element can need two timings: see "Redraws" below.

## Easing

The curves this codebase already uses. Reuse them rather than inventing new ones.

| What moves | Curve |
|---|---|
| Show entrance, with a playful overshoot (the house curve) | `cubic-bezier(0.2, 0.9, 0.3, 1.2)` (1.1 for subtler, 1.3 for bouncier) |
| Show entrance, no overshoot, long settle | `cubic-bezier(0.2, 0.8, 0.3, 1)` |
| Anything appearing in answer to a tap | `ease-out` |
| Something moving or morphing while on screen (a tile sliding to a new place, a flip) | `ease-in-out` |
| Loops, progress bars, marquees, things at constant speed | `linear` |
| Falling, speeding up, wind-ups before a throw, exits nobody waits for | `ease-in` |
| Frame-by-frame swaps (sprite frames, a delayed colour change) | `steps(1, end)` |

**`ease-in` never answers a tap.** It starts slowly, at exactly the moment the person is watching for a
reaction. That covers pop-ups, pressed states and anything appearing after an action. It is right for
gravity (the digger's falling earth, lyric lines dropping away) and for exits.

**The `animation` shorthand's curve applies to every segment between keyframes.** A pop-up written as
`animation: msg 2.5s ease-in` with keyframes `0%`, `8%, 80%`, `100%` comes *in* with ease-in too. Give the
entrance segment its own curve:

```css
@keyframes connections-message {   /* in with ease-out (it answers a tap), out with the ease-in from the animation */
	0% { opacity: 0; transform: translate(-50%, 1vh); animation-timing-function: ease-out; }
	8%, 80% { opacity: 1; transform: translate(-50%, 0); }
	100% { opacity: 0; transform: translate(-50%, 0); }
}
```

**Nothing appears from nothing.** Start entrances at `scale(0.6-0.96)` with `opacity: 0`, not `scale(0)`,
except for small things that really pop (confetti, the pet's pop-ups).

## The Use rules

### Every button shows the press

Anything tappable gets a pressed look while the finger is on it. The touchscreen gives no other feedback.

```css
.my-button { transition: transform 0.1s ease-out; }
.my-button:active:not(:disabled) { transform: scale(0.95); }   /* 0.97 for big cards and rows */
```

- Transition only `transform` (or `background` for rows and keys that change colour instead). Never
  `transition: all`.
- Don't put a transition on `background` of buttons whose colour is animated by a keyframe (the Wordle
  keys' `key-update`): the animation wins and the transition does nothing.
- Look at the existing rules first. Puzzles, Spotify, news and the poll all have them, so match their scale.

### Waiting for the server is visible

- A tapped `[data-action]` button gets `.busy` until the answer is back (`player.js` adds it; the shared
  look is in `style.css`: dimmed to 0.55 and scaled to 0.95). Enter on an on-screen keyboard does the same
  through `submit()`. Don't add a second loading indicator for a normal action.
- If a slide's buttons already have a "busy" colour (Spotify's turn green), make sure the busy state still
  differs from the normal one (the green Search button dims instead).
- Something handled in the browser alone (selecting a Connections tile, typing a letter, TimeGuessr's year
  nudges) changes at once, with no animation beyond the press.

### Redraws don't replay the slide

After a tap the server sends the whole slide back, and `redraw()` in `player.js` swaps it in. CSS
entrances replay, so a tap can empty the screen and rebuild it, which is the worst thing Use motion can do.

- Give every element that should stay put a `data-steady="<value>"`. If the redraw brings back an element
  with the same value, it gets the class `.steady`, and `[data-steady].steady { animation: none; }` stops
  its entrance. The value says what makes it "the same": a fixed name for a title (`news-title`), the
  cover's URL for Spotify's cover (so a new song still comes in).
- `.steady` only stops the element's *own* animation. If the entrance is on its children or a
  pseudo-element, add a rule for them:
  ```css
  .news-slide .poster-title.steady span, .news-feeds.steady li { animation: none; }
  ```
- Content that really changes (new headlines, new results) may come in again, but as Use motion: no
  initial delay, short stagger, short duration:
  ```css
  .news-cards.steady li { animation-duration: 0.6s; animation-delay: calc(var(--i) * 0.08s); }
  ```
- A value that updates every second (a clock, a volume bar) shouldn't redraw at all: mark it `data-live`
  and `refresh()` updates it in place. Return `None, None` from the provider's `action()` when nothing
  else changed (see Spotify's volume).
- For motion that has to happen *before* the new HTML replaces the old (Connections' tiles hopping into
  the top row), add an entry to `effects` in `player.js` and put `data-effect="<name>"` on the new slide.

### Messages after an action

Use the pop-up pattern of `.connections-message` and `.spotify-message`: absolutely positioned,
`pointer-events: none` so taps reach what's beneath, in with ease-out in about 0.2 s, held, out with
ease-in. Don't block the screen with them.

### Don't animate typing

Keys, letters in tiles and the cursor appear instantly. Something done many times a minute shouldn't
animate (Emil: "animation on keyboard action → remove it"). The press look on the key is enough.

## The Show rules (choreography)

- **One entrance per container.** If a panel flies in, its contents are already on it. Don't also
  stagger the children in after it.
- **Lead with what matters.** The title or the main picture comes first, then the details. Secondary
  motion (sparkles, glows, a glint over a name) follows the moment that matters: it doesn't run alongside it.
- **Don't stagger like a metronome.** Vary delays by importance, or give the first item a head start.
  Stagger steps of 0.1-0.35 s for Show, at most 0.08 s for Use.
- **Hold long enough to read from across the room.** Text needs a few seconds standing still after it
  lands. A slide's total time is set in `config/config.toml`, so check that the sequence fits in it.
- **Ambient loops are slow and cheap.** Bobbing, swaying and glowing loops run for the whole slide on the
  weak PC. Use `transform`/`opacity`, 2-6 s periods, `ease-in-out ... infinite alternate`.
- **Interaction never waits on choreography.** On an interactive slide, buttons work from the moment they
  are visible.

## Performance on the TV PC

- **Animate `transform` and `opacity`.** `width`, `height`, `top`, `left`, `margin` and `padding` force
  layout every frame; `box-shadow`, `border-radius`, `color` and backgrounds repaint every frame. Use
  `scale()`/`translate()` instead (the nyan cat's bob: "translate, not margin: no relayout each frame").
  Small elements that already animate a paint property (a 1 vh volume bar) are fine. Don't spread it.
- **Use separate `translate`/`scale`/`rotate` properties** when two animations move the same element (one
  bobbing, one swaying). Otherwise they both set `transform` and the second one wins.
- **Pixels are what's expensive.** At most one see-through layer may cover the whole screen (glows, fades,
  fog, a full-screen `filter: blur`). Two already drop it to 53 fps.
- **3D (Three.js)**: read `docs/07-3d-limits.md` first. Antialiasing off or `setPixelRatio(0.75)`, no
  shadows, instancing, draw only when something moves, and draw anything that stands still once (the
  bookcase). Fall back to plain HTML without WebGL.
- **Never conclude it's smooth from your own machine.** Say what you checked in code and what has to be
  looked at on the TV PC.

## Corners: continuous, not rounded

Don't give boxes plain rounded corners (`border-radius: 1.6vh`). Give them **continuous corners** (a
squircle): the curve starts gradually out of the straight edge instead of a circle arc joining it abruptly,
as on Apple's icons and cards. On a TV-sized card the difference is visible from across the room.

**`corner-shape: squircle` does not work on the TV.** It is the native CSS way, but only Chromium has it;
the TV PC runs Firefox. The slideshow draws the outline with `clip-path: shape()` instead (Firefox 148+,
Chrome 135+). The helper is in `style.css`:

```css
/* Continuous corners, as Apple's and Figma's (60% smoothing): --r is how far each corner reaches along the
   edges; its middle is a circle arc of radius --r / 1.6, reached from the straight edges by gentle curves
   instead of meeting them abruptly. One clip-path shape() for the whole outline (Firefox 148+, Chrome 135+),
   so it stays exact at any size and while moving. Without shape(): the border-radius, the same circle.
   The clip cuts off shadows, outlines and borders: put a shadow on a parent (see .activities-slide li). */
.squircle {
	--r: 2.4vh;
	border-radius: calc(var(--r) / 1.6);
	clip-path: shape(from var(--r) 0,
		line to calc(100% - var(--r)) 0,
		curve to calc(100% - 0.3413 * var(--r)) calc(0.0681 * var(--r)) with calc(100% - 0.65 * var(--r)) 0 / calc(100% - 0.475 * var(--r)) 0,
		arc to calc(100% - 0.0681 * var(--r)) calc(0.3413 * var(--r)) of calc(0.625 * var(--r)) cw,
		curve to 100% var(--r) with 100% calc(0.475 * var(--r)) / 100% calc(0.65 * var(--r)),
		line to 100% calc(100% - var(--r)),
		curve to calc(100% - 0.0681 * var(--r)) calc(100% - 0.3413 * var(--r)) with 100% calc(100% - 0.65 * var(--r)) / 100% calc(100% - 0.475 * var(--r)),
		arc to calc(100% - 0.3413 * var(--r)) calc(100% - 0.0681 * var(--r)) of calc(0.625 * var(--r)) cw,
		curve to calc(100% - var(--r)) 100% with calc(100% - 0.475 * var(--r)) 100% / calc(100% - 0.65 * var(--r)) 100%,
		line to var(--r) 100%,
		curve to calc(0.3413 * var(--r)) calc(100% - 0.0681 * var(--r)) with calc(0.65 * var(--r)) 100% / calc(0.475 * var(--r)) 100%,
		arc to calc(0.0681 * var(--r)) calc(100% - 0.3413 * var(--r)) of calc(0.625 * var(--r)) cw,
		curve to 0 calc(100% - var(--r)) with 0 calc(100% - 0.475 * var(--r)) / 0 calc(100% - 0.65 * var(--r)),
		line to 0 var(--r),
		curve to calc(0.0681 * var(--r)) calc(0.3413 * var(--r)) with 0 calc(0.65 * var(--r)) / 0 calc(0.475 * var(--r)),
		arc to calc(0.3413 * var(--r)) calc(0.0681 * var(--r)) of calc(0.625 * var(--r)) cw,
		curve to var(--r) 0 with calc(0.475 * var(--r)) 0 / calc(0.65 * var(--r)) 0,
		close);
}
```

Put `class="... squircle"` on the element and set `--r` per element.

- **One shape, never pieces.** An earlier version built the corners from a mask of six tiles (four corner
  images and two bars). Browsers round each tile to whole pixels on its own, so every corner measured from
  the right or bottom edge came out a pixel off: a step where curve meets edge, worse at other aspect
  ratios, and hairlines while cards slid in. A single `shape()` has no seams.
- **`--r` is 1.6× the `border-radius` it replaces.** `--r` is how far the corner reaches along each edge;
  its middle is a true circle arc of radius `--r / 1.6`, the gentle lead-ins take the rest. So
  `border-radius: 1.4vh` becomes `--r: 2.2vh` and looks just as round.
- **Don't make it a superellipse.** A pure superellipse (|x|ⁿ + |y|ⁿ = 1) runs much closer to the corner
  point than a circle, and on a card it looks pointed. The shapes above are the Apple/Figma construction:
  a circle arc with smooth (curvature-continuous) lead-ins, at 60% smoothing.
- **The clip cuts off everything outside the shape**: `box-shadow`, `outline` and anything that sticks out
  (a badge, the pet's cameo). For a shadow, the house pattern is a **shadow carrier**: the outer element
  (the `li`) keeps the `box-shadow`, a `border-radius` of the old size (it only shapes the blurred shadow,
  the difference can't be seen) and the entrance animation; an inner element is the card, with the
  background and `.squircle`. See `.activities-slide li` / `.activity-card`, `.practice-ticket` /
  `.practice-card`, `.news-cards li` / its button, `.member-qr-shadow` / `.member-qr-card`.
  Don't use `filter: drop-shadow()` on the parent instead: it follows the shape, but a blurred filter over
  card-sized areas is what the TV PC can't afford, worst while the cards animate in.
- **A pressed or busy card mustn't shrink away from its shadow.** With a shadow carrier, scaling the inner
  card leaves the shadow behind as a dark rim. Scale the carrier instead, or dim only (the news cards:
  `.news-cards button.busy { transform: none; }`).
- **Focus rings:** a clipped button can't show its `outline`. Give its `:focus-visible` another look
  (background, scale, as `.puzzle-card:focus-visible` does), or put the ring on the carrier.
- **Borders are cut off at the corners**, since a border follows the box, not the clip. For a bordered box,
  make the element's background the border colour and put the fill on an inset `::before`
  (`inset: <border width>; z-index: -1`, the parent `isolation: isolate`) that is a `.squircle` too, with
  `--r` minus the border width.
- **Never two backgrounds at the edge.** `clip-path` is applied to each painted layer separately, so where
  the curve cuts through a pixel, a parent's background under a child's (cream under a red date block or a
  photo) both get blended in and leave light pixels along the curve: the same fringe plain `border-radius`
  has. Give the clipped card no background and put each colour on the child that shows it (the cream on
  `.activity-text`, `.practice-info`, `.news-text`), so every edge pixel has one colour to cut.
- **Inner corners go.** A child that rounded its own corners to match the card (the practice ticket's date
  block) loses its `border-radius`: the card's clip shapes it now.
- **Circles stay circles.** Round avatars, the ERO photos, dots and round buttons (`border-radius: 50%`) are
  not corners. Leave them.
- **Pills stay capsules.** Fully round ends (`border-radius: 4vh` on a button, "Next two weeks") keep their
  semicircles: Apple's capsule buttons are semicircular too, and a squircle capsule looks flattened.
- **Tiny radii stay.** Under about 1vh (progress bars, small tags, chips, a book's edge) the difference is a
  pixel or less; a clip there is work for nothing.
- **Cost:** the clip is computed once and moves with `transform`/`opacity` for free. Don't animate `--r`, and
  don't animate the size of a clipped element with `width`/`height`.
- **In 3D** (Three.js), round the shapes in the geometry or texture; this clip is for HTML only.
- When Firefox gets `corner-shape`, this clip can become `border-radius: R; corner-shape: squircle;`.

## How to check your work

- Preview one slide: `./start.sh` and open `http://127.0.0.1:8080/preview/<name>`.
- `python3 -m unittest` must pass (the TV PC refuses a commit that fails it).
- For Use motion, tap through it at least three times in a row. The third tap is where replays and slow
  starts become annoying.
- Comments in `style.css` and the templates explain *why* in plain words, as the existing ones do (for
  example "translate, not margin: no relayout each frame"). Keep that up for every rule you add.

## Reviewing

When asked to review a slide's motion, go through it in this order and report findings as a table:

| Element | Show/Use | Problem | Fix (`file:line`) |
|---|---|---|---|

1. List everything that animates (`@keyframes`, `animation`, `transition`, `effects` in `player.js`, 3D loops).
2. Classify each as Show or Use.
3. Check the Use items: press look, busy state, ease-in on a response, entrances replayed after a redraw,
   duration over 0.3 s (0.6 s for changed content), animated typing.
4. Check the Show items: one entrance per container, order of importance, stagger, reading time, loop cost.
5. Check performance: animated layout or paint properties, full-screen layers, 3D budget.
5b. Check corners: plain `border-radius` on boxes (not circles) should be continuous corners (`.squircle`).
6. Say what's fine as well, and why (ease-in on something falling is right). Say what you couldn't
   verify without the TV.

Fix only what the person asked for. List the rest.
