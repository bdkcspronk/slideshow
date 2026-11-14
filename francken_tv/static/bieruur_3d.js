// The bieruur countdown as a split-flap display in 3D (templates/slides/bieruur.html, providers/bieruur.py), drawn
// with Three.js (static/vendor/three), like the departure boards at a station.
//
// The time left, always as HH:MM:SS, on a row of flaps in a display hanging on the wall (the slide's background:
// white plaster; the canvas is see-through), where the countdown's text is on the page; the label above it ("Bieruur
// in") stays text. Around the time, above, beside and below it, half-size flaps without letters, in colours, which
// flip in waves every few seconds, so their colours move in a pattern (stripes, rings around the time, a wipe, rain;
// the next pattern every few waves, and faster waves in the last two minutes).
// At bieruur (the page's data-phase turns to "bieruur", and the time to 00:00:00) the party starts: every flap, the
// time's too, rattles round to a colour, in a burst from the middle out; the display jumps, confetti shoots out of it
// and keeps falling. Then the colours flow over the flaps like a fluid (a small fluid simulation, stirred by a few
// stirrers pouring in colour), the display bouncing to a beat.
// From the first frame it shows the time as it is; each second the flaps whose digit changes fall to the next one
// (the digits go round downwards, 9 to 0, so a second is one flap). The time comes from the page (the data-live
// element the player updates every second, see refresh() in player.js), which is also what is shown without WebGL.
//
// Each flap is a real split flap: the top half of the letter on a flap that falls forward around the middle, the
// bottom half of the next letter on its back, the halves of the letters behind it on the fixed halves above and below.
// The wall itself is not drawn (the page shows through), only the display's case standing out from it, and the case's
// soft shadow on it.
//
// Kept within what the TV PC can do (docs/07-3d-limits.md): all flaps (some 110) are one InstancedMesh (each the black
// window behind and three thin boxes: the two fixed halves and the falling flap; 34 triangles, some 3,700 in all), drawn by a small shader from one
// texture holding every letter (a colour flap's "letter" is SOLID + its colour); with the case and
// its shadow that is 3 draw calls. It only draws when something moves: the time's flaps once a second and the waves
// (about a second of every few). Like the books, it drops to 75% resolution if its first flips draw slowly.
//
// One unit in the 3D world is 1vh: the camera is DISTANCE in front of the screen, so at z = 0 (the wall) the world is
// the size of the page.

const FLAPS = {
	distance: 140,   // the camera, in front of the screen
	letters: " ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,:-·/&'!?()+#",   // the letters in the texture
	digits: " :9876543210",   // the order the flaps go round: down, a second is one flap
	aspect: 0.6,   // a flap's width / its height
	pitch: 1.12,   // from one flap to the next, in flap widths (the black between them)
	row: 1.12,   // from one row of flaps to the next, in flap heights
	flip: 0.21,   // seconds per flap falling
	// How a flap falls (FALL, below): like a pendulum tipping over from upright. The drum turning gives it a `kick`
	// (it starts at that share of the speed it lands with), then gravity takes over: slowly while it is nearly
	// upright, faster and faster as it tips. Where it lands for good it bounces back up `bounce` degrees, and again
	// a third of that, in `bounceTime` seconds (not in the middle of a rattle: the next flap is falling already).
	// Seen straight from the front a small bounce hardly shows (8 degrees makes the flap 1% shorter), hence 30.
	fall: { kick: 0.3, bounce: 30, bounceTime: 0.22 },
	thickness: 0.22,   // how far the display's case stands out from the wall, in time flap heights
	lights: {   // three-point lighting: where each comes from (x right, y up, z towards the viewer), its colour and strength
		key: { from: [-4, 5, 8], colour: 0xfff4e6, strength: 2.2 },   // the main light, warm, from the top left front
		fill: { from: [6, -2, 6], colour: 0xdde6ff, strength: 0.6 },   // softens the key light's shadows, cool, from the right
		back: { from: [0, 8, -3], colour: 0xffffff, strength: 1.6 },   // from above and behind: lights up the top edges
		ambient: 0.5,
	},
	colours: {   // the flaps (r, g, b; as on the screen) and the case
		face: [0.11, 0.115, 0.13],   // a flap
		ink: [0.97, 0.94, 0.86],   // the digits: cream
		case: 0x2b2f36,   // the case: dark anthracite metal
	},
	// Around the time, half-size flaps without letters, only colours, flapping in patterns: so many rows above and
	// below it, columns beside it. Every `wave` seconds (`final`: in the last two minutes) a wave of flips runs over them.
	filler: { above: 2, below: 2, beside: 3, wave: 2.6, final: 1.2 },
	// At bieruur: `wait` seconds after 00:00:00 the burst, the flaps falling `flip` seconds each (going round once
	// more for the time's flaps, twice for the others), from the middle out (`spread` seconds per time flap height);
	// then the fluid (below), with a beat every `wave` seconds. `confetti` pieces, `pop` and `beat`: how much bigger
	// the display jumps at the burst and at each beat (the label bounces along: party-bounce in style.css).
	party: { wait: 0.6, flip: 0.08, spread: 0.16, wave: 1.3, confetti: 180, pop: 0.06, beat: 0.012 },
	// After the burst the colours flow over the flaps like a fluid: a small fluid simulation (fluidSim) `cells` wide
	// over the board, each palette colour a dye in it; each flap shows the colour with the most dye at its middle,
	// turning to another when that has `margin` more, in one flip of `flip` seconds. It starts from the burst's colours
	// with a push outwards (`kick`, cells a second). `stirrers` wander over the board, dragging the fluid along (`push`)
	// and pouring in colour, each the next colour every `colourEvery` seconds; `swirl` keeps the eddies going.
	fluid: { cells: 48, flip: 0.15, margin: 0.08, kick: 25, stirrers: 3, push: 1.6, colourEvery: 3.5, swirl: 6 },
	// Motion blur on the falling flaps: `ghosts` see-through copies of each falling flap behind it, spread over the angle
	// it falls while the shutter is open (`shutter` of a frame: 0.5 is a film camera's 180 degrees), fading out
	// (the first `strength` opaque); the time's big flaps, which sweep over more of the screen, `bigGhosts`. Off on a
	// canvas with data-blur="off" (the side by side test: bieruur_blur.html).
	blur: { ghosts: 8, bigGhosts: 16, shutter: 1, strength: 0.6 },
	palette: [   // the filler flaps' colours (r, g, b), in the order they go round: beer to Francken blue
		[0.96, 0.76, 0.25],   // gold
		[0.91, 0.58, 0.12],   // amber
		[0.94, 0.89, 0.77],   // foam
		[0.86, 0.21, 0.27],   // Francken red
		[0.09, 0.2, 0.29],   // Francken blue
		[0.18, 0.37, 0.54],   // light blue
	],
};
const SOLID = 64;   // a "letter" from SOLID up is a flap in colour palette[letter - SOLID], without a letter

