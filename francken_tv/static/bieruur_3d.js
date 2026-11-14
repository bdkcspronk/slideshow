// The bieruur countdown as a split-flap display in 3D (templates/slides/bieruur.html, providers/bieruur.py), drawn
// with Three.js (static/vendor/three), like the departure boards at a station.
//
// The time left, always as HH:MM:SS, on a row of flaps in a display hanging on the wall (the slide's background:
// white plaster; the canvas is see-through), where the countdown's text is on the page; the label above it ("Bieruur
// in") stays text. Around the time, above, beside and below it, half-size flaps without letters, in colours, which
// flip in waves every few seconds, so their colours move in a pattern (stripes, rings around the time, a wipe, rain;
// the next pattern every few waves, and faster waves in the last two minutes).
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
	flip: 0.16,   // seconds per flap falling
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
	const countdown = slide.querySelector('[data-live="countdown"]');
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
	const flaps = Array.from({ length: n }, (_, c) => ({ wheel: digits, size: fh,
		x: left + filler.beside * step / 2 + (c + 0.5) * step, y: top - filler.above * rowH / 2 - rowH / 2, from: 0, steps: 0, start: 0 }));
	const fillers = [];
	for (let j = 0; j < rows; j++) {
		for (let i = 0; i < cols; i++) {
			const inTime = i >= filler.beside && i < filler.beside + 2 * n && j >= filler.above && j < filler.above + 2;
			if (!inTime) fillers.push({ wheel: colourWheel, size: fh / 2, i, j,
				x: left + (i + 0.5) * step / 2, y: top - (j + 0.5) * rowH / 2, from: 0, steps: 0, start: 0 });
		}
	}
	flaps.push(...fillers);
	const count = flaps.length;

	// Send a flap to wheel position `target`, from where it is at t (also halfway falling: it carries on from there).
	// now: be there at once, without falling.
	const at = (flap, t) => Math.min(flap.steps, Math.max(0, Math.floor((t - flap.start) / FLAPS.flip)));
	const turnTo = (flap, target, t, now = false) => {
		if (target < 0) return;
		if (now) return void Object.assign(flap, { from: target, steps: 0, start: t });
		const k = at(flap, t);
		flap.from = (flap.from + k) % flap.wheel.length;
		if (k < flap.steps && t >= flap.start) flap.start += k * FLAPS.flip;   // carries on falling
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
	const wavePause = () => (slide.classList.contains("bieruur-final") ? filler.final : filler.wave);

	// The display's case on the wall: a dark box `thick` deep with bevelled edges (seen from the front, they are what
	// shows it stands out: lit on the top left, dark on the bottom right), a narrow rim around the board, and its soft
	// shadow on the wall, down and to the right (the key light comes from the top left).
	const rim = fh * 0.12, thick = fh * FLAPS.thickness;
	const caseW = boardW + 2 * rim, caseH = boardH + 2 * rim, bevel = rim * 0.6;
	const outline = new THREE.Shape();
	const ow = caseW / 2 - bevel, oh = caseH / 2 - bevel;
	outline.moveTo(-ow, -oh).lineTo(ow, -oh).lineTo(ow, oh).lineTo(-ow, oh).closePath();
	const housing = new THREE.Mesh(new THREE.ExtrudeGeometry(outline, { depth: thick - 2 * bevel, bevelEnabled: true,
		bevelThickness: bevel, bevelSize: bevel, bevelSegments: 4 }),
		new THREE.MeshStandardMaterial({ color: colours.case, roughness: 0.45, metalness: 0.35 }));
	housing.position.set(0, y, bevel);   // its back against the wall
	scene.add(housing);
	const blur = fh * 0.45;
	const shade = shadowTexture(THREE, caseW, caseH, blur);
	const shadow = new THREE.Mesh(new THREE.PlaneGeometry(caseW + 2 * blur, caseH + 2 * blur),
		new THREE.MeshBasicMaterial({ map: shade, transparent: true, depthWrite: false }));
	shadow.position.set(thick * 0.5, y - thick * 0.8, 0.01);
	scene.add(shadow);

	// The flaps on the front of the case.
	const atlas = letterAtlas(THREE);
	const flapMaterial = flapShader(THREE, atlas);
	const geometry = flapGeometry(THREE);
	const mesh = new THREE.InstancedMesh(geometry, flapMaterial, count);
	const chars = new THREE.InstancedBufferAttribute(new Float32Array(count * 4), 4);
	const angles = new THREE.InstancedBufferAttribute(new Float32Array(count), 1);
	[chars, angles].forEach((a) => a.setUsage(THREE.DynamicDrawUsage));
	geometry.setAttribute("aChars", chars);
	geometry.setAttribute("aAngle", angles);
	geometry.setAttribute("aFace", new THREE.InstancedBufferAttribute(new Float32Array(flaps.flatMap(() => colours.face)), 3));
	geometry.setAttribute("aInk", new THREE.InstancedBufferAttribute(new Float32Array(flaps.flatMap(() => colours.ink)), 3));
	const matrix = new THREE.Matrix4();
	flaps.forEach((flap, c) => {
		matrix.makeScale(flap.size * aspect, flap.size, flap.size).setPosition(flap.x, flap.y, thick + flap.size * 0.04);
		mesh.setMatrixAt(c, matrix);
	});
	mesh.frustumCulled = false;   // the flaps move out of the box three.js thinks they are in
	scene.add(mesh);

	spell(first, 0, true);
	flapWave(0, true);
	let shown = first, nextWave = wavePause();

	// Where every flap is at t seconds after the slide was shown; true while one moves (or is about to).
	const pose = (t) => {
		let moving = false;
		flaps.forEach((flap, c) => {
			const wheel = flap.wheel, N = wheel.length;
			const e = t - flap.start;
			const k = Math.floor(e / FLAPS.flip);
			let top, bottom, front, back, angle = 0;
			if (e < 0 || flap.steps === 0) top = bottom = front = back = wheel[flap.from];
			else if (k >= flap.steps) top = bottom = front = back = wheel[(flap.from + flap.steps) % N];
			else {
				// Letter `now` falls away and shows `next`: the falling flap has now's top half on its front and
				// next's bottom half on its back; behind it the fixed halves are next's top and now's bottom.
				const now = wheel[(flap.from + k) % N], next = wheel[(flap.from + k + 1) % N];
				top = next; bottom = now; front = now; back = next;
				const p = e / FLAPS.flip - k;
				angle = Math.PI * p * p;   // falling faster and faster
			}
			if (flap.steps > 0 && (e < 0 || k < flap.steps)) moving = true;
			chars.setXYZW(c, top, bottom, front, back);
			angles.setX(c, angle);
		});
		chars.needsUpdate = angles.needsUpdate = true;
		return moving;
	};
	pose(0);
	renderer.render(scene, camera);   // there at once, also while the slide is still coming in

	// One frame at a time while the slide is on the page, drawn only when something moves; freed when it's gone
	// (the browser has only a few WebGL contexts).
	let started = null, measured = false, still = true, previous = null;
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
		started ??= now;
		const t = (now - started) / 1000;
		const time = text();
		if (time !== shown) {   // the next second
			shown = time;
			spell(time, t);
			still = false;
		}
		if (t >= nextWave) {   // the next wave over the filler flaps
			flapWave(t);
			nextWave = t + wavePause();
			still = false;
		}
		if (still) return void (previous = null);
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
const FLAP_THICK = 0.025, FLAP_Z = FLAP_THICK + 0.005;   // the falling flap's front; it turns around its middle
function flapGeometry(THREE) {
	const seam = 0.012;   // half the gap between the halves
	const positions = [], normals = [], uvs = [], parts = [], edges = [], index = [];
	// A quad through four corners (anticlockwise seen from where `normal` points).
	const quad = (corners, normal, part, uv, edge = 0) => {
		const at = positions.length / 3;
		for (const [x, y, z] of corners) {
			positions.push(x, y, z);
			normals.push(...normal);
			uvs.push(...uv(x, y));
			parts.push(part);
			edges.push(edge);
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
	quad([[-half, -FLAPS.row / 2, -0.03], [half, -FLAPS.row / 2, -0.03], [half, FLAPS.row / 2, -0.03], [-half, FLAPS.row / 2, -0.03]], [0, 0, 1], 4, letter);
	box(-0.5, seam, 0.5, 0.5, -FLAP_THICK, 0, 0);
	box(-0.5, -0.5, 0.5, -seam, -FLAP_THICK, 0, 1);
	box(-0.5, seam, 0.5, 0.5, FLAP_Z - FLAP_THICK, FLAP_Z, 2, 3);
	const geometry = new THREE.BufferGeometry();
	geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
	geometry.setAttribute("normal", new THREE.Float32BufferAttribute(normals, 3));
	geometry.setAttribute("uv", new THREE.Float32BufferAttribute(uvs, 2));
	geometry.setAttribute("part", new THREE.Float32BufferAttribute(parts, 1));
	geometry.setAttribute("edge", new THREE.Float32BufferAttribute(edges, 1));
	geometry.setIndex(index);
	return geometry;
}

// The flaps' shader: per flap (instance) the four letters (top, bottom, front, back), the falling flap's angle and the
// colours of its face and letter. Lit by the three lights (FLAPS.lights); a flap falling shades the half below it.
function flapShader(THREE, atlas) {
	const columns = LETTER_TILE.columns, rows = Math.ceil(FLAPS.letters.length / columns);
	return new THREE.ShaderMaterial({
		uniforms: {
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
				if (part > 1.5 && part < 3.5) {   // the falling flap: around its middle, towards us and down
					float s = sin(aAngle), c = cos(aAngle);
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
			void main() {
				if (vPart > 3.5) { gl_FragColor = vec4(0.02, 0.02, 0.025, 1.0); return; }   // the black window
				if (vEdge > 0.5) { gl_FragColor = vec4(vFace * vShade * 0.85, 1.0); return; }   // a side of a flap
				vec2 size = vec2(aspect, 1.0);   // rounded corners
				vec2 q = abs(vUv - 0.5) * size - (size * 0.5 - 0.07);
				if (length(max(q, 0.0)) > 0.07) discard;
				vec2 at = vec2((vTile.x + vUv.x) / grid.x, 1.0 - (vTile.y + 1.0 - vUv.y) / grid.y);
				float ink = vSolid > 0.5 ? 0.0 : texture2D(atlas, at).r;
				gl_FragColor = vec4(mix(vFace, vInk, ink) * vShade, 1.0);
			}
		`,
	});
}