// The fall (FLAPS.fall), worked out once: the angle from upright (0) to lying down (π) of a pendulum tipping over,
// angle'' = sin(angle), starting with the kick's speed; time scaled so that it lands at p = 1. angle(p), and speed(p)
// the change of the angle per unit of p (divide by the flip's seconds for radians a second), both from a table.
// The bounce: angle(s) back up, s seconds after it landed (two humps, the second a third as high).
const FALL = (() => {
	const kick = Math.min(Math.max(FLAPS.fall.kick, 0.05), 0.95);
	let angle = 0, speed = 2 * kick / Math.sqrt(1 - kick * kick);   // so that it lands at speed / kick
	const samples = [[angle, speed]], dt = 1e-4;
	while (angle < Math.PI) {
		speed += Math.sin(angle) * dt;
		angle += speed * dt;
		samples.push([Math.min(angle, Math.PI), speed]);
	}
	const time = (samples.length - 1) * dt, size = 64;
	const table = Array.from({ length: size + 1 }, (_, i) => samples[Math.round(i / size * (samples.length - 1))]);
	const look = (p, n) => {
		const x = Math.min(Math.max(p, 0), 1) * size, i = Math.min(Math.floor(x), size - 1), a = x - i;
		return table[i][n] * (1 - a) + table[i + 1][n] * a;
	};
	const { bounce, bounceTime } = FLAPS.fall, first = bounceTime * 0.65, second = bounceTime - first;
	return {
		angle: (p) => look(p, 0),
		speed: (p) => look(p, 1) * time,
		bounce: (s) => (bounce * Math.PI / 180) * (s < first ? Math.sin(Math.PI * s / first) : s < bounceTime ? Math.sin(Math.PI * (s - first) / second) / 3 : 0),
	};
})();

function setupBieruur3d(canvas) {
	const slide = canvas.closest(".bieruur-slide");
	slide.classList.add("bieruur-flaps");   // hides the countdown as text, keeping its place
	loadThree().then((THREE) => {
		if (document.contains(canvas)) return drawBieruur3d(THREE, canvas, slide);
	}).catch((error) => {
		console.warn("Bieruur in 3D:", error);
		slide.classList.remove("bieruur-flaps");   // the text instead
	});
}

async function drawBieruur3d(THREE, canvas, slide) {
	let renderer;
	try {
		renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true, powerPreference: "high-performance" });
	} catch (error) {
		throw new Error(`no WebGL: ${error}`);
	}
	await document.fonts.load('400 100px "Bebas Neue"').catch(() => {});
	if (!document.contains(canvas)) return renderer.dispose();

	const vh = innerHeight / 100;
	const box = canvas.getBoundingClientRect();
	const width = box.width / vh, height = box.height / vh;
	const { distance, colours, aspect, pitch } = FLAPS;
	let quality = 1;
	const resize = () => {
		renderer.setPixelRatio(devicePixelRatio * quality);
		renderer.setSize(canvas.clientWidth, canvas.clientHeight, false);
	};
	resize();
	// Three-point lighting (FLAPS.lights): a key light from the top left front, a weaker fill from the right, and a
	// back light from above and behind that catches the top edges; a little ambient light besides.
	const scene = new THREE.Scene();
	scene.add(new THREE.HemisphereLight(0xf4f0ff, 0x30384a, FLAPS.lights.ambient));
	for (const name of ["key", "fill", "back"]) {
		const { colour, strength, from } = FLAPS.lights[name];
		const light = new THREE.DirectionalLight(colour, strength);
		light.position.set(...from);
		scene.add(light);
	}

	// The time as the page says it now (the player replaces this element's text every second), always as HH:MM:SS.
	const countdown = slide.querySelector(".bieruur-countdown");
	const info = slide.querySelector(".bieruur-info");
	// In the side by side test (bieruur_blur.html) both displays run on one clock, which can be paused there.
	const demo = slide.closest("[data-bieruur-demo]");
	const blurred = canvas.dataset.blur !== "off";
	const phase = () => info?.dataset.phase;   // "countdown", "final" (the last two minutes) or "bieruur"
	const text = () => clockText(flapText(countdown?.textContent));
	const first = text();

	// The board where the countdown's text is (style.css keeps its place): the time's 8 flaps in the middle, with
	// half-size filler flaps around them, all as big as fit in that place and in 88% of the width. The filler flaps
	// are on a grid of half cells (`cols` x `rows`), the time's flaps take 2 x 2 of them each.
	const n = 8, filler = FLAPS.filler;
	const cols = 2 * filler.beside + 2 * n, rows = filler.above + filler.below + 2;
	const place = countdown.getBoundingClientRect();
	// (Room left for the case's rim, and for the case looking a little bigger, standing out towards the camera.)
	const fh = Math.min(place.height / vh / (rows / 2 * FLAPS.row + 0.4), 0.88 * width / (cols / 2 * aspect * pitch));
	const step = fh * aspect * pitch, rowH = fh * FLAPS.row;
	const y = height / 2 - ((place.top + place.bottom) / 2 - box.top) / vh;
	const boardW = cols * step / 2, boardH = rows * rowH / 2;
	const left = -boardW / 2, top = y + boardH / 2;

	// The camera straight in front of the board (at its height), looking straight at the wall; the view shifted
	// (an off-centre frustum) so the wall still lines up with the page.
	const camera = new THREE.PerspectiveCamera(50, width / height, 10, 1000);
	camera.position.set(0, y, distance);
	const near = camera.near / distance;
	camera.projectionMatrix.makePerspective(-width / 2 * near, width / 2 * near, (height / 2 - y) * near, (-height / 2 - y) * near, camera.near, camera.far);
	camera.projectionMatrixInverse.copy(camera.projectionMatrix).invert();

	// The flaps: each where it is on its wheel (the digits, or the colours) and where it is going (from, steps,
	// start: at t = start it starts falling from wheel[from], one step per flip). The time's flaps first.
	const digits = [...FLAPS.digits].map((c) => FLAPS.letters.indexOf(c));
	const colourWheel = FLAPS.palette.map((_, k) => SOLID + k);
	const flaps = Array.from({ length: n }, (_, c) => ({ wheel: digits, size: fh, flip: FLAPS.flip,
		x: left + filler.beside * step / 2 + (c + 0.5) * step, y: top - filler.above * rowH / 2 - rowH / 2, from: 0, steps: 0, start: 0 }));
	const fillers = [];
	for (let j = 0; j < rows; j++) {
		for (let i = 0; i < cols; i++) {
			const inTime = i >= filler.beside && i < filler.beside + 2 * n && j >= filler.above && j < filler.above + 2;
			if (!inTime) fillers.push({ wheel: colourWheel, size: fh / 2, flip: FLAPS.flip, i, j,
				x: left + (i + 0.5) * step / 2, y: top - (j + 0.5) * rowH / 2, from: 0, steps: 0, start: 0 });
		}
	}
	flaps.push(...fillers);
	const count = flaps.length;

	// Send a flap to wheel position `target`, from where it is at t (also halfway falling: it carries on from there).
	// now: be there at once, without falling.
	const at = (flap, t) => Math.min(flap.steps, Math.max(0, Math.floor((t - flap.start) / flap.flip)));
	const turnTo = (flap, target, t, now = false) => {
		if (target < 0) return;
		if (now) return void Object.assign(flap, { from: target, steps: 0, start: t });
		const k = at(flap, t);
		flap.from = (flap.from + k) % flap.wheel.length;
		if (k < flap.steps && t >= flap.start) flap.start += k * flap.flip;   // carries on falling
		else flap.start = t;
		flap.steps = (target - flap.from + flap.wheel.length) % flap.wheel.length;
	};
	const spell = (time, t, now) => {
		time = time.slice(-n).padStart(n, " ");
		flaps.slice(0, n).forEach((flap, c) => turnTo(flap, digits.indexOf(FLAPS.letters.indexOf(time[c])), t, now));
	};

	// The filler flaps' patterns, on the grid of half cells (i across, j down): each wave every flap goes to colour
	// (colour(i, j) + wave), starting after delay(i, j) seconds, so the pattern moves on by one colour, as a wave. Every
	// few waves the next pattern.
	const timeLeft = filler.beside, timeRight = filler.beside + 2 * n - 1, timeTop = filler.above, timeBottom = filler.above + 1;
	const ring = (i, j) => Math.max(timeLeft - i, i - timeRight, timeTop - j, j - timeBottom, 0);   // half cells from the time
	const patterns = [
		{ colour: (i, j) => Math.floor((i + j) / 2), delay: (i, j) => (i + j) * 0.035 },   // diagonal stripes, from the top left
		{ colour: (i, j) => -ring(i, j), delay: (i, j) => ring(i, j) * 0.14 },   // rings going out from the time
		{ colour: () => 0, delay: (i) => i * 0.035 },   // the whole board one colour, wiped from left to right
		{ colour: (i) => Math.floor(i / 2), delay: (i, j) => j * 0.07 + ((i * 7) % 5) * 0.04 },   // columns, raining down
	];
	const perPattern = 3;
	let wave = 0;
	const flapWave = (t, now = false) => {
		const pattern = patterns[Math.floor(wave / perPattern) % patterns.length];
		const K = colourWheel.length;
		fillers.forEach((flap) => {
			const colour = ((pattern.colour(flap.i, flap.j) + wave) % K + K) % K;
			turnTo(flap, colour, t, now);
			if (!now) flap.start = Math.max(flap.start, t + pattern.delay(flap.i, flap.j));
		});
		wave++;
	};
	const wavePause = () => (phase() === "final" ? filler.final : filler.wave);

	// The display's case on the wall: a dark box `thick` deep with bevelled edges (seen from the front, they are what
	// shows it stands out: lit on the top left, dark on the bottom right), a narrow rim around the board, and its soft
	// shadow on the wall, down and to the right (the key light comes from the top left).
	const rim = fh * 0.12, thick = fh * FLAPS.thickness;
	const caseW = boardW + 2 * rim, caseH = boardH + 2 * rim, bevel = rim * 0.6;
	const board = new THREE.Group();   // the case, its shadow and the flaps: jumps at bieruur (bounce, below)
	scene.add(board);
	const outline = new THREE.Shape();
	const ow = caseW / 2 - bevel, oh = caseH / 2 - bevel;
	outline.moveTo(-ow, -oh).lineTo(ow, -oh).lineTo(ow, oh).lineTo(-ow, oh).closePath();
	const housing = new THREE.Mesh(new THREE.ExtrudeGeometry(outline, { depth: thick - 2 * bevel, bevelEnabled: true,
		bevelThickness: bevel, bevelSize: bevel, bevelSegments: 4 }),
		new THREE.MeshStandardMaterial({ color: colours.case, roughness: 0.45, metalness: 0.35 }));
	housing.position.set(0, y, bevel);   // its back against the wall
	board.add(housing);
	const blur = fh * 0.45;
	const shade = shadowTexture(THREE, caseW, caseH, blur);
	const shadow = new THREE.Mesh(new THREE.PlaneGeometry(caseW + 2 * blur, caseH + 2 * blur),
		new THREE.MeshBasicMaterial({ map: shade, transparent: true, depthWrite: false }));
	shadow.position.set(thick * 0.5, y - thick * 0.8, 0.01);
	board.add(shadow);

	// The flaps on the front of the case.
	const atlas = letterAtlas(THREE);
	const flapMaterial = flapShader(THREE, atlas);
	const geometry = flapGeometry(THREE);
	const mesh = new THREE.InstancedMesh(geometry, flapMaterial, count);
	const chars = new THREE.InstancedBufferAttribute(new Float32Array(count * 4), 4);
	const angles = new THREE.InstancedBufferAttribute(new Float32Array(count), 1);
	const speeds = new THREE.InstancedBufferAttribute(new Float32Array(count), 1);   // how fast each falls, radians a second
	[chars, angles, speeds].forEach((a) => a.setUsage(THREE.DynamicDrawUsage));
	const instanced = { aChars: chars, aAngle: angles, aSpeed: speeds,
		aGhosts: new THREE.InstancedBufferAttribute(new Float32Array(flaps.map((_, c) => (c < n ? FLAPS.blur.bigGhosts : FLAPS.blur.ghosts))), 1),
		aFace: new THREE.InstancedBufferAttribute(new Float32Array(flaps.flatMap(() => colours.face)), 3),
		aInk: new THREE.InstancedBufferAttribute(new Float32Array(flaps.flatMap(() => colours.ink)), 3) };
	Object.entries(instanced).forEach(([name, attribute]) => geometry.setAttribute(name, attribute));
	const matrix = new THREE.Matrix4();
	flaps.forEach((flap, c) => {
		matrix.makeScale(flap.size * aspect, flap.size, flap.size).setPosition(flap.x, flap.y, thick + flap.size * 0.04);
		mesh.setMatrixAt(c, matrix);
	});
	mesh.frustumCulled = false;   // the flaps move out of the box three.js thinks they are in
	board.add(mesh);
	// The motion blur (FLAPS.blur): the falling flaps' ghosts, all in one more mesh with the same flaps (the same
	// attributes and places), drawn see-through after the rest. Only what falls has ghosts; the others are not drawn.
	// Room for the most ghosts a flap has (aGhosts); a small flap's spare ghosts are not drawn either.
	let trail = null;
	if (blurred) {
		const trailGeometry = flapGeometry(THREE, Math.max(FLAPS.blur.ghosts, FLAPS.blur.bigGhosts));
		Object.entries(instanced).forEach(([name, attribute]) => trailGeometry.setAttribute(name, attribute));
		trail = new THREE.InstancedMesh(trailGeometry, flapShader(THREE, atlas, true), count);
		trail.instanceMatrix = mesh.instanceMatrix;
		trail.frustumCulled = false;
		board.add(trail);
	}

	// The party at bieruur (FLAPS.party). Where each flap is on the board, for the party's patterns: d how far from
	// the middle (in time flap heights), u and v across and down (0 to 1).
	const party = FLAPS.party, K = colourWheel.length;
	flaps.forEach((flap) => Object.assign(flap, { d: Math.hypot(flap.x, flap.y - y) / fh, u: (flap.x - left) / boardW, v: (top - flap.y) / boardH }));
	let partyAt = null, burstAt = null, pop = { at: -Infinity, size: 0 };
	// The burst: the time's flaps go round once more, now with the colours on their wheel too (partyWheel; when they
	// are there, only the colours: `next`, see settle), the colour flaps twice; quickly, from the middle out, ending
	// in rings of colour. Returns when the last flap is there.
	const partyWheel = digits.concat(colourWheel);
	const settle = (flap, t) => {
		if (!flap.next || at(flap, t) < flap.steps) return;
		const letter = flap.wheel[(flap.from + flap.steps) % flap.wheel.length];
		Object.assign(flap, { wheel: flap.next, from: flap.next.indexOf(letter), steps: 0, start: t, next: null });
	};
	const burst = (t) => {
		let end = t;
		flaps.forEach((flap, c) => {
			if (c < n) Object.assign(flap, { wheel: partyWheel, from: (flap.from + at(flap, t)) % digits.length, steps: 0, start: t, next: colourWheel });
			turnTo(flap, flap.wheel.indexOf(SOLID + ((-Math.floor(flap.d * 1.6)) % K + K) % K), t);
			flap.steps += flap.wheel.length * (c < n ? 1 : 2);
			flap.flip = party.flip;
			flap.start = t + flap.d * party.spread;
			end = Math.max(end, flap.start + flap.steps * flap.flip);
		});
		return end;
	};
	// Then the fluid (FLAPS.fluid): a simulation on a grid of square cells over the board; where each flap's middle is
	// on it (gx, gy, in cells). It starts from the colours the burst ended on (each cell the colour of the flap it is
	// under, judged by distance over size, so a big flap covers more) and a push outwards from the middle.
	const F = FLAPS.fluid, cell = boardW / F.cells, fluidRows = Math.max(4, Math.round(boardH / cell));
	flaps.forEach((flap) => Object.assign(flap, { gx: (flap.x - left) / cell - 0.5, gy: (top - flap.y) / cell - 0.5 }));
	const showing = (flap) => flap.wheel[(flap.from + flap.steps) % flap.wheel.length];   // the letter it ends on
	let fluid = null, fluidT = 0;
	const startFluid = (t) => {
		fluid = fluidSim(F.cells, fluidRows, K);
		fluid.seed((x, y) => {
			let best = flaps[0], nearest = Infinity;
			flaps.forEach((flap) => {
				const d = Math.hypot(flap.gx - x, flap.gy - y) / flap.size;
				if (d < nearest) [best, nearest] = [flap, d];
			});
			return showing(best) - SOLID;
		});
		fluid.kick(F.kick);
		fluidT = t;
	};
	// The stirrers: each wanders over the board on its own path (a Lissajous figure), dragging the fluid along in
	// the direction it moves and pouring in its colour.
	const stir = (t) => {
		const nx = F.cells, ny = fluidRows;
		for (let s = 0; s < F.stirrers; s++) {
			const w1 = 0.5 + 0.13 * s, w2 = 0.83 + 0.11 * s, p1 = s * 2.1, p2 = s * 1.3 + 0.7;
			const ax = 0.42 * nx, ay = 0.36 * ny;
			fluid.splat(nx / 2 + ax * Math.sin(w1 * t + p1), ny / 2 + ay * Math.sin(w2 * t + p2), 2.4,
				ax * w1 * Math.cos(w1 * t + p1) * F.push, ay * w2 * Math.cos(w2 * t + p2) * F.push,
				(s * 2 + Math.floor(t / F.colourEvery)) % K);
		}
	};
	// Each frame: the fluid on in steps of 1/30 s (at most 4, after a stall), then every flap that is standing still
	// turns to the colour with the most dye under it, if that has clearly more than its own.
	const flow = (t) => {
		for (let steps = 0; fluidT + 1 / 30 <= t && steps < 4; steps++) {
			stir(fluidT);
			fluid.step(1 / 30, F.swirl);
			fluidT += 1 / 30;
		}
		fluidT = Math.max(fluidT, t - 1 / 30);
		flaps.forEach((flap) => {
			if (at(flap, t) < flap.steps) return;   // still falling
			const letter = showing(flap), amounts = fluid.dyes(flap.gx, flap.gy);
			let best = 0;
			amounts.forEach((a, k) => { if (a > amounts[best]) best = k; });
			if (SOLID + best !== letter && amounts[best] > amounts[letter - SOLID] + F.margin) {
				// one flip, straight to the new colour (not round the wheel: colours in between would muddy the flow)
				Object.assign(flap, { wheel: [letter, SOLID + best], from: 0, steps: 1, start: t, flip: F.flip, next: null });
			}
		});
	};
	// The display jumps (a little bigger, springing back) at the burst and, less, at every beat.
	const bounce = (t) => {
		const age = t - pop.at;
		const s = age < 0 || age > 2 ? 1 : 1 + pop.size * Math.exp(-age * 5) * Math.sin(age * 20);
		board.scale.setScalar(s);
		board.position.y = y * (1 - s);   // bigger around the board's middle
	};

	// Confetti: small cards in the flaps' colours, tumbling and fluttering, lit by the same lights. Shot out of the
	// display at the burst; one that has fallen off the screen comes down again from above. One draw call, all moved
	// every frame (a few hundred: well within what the PC can do).
	const confetti = new THREE.InstancedMesh(new THREE.PlaneGeometry(1, 0.6),
		new THREE.MeshLambertMaterial({ side: THREE.DoubleSide }), party.confetti);
	const pieces = Array.from({ length: party.confetti }, (_, c) => {
		confetti.setColorAt(c, new THREE.Color().setRGB(...FLAPS.palette[c % K], THREE.SRGBColorSpace));
		return { p: new THREE.Vector3(), v: new THREE.Vector3(), angle: Math.random() * 6.3, spin: 3 + Math.random() * 9,
			axis: new THREE.Vector3(Math.random() - 0.5, Math.random() - 0.5, Math.random() - 0.5).normalize(),
			sway: Math.random() * 6.3, size: 1.3 + Math.random() * 1.1 };
	});
	confetti.frustumCulled = false;
	confetti.visible = false;
	scene.add(confetti);
	const gravity = 40, drag = 2.2;   // falling at most gravity / drag (18vh) a second
	const launch = (piece) => {   // out of the display: up, outwards and towards the camera
		piece.p.set(left + Math.random() * boardW, y + (Math.random() - 0.5) * boardH, thick + 1);
		piece.v.set(piece.p.x / (boardW / 2) * 60 + (Math.random() - 0.5) * 50, 40 + Math.random() * 90, 10 + Math.random() * 60);
	};
	const rain = (piece) => {   // from just above the screen (as seen from the camera at that depth)
		const z = 3 + Math.random() * 50, near = (distance - z) / distance;
		piece.p.set((Math.random() - 0.5) * width * near, y + (height / 2 - y) * near + 2 + Math.random() * 15, z);
		piece.v.set(0, -8, 0);
	};
	const turn = new THREE.Quaternion(), size = new THREE.Vector3();
	let flown = null;
	const fly = (t) => {
		const dt = flown === null ? 0 : Math.min(t - flown, 0.05);
		flown = t;
		const slow = Math.exp(-drag * dt);
		pieces.forEach((piece, c) => {
			piece.v.y -= gravity * dt;
			piece.v.multiplyScalar(slow);
			piece.p.addScaledVector(piece.v, dt);
			piece.p.x += Math.sin(t * 2.5 + piece.sway) * 5 * dt;
			piece.angle += piece.spin * dt;
			if (piece.p.y < -height / 2 - 10) rain(piece);
			matrix.compose(piece.p, turn.setFromAxisAngle(piece.axis, piece.angle), size.setScalar(piece.size));
			confetti.setMatrixAt(c, matrix);
		});
		confetti.instanceMatrix.needsUpdate = true;
	};

	spell(first, 0, true);
	flapWave(0, true);
	let shown = first, nextWave = wavePause();

	// Where every flap is at t seconds after the slide was shown; true while one moves (or is about to).
	const pose = (t) => {
		let moving = false;
		flaps.forEach((flap, c) => {
			const wheel = flap.wheel, N = wheel.length;
			const e = t - flap.start;
			const k = Math.floor(e / flap.flip);
			const landed = e - flap.steps * flap.flip;   // seconds since it landed for good
			let top, bottom, front, back, angle = 0, speed = 0;
			if (e < 0 || flap.steps === 0) top = bottom = front = back = wheel[flap.from];
			else if (k >= flap.steps && landed < FLAPS.fall.bounceTime) {
				// Just landed: the last flap bounces up from lying down (the bounce is too slow to blur).
				const now = wheel[(flap.from + flap.steps - 1) % N], next = wheel[(flap.from + flap.steps) % N];
				top = next; bottom = now; front = now; back = next;
				angle = Math.PI - FALL.bounce(landed);
			} else if (k >= flap.steps) top = bottom = front = back = wheel[(flap.from + flap.steps) % N];
			else {
				// Letter `now` falls away and shows `next`: the falling flap has now's top half on its front and
				// next's bottom half on its back; behind it the fixed halves are next's top and now's bottom.
				const now = wheel[(flap.from + k) % N], next = wheel[(flap.from + k + 1) % N];
				top = next; bottom = now; front = now; back = next;
				const p = e / flap.flip - k;
				angle = FALL.angle(p);   // a kick, then faster and faster
				speed = FALL.speed(p) / flap.flip;
			}
			if (flap.steps > 0 && (e < 0 || landed < FLAPS.fall.bounceTime)) moving = true;
			chars.setXYZW(c, top, bottom, front, back);
			angles.setX(c, angle);
			speeds.setX(c, speed);
		});
		chars.needsUpdate = angles.needsUpdate = speeds.needsUpdate = true;
		return moving;
	};
	pose(0);
	renderer.render(scene, camera);   // there at once, also while the slide is still coming in

	// One frame at a time while the slide is on the page, drawn only when something moves; freed when it's gone
	// (the browser has only a few WebGL contexts).
	// t: seconds since the slide was shown; stands still while the side by side test is paused.
	let t = 0, last = null, measured = !!demo, still = true, previous = null;   // (the test: both at full resolution)
	const gaps = [];
	const frame = (now) => {
		if (!document.contains(canvas)) {
			atlas.dispose();
			shade.dispose();
			scene.traverse((o) => { o.geometry?.dispose(); [o.material].flat().forEach((m) => m?.dispose()); });
			renderer.dispose();
			renderer.forceContextLoss();
			return;
		}
		requestAnimationFrame(frame);
		const frozen = demo?.dataset.frozen === "true";
		const rate = Number(demo?.dataset.rate ?? 1);   // the test's slow motion
		if (last !== null && !frozen) {
			t += (now - last) / 1000 * rate;
			// The shutter for the motion blur: open for part of this frame (frames over 50 ms count as 1/60 s).
			if (trail) trail.material.uniforms.shutter.value = FLAPS.blur.shutter * (now - last > 50 ? 1 / 60 : (now - last) / 1000) * rate;
		}
		last = now;
		const time = text();
		if (burstAt === null && time !== shown) {   // the next second
			shown = time;
			spell(time, t);
			still = false;
		}
		if (partyAt === null && phase() === "bieruur") partyAt = t + party.wait;   // bieruur! (just after 00:00:00)
		if (burstAt === null && partyAt !== null && t >= partyAt) {
			burstAt = t;
			nextWave = burst(t) + 0.3;
			pop = { at: t, size: party.pop };
			pieces.forEach(launch);
			confetti.visible = true;
		} else if (t >= nextWave && burstAt !== null) {   // after the burst: the fluid, and the beat
			if (!fluid) startFluid(t);
			pop = { at: t, size: party.beat };
			nextWave = t + party.wave;
		} else if (t >= nextWave && partyAt === null) {   // the next wave over the filler flaps
			flapWave(t);
			nextWave = t + wavePause();
			still = false;
		}
		if (burstAt !== null) {   // the party: confetti, the display moving and the fluid, every frame
			fly(t);
			bounce(t);
			if (fluid && !frozen) flow(t);
			still = false;
		}
		if (still || frozen) return void (previous = null);
		still = !pose(t);
		renderer.render(scene, camera);
		// Too slow for this PC? Over the first 30 frames drawn one after the other (flaps falling), drop to 75%
		// resolution once if they come slower than 50 a second.
		if (!measured) {
			if (previous !== null) gaps.push(now - previous);
			previous = now;
			if (gaps.length >= 30) {
				measured = true;
				gaps.sort((p, q) => p - q);
				if (gaps[Math.floor(gaps.length / 2)] > 20) {
					quality = 0.75;
					resize();
					renderer.render(scene, camera);
					console.info("Bieruur in 3D: slow frames, drawing at 75% resolution");
				}
			}
		}
	};
	requestAnimationFrame(frame);
}

// A small 2D fluid, as in Jos Stam's "Stable fluids", for the party (FLAPS.fluid): on a grid of nx x ny square cells
// (i across, j down; distances in cells, speeds in cells a second), with walls all round, carrying `colours` dyes
// (one per palette colour, 0 to 1). Each step: the velocity carries itself and the dyes along (looking back along it,
// which keeps it stable at any speed), swirl keeps the eddies going (vorticity confinement), and the velocity is
// made to flow without piling up or thinning out (a pressure solve, Jacobi iterations). Some 1,000 cells: a fraction
// of a millisecond a step in JavaScript.
function fluidSim(nx, ny, colours) {
	const N = nx * ny, at = (i, j) => i + j * nx;
	let u = new Float32Array(N), v = new Float32Array(N), u2 = new Float32Array(N), v2 = new Float32Array(N);
	let dye = Array.from({ length: colours }, () => new Float32Array(N));
	let dye2 = Array.from({ length: colours }, () => new Float32Array(N));
	const pressure = new Float32Array(N), divergence = new Float32Array(N), curl = new Float32Array(N);
	// A field at any point (bilinear, kept inside the grid).
	const sample = (f, x, y) => {
		x = Math.min(Math.max(x, 0), nx - 1.001);
		y = Math.min(Math.max(y, 0), ny - 1.001);
		const i = Math.floor(x), j = Math.floor(y), a = x - i, b = y - j, k = at(i, j);
		return (f[k] * (1 - a) + f[k + 1] * a) * (1 - b) + (f[k + nx] * (1 - a) + f[k + nx + 1] * a) * b;
	};
	const advect = (from, to, dt) => {
		for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) {
			const k = at(i, j);
			to[k] = sample(from, i - dt * u[k], j - dt * v[k]);
		}
	};
	const walls = () => {
		for (let j = 0; j < ny; j++) u[at(0, j)] = u[at(nx - 1, j)] = 0;
		for (let i = 0; i < nx; i++) v[at(i, 0)] = v[at(i, ny - 1)] = 0;
	};
	const swirl = (dt, strength) => {
		for (let j = 1; j < ny - 1; j++) for (let i = 1; i < nx - 1; i++) {
			const k = at(i, j);
			curl[k] = (v[k + 1] - v[k - 1] - u[k + nx] + u[k - nx]) / 2;
		}
		for (let j = 2; j < ny - 2; j++) for (let i = 2; i < nx - 2; i++) {
			const k = at(i, j);
			const gx = (Math.abs(curl[k + 1]) - Math.abs(curl[k - 1])) / 2, gy = (Math.abs(curl[k + nx]) - Math.abs(curl[k - nx])) / 2;
			const length = Math.hypot(gx, gy) + 1e-5;
			u[k] += dt * strength * (gy / length) * curl[k];
			v[k] -= dt * strength * (gx / length) * curl[k];
		}
	};
	const project = () => {
		for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) {
			const k = at(i, j);
			divergence[k] = -((i < nx - 1 ? u[k + 1] : 0) - (i > 0 ? u[k - 1] : 0) + (j < ny - 1 ? v[k + nx] : 0) - (j > 0 ? v[k - nx] : 0)) / 2;
		}
		pressure.fill(0);
		for (let n = 0; n < 20; n++) {
			for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) {
				const k = at(i, j), p = pressure[k];
				pressure[k] = (divergence[k] + (i > 0 ? pressure[k - 1] : p) + (i < nx - 1 ? pressure[k + 1] : p)
					+ (j > 0 ? pressure[k - nx] : p) + (j < ny - 1 ? pressure[k + nx] : p)) / 4;
			}
		}
		for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) {
			const k = at(i, j), p = pressure[k];
			u[k] -= ((i < nx - 1 ? pressure[k + 1] : p) - (i > 0 ? pressure[k - 1] : p)) / 2;
			v[k] -= ((j < ny - 1 ? pressure[k + nx] : p) - (j > 0 ? pressure[k - nx] : p)) / 2;
		}
		walls();
	};
	return {
		// Every cell full of one colour: colour(i, j).
		seed(colour) {
			for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) dye[colour(i, j)][at(i, j)] = 1;
		},
		// A push outwards from the middle, `speed` cells a second there, less further out.
		kick(speed) {
			for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) {
				const dx = i - nx / 2, dy = j - ny / 2, d = Math.hypot(dx, dy) + 1e-5, k = at(i, j);
				u[k] += dx / d * speed * Math.exp(-d / (nx / 4));
				v[k] += dy / d * speed * Math.exp(-d / (nx / 4));
			}
			project();
		},
		// Around (x, y), within about `radius` cells: the fluid dragged towards velocity (vx, vy), and colour `colour` poured in.
		splat(x, y, radius, vx, vy, colour) {
			const i0 = Math.max(0, Math.floor(x - 2 * radius)), i1 = Math.min(nx - 1, Math.ceil(x + 2 * radius));
			const j0 = Math.max(0, Math.floor(y - 2 * radius)), j1 = Math.min(ny - 1, Math.ceil(y + 2 * radius));
			for (let j = j0; j <= j1; j++) for (let i = i0; i <= i1; i++) {
				const k = at(i, j), w = Math.exp(-((i - x) ** 2 + (j - y) ** 2) / (radius * radius));
				u[k] += (vx - u[k]) * w * 0.25;
				v[k] += (vy - v[k]) * w * 0.25;
				const pour = w * 0.3;
				for (let c = 0; c < colours; c++) dye[c][k] = c === colour ? dye[c][k] + pour * (1 - dye[c][k]) : dye[c][k] * (1 - pour);
			}
		},
		step(dt, strength) {
			walls();
			swirl(dt, strength);
			project();
			advect(u, u2, dt);
			advect(v, v2, dt);
			[u, u2, v, v2] = [u2, u, v2, v];
			walls();
			project();
			for (let c = 0; c < colours; c++) advect(dye[c], dye2[c], dt);
			[dye, dye2] = [dye2, dye];
		},
		// How much of each colour there is at (x, y).
		dyes(x, y) {
			return dye.map((f) => sample(f, x, y));
		},
	};
}

// The case's shadow on the wall: a w x h rectangle blurred by `blur` (world units) all round, black and see-through;
// the texture covers (w + 2 blur) x (h + 2 blur).
function shadowTexture(THREE, w, h, blur) {
	const scale = 256 / (w + 2 * blur);
	const canvas = document.createElement("canvas");
	canvas.width = 256;
	canvas.height = Math.max(8, Math.round((h + 2 * blur) * scale));
	const ctx = canvas.getContext("2d");
	ctx.shadowColor = "rgba(0, 0, 0, 0.42)";
	ctx.shadowBlur = blur * scale * 0.9;
	ctx.shadowOffsetX = 10000;   // only the shadow lands on the canvas, the rectangle itself is far to the left
	ctx.fillRect(blur * scale - 10000, blur * scale, w * scale, h * scale);
	const texture = new THREE.CanvasTexture(canvas);
	texture.colorSpace = THREE.SRGBColorSpace;
	return texture;
}

// The time left as HH:MM:SS, whatever the page shows ("4:05:09", "05:09"); other text as it is.
function clockText(text) {
	const parts = text.split(":");
	if (!parts.every((p) => /^\d+$/.test(p)) || parts.length > 3) return text;
	while (parts.length < 3) parts.unshift("0");
	return parts.map((p) => p.padStart(2, "0").slice(-2)).join(":");
}

// Text as the flaps can show it: capitals without accents; letters they don't have become a space.
function flapText(text) {
	const plain = String(text ?? "").normalize("NFD").replace(/[̀-ͯ]/g, "").toUpperCase()
		.replace(/[‘’`´]/g, "'").replace(/[“”"]/g, "'").replace(/[–—]/g, "-").replace(/ß/g, "SS").replace(/…/g, "...");
	return [...plain].map((c) => (FLAPS.letters.includes(c) ? c : " ")).join("").replace(/\s+/g, " ").trim();
}

// Every letter in one texture: a grid of tiles, white letters on black, each letter's middle at its tile's middle
// (where the flap splits it). The shader colours them.
const LETTER_TILE = { w: Math.round(128 * FLAPS.aspect), h: 128, columns: 8 };
function letterAtlas(THREE) {
	const { w, h, columns } = LETTER_TILE;
	const rows = Math.ceil(FLAPS.letters.length / columns);
	const canvas = document.createElement("canvas");
	canvas.width = w * columns;
	canvas.height = h * rows;
	const ctx = canvas.getContext("2d");
	ctx.fillStyle = "#000000";
	ctx.fillRect(0, 0, canvas.width, canvas.height);
	ctx.fillStyle = "#ffffff";
	ctx.font = `400 ${Math.round(h * 1.02)}px "Bebas Neue", "DejaVu Sans Condensed", sans-serif`;
	ctx.textAlign = "center";
	ctx.textBaseline = "alphabetic";
	const capital = ctx.measureText("H").actualBoundingBoxAscent || h * 0.6;
	[...FLAPS.letters].forEach((letter, n) => {
		const x = (n % columns) * w, y = Math.floor(n / columns) * h;
		ctx.fillText(letter, x + w / 2, y + h / 2 + capital / 2);
	});
	const texture = new THREE.CanvasTexture(canvas);
	texture.anisotropy = 4;
	return texture;
}

// One flap position, 1 high and 1 wide (the instance matrix stretches it to the flap's size). Each half is a thin box
// (FLAP_THICK deep) with its `part`: 0 the fixed top half, 1 the fixed bottom half, 2 and 3 the falling flap's front and
// back (at rest over the top half, just in front of it); and 4, a flat quad, the black window behind. The boxes' sides
// (`edge` 1) are plain, in the flap's colour; uv is where on the letter's tile each point of a front or back is.
// With `ghosts`: only the falling flap, that many times (`ghost` 1, 2, ...), for the motion blur (FLAPS.blur).
const FLAP_THICK = 0.025, FLAP_Z = FLAP_THICK + 0.005;   // the falling flap's front; it turns around its middle
function flapGeometry(THREE, ghosts = 0) {
	const seam = 0.012;   // half the gap between the halves
	const positions = [], normals = [], uvs = [], parts = [], edges = [], index = [], ghostOf = [];
	let ghost = 0;
	// A quad through four corners (anticlockwise seen from where `normal` points).
	const quad = (corners, normal, part, uv, edge = 0) => {
		const at = positions.length / 3;
		for (const [x, y, z] of corners) {
			positions.push(x, y, z);
			normals.push(...normal);
			uvs.push(...uv(x, y));
			parts.push(part);
			edges.push(edge);
			ghostOf.push(ghost);
		}
		index.push(at, at + 1, at + 2, at, at + 2, at + 3);
	};
	const letter = (x, y) => [x + 0.5, y + 0.5];
	const turned = (x, y) => [x + 0.5, 0.5 - y];   // the falling flap's back, turned over, shows a bottom half
	// A thin box from (x0, y0) to (x1, y1), from z0 (back) to z1 (front): its front (and back, if it has one) and sides.
	const box = (x0, y0, x1, y1, z0, z1, front, back) => {
		quad([[x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]], [0, 0, 1], front, letter);
		if (back !== undefined) quad([[x1, y0, z0], [x0, y0, z0], [x0, y1, z0], [x1, y1, z0]], [0, 0, -1], back, turned);
		quad([[x0, y1, z1], [x1, y1, z1], [x1, y1, z0], [x0, y1, z0]], [0, 1, 0], front, letter, 1);   // top
		quad([[x0, y0, z0], [x1, y0, z0], [x1, y0, z1], [x0, y0, z1]], [0, -1, 0], front, letter, 1);   // bottom
		quad([[x0, y0, z0], [x0, y0, z1], [x0, y1, z1], [x0, y1, z0]], [-1, 0, 0], front, letter, 1);   // left
		quad([[x1, y0, z1], [x1, y0, z0], [x1, y1, z0], [x1, y1, z1]], [1, 0, 0], front, letter, 1);   // right
	};
	const half = FLAPS.pitch / 2;
	if (ghosts) {
		for (ghost = 1; ghost <= ghosts; ghost++) box(-0.5, seam, 0.5, 0.5, FLAP_Z - FLAP_THICK, FLAP_Z, 2, 3);
	} else {
		quad([[-half, -FLAPS.row / 2, -0.03], [half, -FLAPS.row / 2, -0.03], [half, FLAPS.row / 2, -0.03], [-half, FLAPS.row / 2, -0.03]], [0, 0, 1], 4, letter);
		box(-0.5, seam, 0.5, 0.5, -FLAP_THICK, 0, 0);
		box(-0.5, -0.5, 0.5, -seam, -FLAP_THICK, 0, 1);
		box(-0.5, seam, 0.5, 0.5, FLAP_Z - FLAP_THICK, FLAP_Z, 2, 3);
	}
	const geometry = new THREE.BufferGeometry();
	geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
	geometry.setAttribute("normal", new THREE.Float32BufferAttribute(normals, 3));
	geometry.setAttribute("uv", new THREE.Float32BufferAttribute(uvs, 2));
	geometry.setAttribute("part", new THREE.Float32BufferAttribute(parts, 1));
	geometry.setAttribute("edge", new THREE.Float32BufferAttribute(edges, 1));
	geometry.setAttribute("ghost", new THREE.Float32BufferAttribute(ghostOf, 1));
	geometry.setIndex(index);
	return geometry;
}

// The flaps' shader: per flap (instance) the four letters (top, bottom, front, back), the falling flap's angle and the
// colours of its face and letter. Lit by the three lights (FLAPS.lights); a flap falling shades the half below it.
// trail: for the motion blur's ghosts (flapGeometry with ghosts): each ghost where the flap was a little earlier in
// this frame (its angle minus how far it fell while the shutter was open, `shutter` seconds), see-through, fading out.
function flapShader(THREE, atlas, trail = false) {
	const columns = LETTER_TILE.columns, rows = Math.ceil(FLAPS.letters.length / columns);
	const { strength } = FLAPS.blur;
	return new THREE.ShaderMaterial({
		transparent: trail,
		depthWrite: !trail,
		uniforms: {
			shutter: { value: FLAPS.blur.shutter / 60 },
			atlas: { value: atlas },
			grid: { value: new THREE.Vector2(columns, rows) },
			aspect: { value: FLAPS.aspect },
			palette: { value: FLAPS.palette.map((c) => new THREE.Vector3(...c)) },
		},
		vertexShader: `
			attribute float part;
			attribute float edge;
			attribute vec4 aChars;
			attribute float aAngle;
			attribute float aSpeed;
			attribute float ghost;
			attribute float aGhosts;   // how many ghosts this flap has
			uniform float shutter;
			varying float vAlpha;
			attribute vec3 aFace;
			attribute vec3 aInk;
			uniform vec2 grid;
			uniform vec3 palette[${FLAPS.palette.length}];
			varying vec2 vUv;
			varying vec2 vTile;
			varying vec3 vFace;
			varying vec3 vInk;
			varying float vShade;
			varying float vPart;
			varying float vSolid;
			varying float vEdge;
			void main() {
				vec3 p = position;
				vec3 n = normal;
				float angle = aAngle;
				vAlpha = 1.0;
				if (ghost > 0.5) {   // a ghost: where it was ghost / aGhosts of the shutter time ago
					angle = aAngle - aSpeed * shutter * ghost / aGhosts;
					// not falling, or a ghost more than this flap has: not drawn
					if (aSpeed <= 0.0 || angle <= 0.0 || ghost > aGhosts + 0.5) { gl_Position = vec4(2.0, 2.0, 2.0, 1.0); return; }
					vAlpha = ${strength.toFixed(3)} * (1.0 - (ghost - 1.0) / aGhosts);
				}
				if (part > 1.5 && part < 3.5) {   // the falling flap: around its middle, towards us and down
					float s = sin(angle), c = cos(angle);
					float pivot = ${(FLAP_Z - FLAP_THICK / 2).toFixed(4)};
					float z = p.z - pivot;
					p.yz = vec2(p.y * c - z * s, p.y * s + z * c + pivot);
					n.yz = vec2(n.y * c - n.z * s, n.y * s + n.z * c);
				}
				float letter = part < 0.5 ? aChars.x : part < 1.5 ? aChars.y : part < 2.5 ? aChars.z : aChars.w;
				vTile = vec2(mod(letter, grid.x), floor((letter + 0.5) / grid.x));
				vUv = uv;
				vFace = aFace;
				vInk = aInk;
				vSolid = 0.0;
				if (letter > ${SOLID}.0 - 0.5) {   // a colour, no letter
					vFace = palette[int(letter - ${SOLID}.0 + 0.5)];
					vSolid = 1.0;
				}
				vPart = part;
				vEdge = edge;
				vec4 world = modelMatrix * instanceMatrix * vec4(p, 1.0);
				gl_Position = projectionMatrix * viewMatrix * world;
				vec3 normal = normalize(mat3(modelMatrix) * mat3(instanceMatrix) * n);
				// The same three lights as the case (FLAPS.lights): key, fill and back.
				float shade = 0.36 + 0.6 * max(dot(normal, normalize(vec3(${FLAPS.lights.key.from.map((v) => v.toFixed(1))}))), 0.0)
					+ 0.18 * max(dot(normal, normalize(vec3(${FLAPS.lights.fill.from.map((v) => v.toFixed(1))}))), 0.0)
					+ 0.45 * max(dot(normal, normalize(vec3(${FLAPS.lights.back.from.map((v) => v.toFixed(1))}))), 0.0);
				if (edge < 0.5) shade *= 0.86 + 0.28 * abs(uv.y - 0.5);   // a little darker towards the split
				if (part > 0.5 && part < 1.5) shade *= 1.0 - 0.45 * sin(aAngle);   // under a falling flap
				vShade = shade;
			}
		`,
		fragmentShader: `
			uniform sampler2D atlas;
			uniform vec2 grid;
			uniform float aspect;
			varying vec2 vUv;
			varying vec2 vTile;
			varying vec3 vFace;
			varying vec3 vInk;
			varying float vShade;
			varying float vPart;
			varying float vSolid;
			varying float vEdge;
			varying float vAlpha;
			void main() {
				if (vPart > 3.5) { gl_FragColor = vec4(0.02, 0.02, 0.025, 1.0); return; }   // the black window
				if (vEdge > 0.5) { gl_FragColor = vec4(vFace * vShade * 0.85, vAlpha); return; }   // a side of a flap
				vec2 size = vec2(aspect, 1.0);   // rounded corners
				vec2 q = abs(vUv - 0.5) * size - (size * 0.5 - 0.07);
				if (length(max(q, 0.0)) > 0.07) discard;
				vec2 at = vec2((vTile.x + vUv.x) / grid.x, 1.0 - (vTile.y + 1.0 - vUv.y) / grid.y);
				float ink = vSolid > 0.5 ? 0.0 : texture2D(atlas, at).r;
				gl_FragColor = vec4(mix(vFace, vInk, ink) * vShade, vAlpha);
			}
		`,
	});
}

// The motion blur test (templates/slides/bieruur_blur.html, BieruurBlurTestProvider in providers/bieruur.py): two
// displays side by side, without and with motion blur (FLAPS.blur), playing the last seconds before bieruur and the
// party over and over (DEMO). One clock for both, which Pause (or P) stops, to compare them standing still; Slow
// motion (or S) runs it at a fifth of the speed (data-rate), to watch a flap fall and bounce; Restart (or R) starts over. Each round the displays start afresh (new canvases).
const DEMO = { countdown: 5, party: 25 };   // seconds: the party long enough to see the fluid flow
function setupBieruurDemo(root) {
	const halves = [...root.querySelectorAll(".bieruur-slide")];
	const pause = root.querySelector("[data-bieruur-pause]"), restart = root.querySelector("[data-bieruur-restart]");
	const slow = root.querySelector("[data-bieruur-slow]");
	let t = 0, last = null, round = 0;
	const show = (s) => {   // s seconds into a round: the countdown, then bieruur
		const left = Math.ceil(DEMO.countdown - s);
		const [time, phase, label] = left > 0 ? [`00:00:0${left}`, "final", "Bijna bieruur!"] : ["00:00:00", "bieruur", "Het is bieruur!"];
		halves.forEach((half) => {
			const info = half.querySelector(".bieruur-info");
			if (info.dataset.phase !== phase) info.dataset.phase = phase;
			if (info.querySelector(".bieruur-countdown").textContent !== time) info.querySelector(".bieruur-countdown").textContent = time;
			if (info.querySelector(".bieruur-label").textContent !== label) info.querySelector(".bieruur-label").textContent = label;
		});
	};
	const fresh = () => halves.forEach((half) => {
		const old = half.querySelector("canvas[data-bieruur-3d]"), canvas = old.cloneNode();
		old.replaceWith(canvas);   // the old one frees itself (see drawBieruur3d)
		setupBieruur3d(canvas);
	});
	const frame = (now) => {
		if (!document.contains(root)) return;
		requestAnimationFrame(frame);
		if (last !== null && root.dataset.frozen !== "true") t += (now - last) / 1000 * Number(root.dataset.rate ?? 1);
		last = now;
		const length = DEMO.countdown + DEMO.party, n = Math.floor(t / length);
		show(t - n * length);
		if (n !== round) {
			round = n;
			fresh();
		}
	};
	pause.addEventListener("click", () => {
		const frozen = root.dataset.frozen !== "true";
		root.dataset.frozen = frozen;
		pause.textContent = frozen ? "Play" : "Pause";
		pause.classList.toggle("selected", frozen);
	});
	slow.addEventListener("click", () => {
		const slower = root.dataset.rate !== "0.2";
		root.dataset.rate = slower ? 0.2 : 1;
		slow.classList.toggle("selected", slower);
	});
	restart.addEventListener("click", () => {
		t = 0;
		round = 0;
		show(0);
		fresh();
	});
	const keys = (event) => {   // clicks, so the slideshow stays on this slide like for a tap
		if (!document.contains(root)) return document.removeEventListener("keydown", keys);
		if (event.ctrlKey || event.altKey || event.metaKey) return;
		if (event.key === "p") pause.click();
		else if (event.key === "r") restart.click();
		else if (event.key === "s") slow.click();
	};
	document.addEventListener("keydown", keys);
	requestAnimationFrame(frame);
}
