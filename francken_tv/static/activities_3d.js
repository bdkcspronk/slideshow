// The upcoming activities as split-flap displays in 3D (templates/slides/activities.html, providers/activities.py),
// drawn with Three.js (static/vendor/three), like the departure boards at a station.
//
// One display per activity, where its card is on the page (the cards are hidden; they are what is shown without
// WebGL): a dark metal housing (crimson for today's activities) with rows of flaps in black windows. On the left the
// date (weekday, day, month) on crimson flaps; on the right the title on one or two lines and the details (when,
// time, location) in amber. They hang on a white wall (the slide's background, style.css), each with a soft shadow on
// it. The displays swing down into place one after the other, hinged at their top edge, bouncing off the wall, then
// every flap clatters through the letters (" ", A to Z, 0 to 9, a few signs) until it shows its own. The camera
// drifts a little, so the housings and flaps show they are 3D.
//
// Each flap is a real split flap: the top half of the letter on a flap that falls forward around the middle, the
// bottom half of the next letter on its back, the halves of the letters behind it on the fixed halves above and below.
//
// Kept within what the TV PC can do (docs/07-3d-limits.md): all flaps of a display are one InstancedMesh (5 quads
// each: the black window behind, the two fixed halves and the falling flap's two sides), drawn by a small shader from
// one texture holding every letter; with its housing and its shadow (a blurred picture, not a shadow map) that is 3
// draw calls per display, at most about 30, and some 10,000 triangles. Like the books, it drops to 75% resolution if its first seconds draw slowly.
//
// One unit in the 3D world is 1vh: the camera is DISTANCE in front of the screen, so at z = 0 the world is the size of
// the page. bevelledBox() and cubicBezier() are in static/books_3d.js.

const FLAPS = {
	distance: 140,   // the camera, in front of the screen
	letters: " ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,:-·/&'!?()+#",   // in the order the flaps go round
	aspect: 0.6,   // a flap's width / its height
	pitch: 1.12,   // from one flap to the next, in flap widths (the black between them)
	flip: 0.055,   // seconds per flap falling: about 18 letters a second, like the real ones
	housingDepth: 3.2,
	colours: {   // the flaps (r, g, b; as on the screen) and the housing
		face: [0.11, 0.115, 0.13],   // a flap
		title: [0.97, 0.94, 0.86],   // the title's letters: cream
		details: [1.0, 0.76, 0.24],   // the details: amber
		date: [0.74, 0.05, 0.16],   // the date's flaps: crimson
		todayDate: [0.07, 0.14, 0.27],   // on a crimson (today) display: navy
		white: [1, 1, 1],
		housing: 0x262a31,
		todayHousing: 0xc8102e,
	},
};

function setupActivities3d(canvas) {
	const slide = canvas.closest(".activities-slide");
	slide.classList.add("activities-flaps");   // hides the cards (so they stand still where the displays go)
	loadThree().then((THREE) => {
		if (document.contains(canvas)) return drawActivities3d(THREE, canvas, slide);
	}).catch((error) => {
		console.warn("Activities in 3D:", error);
		slide.classList.remove("activities-flaps");   // the cards instead
	});
}

async function drawActivities3d(THREE, canvas, slide) {
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
	const { distance, colours } = FLAPS;
	let quality = 1;
	const resize = () => {
		renderer.setPixelRatio(devicePixelRatio * quality);
		renderer.setSize(canvas.clientWidth, canvas.clientHeight, false);
	};
	resize();
	const camera = new THREE.PerspectiveCamera(2 * Math.atan(height / 2 / distance) * 180 / Math.PI, width / height, 10, 1000);
	camera.position.set(0, 0, distance);
	const onPage = (x, y) => ({ x: (x - box.left) / vh - width / 2, y: height / 2 - (y - box.top) / vh });

	const scene = new THREE.Scene();
	scene.add(new THREE.HemisphereLight(0xf4f0ff, 0x30384a, 1.6));
	const key = new THREE.DirectionalLight(0xfff4e6, 2.4);
	key.position.set(-4, 5, 8);
	scene.add(key);
	const fill = new THREE.DirectionalLight(0xffffff, 0.8);   // the light off the white wall, on the edges
	fill.position.set(5, -2, 3);
	scene.add(fill);
	const shadowPicture = shadowTexture(THREE);

	const atlas = letterAtlas(THREE);
	const flapMaterial = flapShader(THREE, atlas);
	const geometry = flapGeometry(THREE);
	const housingMaterials = {
		normal: new THREE.MeshStandardMaterial({ color: colours.housing, roughness: 0.4, metalness: 0.3 }),
		today: new THREE.MeshStandardMaterial({ color: colours.todayHousing, roughness: 0.45, metalness: 0.15 }),
	};

	// A display per card. Random but the same every time: where each flap starts and how long it waits.
	let seed = 11;
	const random = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
	const cards = [...slide.querySelectorAll("li[data-flaps]")];
	const displays = cards.map((card, i) => {
		const r = card.getBoundingClientRect();
		const topLeft = onPage(r.left, r.top), bottomRight = onPage(r.right, r.bottom);
		const w = bottomRight.x - topLeft.x, h = topLeft.y - bottomRight.y;
		const today = card.classList.contains("today");
		const flaps = layOut(JSON.parse(card.dataset.flaps), w, h, today);

		// Hinged at its top edge (the group's origin), so it can swing down into place.
		const group = new THREE.Group();
		group.position.set(topLeft.x + w / 2, topLeft.y, 0);
		const housing = new THREE.Mesh(bevelledBox(THREE, w, h, FLAPS.housingDepth, 0.6, 1.2), today ? housingMaterials.today : housingMaterials.normal);
		housing.position.set(0, -h / 2, -FLAPS.housingDepth / 2);
		group.add(housing);

		const mesh = new THREE.InstancedMesh(geometry, flapMaterial, flaps.length);
		const chars = new THREE.InstancedBufferAttribute(new Float32Array(flaps.length * 4), 4);
		const angles = new THREE.InstancedBufferAttribute(new Float32Array(flaps.length), 1);
		const face = new THREE.InstancedBufferAttribute(new Float32Array(flaps.flatMap((f) => f.face)), 3);
		const ink = new THREE.InstancedBufferAttribute(new Float32Array(flaps.flatMap((f) => f.ink)), 3);
		[chars, angles].forEach((a) => a.setUsage(THREE.DynamicDrawUsage));
		mesh.geometry = geometry.clone();   // each display its own letters and angles
		mesh.geometry.setAttribute("aChars", chars);
		mesh.geometry.setAttribute("aAngle", angles);
		mesh.geometry.setAttribute("aFace", face);
		mesh.geometry.setAttribute("aInk", ink);
		const matrix = new THREE.Matrix4();
		const start = 0.3 + i * 0.18;   // when it swings in
		flaps.forEach((flap, n) => {
			matrix.makeScale(flap.h * FLAPS.aspect, flap.h, flap.h).setPosition(flap.x, -h / 2 + flap.y, 0.15);
			mesh.setMatrixAt(n, matrix);
			const target = flap.letter;
			const from = Math.floor(random() * FLAPS.letters.length);
			flap.from = from;
			flap.steps = (target - from + FLAPS.letters.length) % FLAPS.letters.length;
			flap.start = start + 0.4 + random() * 0.5;   // once it hangs still, each flap a little after the other
		});
		mesh.frustumCulled = false;   // the flaps move out of the box three.js thinks they are in
		group.add(mesh);
		group.visible = false;
		scene.add(group);

		// Its shadow on the wall, a little down and to the right (the light comes from the top left); as dark as the
		// display is flat against the wall.
		const shadow = new THREE.Mesh(new THREE.PlaneGeometry(w * SHADOW.w, h * SHADOW.h),
			new THREE.MeshBasicMaterial({ map: shadowPicture, transparent: true, depthWrite: false, opacity: 0 }));
		shadow.position.set(topLeft.x + w / 2 + 0.8, topLeft.y - h / 2 - 1.4, -FLAPS.housingDepth - 0.05);
		scene.add(shadow);
		return { group, shadow, flaps, chars, angles, start, settled: false };
	});

	// Where everything is at t seconds after the slide was shown.
	const N = FLAPS.letters.length;
	const pose = (t) => {
		for (const display of displays) {
			const s = t - display.start;
			display.group.visible = s >= 0;
			// Swinging down from folded up (bottom edge towards us), hitting the wall and bouncing off it, smaller
			// each time: a damped swing that can't go through the wall.
			const swingAngle = s < 0 ? -Math.PI / 2 : -Math.PI / 2 * Math.exp(-4.5 * s) * Math.abs(Math.cos(7 * s));
			display.group.rotation.x = swingAngle;
			display.shadow.material.opacity = s < 0 ? 0 : Math.cos(swingAngle) ** 3;
			if (display.settled) continue;
			let moving = false;
			display.flaps.forEach((flap, n) => {
				const e = t - flap.start;
				const k = Math.floor(e / FLAPS.flip);
				let top, bottom, front, back, angle = 0;
				if (e < 0) top = bottom = front = back = flap.from;
				else if (k >= flap.steps) top = bottom = front = back = flap.letter;
				else {
					// Letter `now` falls away and shows `next`: the falling flap has now's top half on its front and
					// next's bottom half on its back; behind it the fixed halves are next's top and now's bottom.
					const now = (flap.from + k) % N, next = (now + 1) % N;
					top = next; bottom = now; front = now; back = next;
					const p = e / FLAPS.flip - k;
					angle = Math.PI * p * p;   // falling faster and faster
				}
				if (e < 0 || k < flap.steps) moving = true;
				display.chars.setXYZW(n, top, bottom, front, back);
				display.angles.setX(n, angle);
			});
			display.chars.needsUpdate = display.angles.needsUpdate = true;
			display.settled = !moving;
		}
		// A slow drift of the camera, always looking at the middle of the page.
		camera.position.set(Math.sin(t * 0.21) * 7, Math.sin(t * 0.13 + 1) * 3, distance);
		camera.lookAt(0, 0, 0);
	};
	pose(0);

	// One frame at a time while the slide is on the page; freed when it's gone (the browser has only a few WebGL contexts).
	const layer = canvas.closest(".layer");
	let started = null, measured = false;
	const times = [];
	const frame = (now) => {
		if (!document.contains(canvas)) {
			atlas.dispose();
			flapMaterial.dispose();
			Object.values(housingMaterials).forEach((m) => m.dispose());
			geometry.dispose();
			scene.traverse((o) => { o.geometry?.dispose(); if (o.material !== flapMaterial) [o.material].flat().forEach((m) => m?.dispose()); });
			shadowPicture.dispose();
			renderer.dispose();
			renderer.forceContextLoss();
			return;
		}
		requestAnimationFrame(frame);
		if (layer?.classList.contains("loading")) return;   // not shown yet: the CSS animations wait too
		started ??= now;
		const t = (now - started) / 1000;
		pose(t);
		renderer.render(scene, camera);
		// Too slow for this PC? Measure from 0.5 to 3 s (everything moving) and drop to 75% resolution once.
		if (!measured && t > 0.5) {
			times.push(now);
			if (t > 3) {
				measured = true;
				const gaps = times.slice(1).map((time, n) => time - times[n]).sort((p, q) => p - q);
				if (gaps[Math.floor(gaps.length / 2)] > 20) {
					quality = 0.75;
					resize();
					console.info("Activities in 3D: slow frames, drawing at 75% resolution");
				}
			}
		}
	};
	requestAnimationFrame(frame);
}

// A display's shadow: a blurred dark rounded rectangle on a transparent picture; the picture is SHADOW times the
// display's width and height, the blur spilling out around it.
const SHADOW = { w: 512 / 416, h: 256 / 176 };
function shadowTexture(THREE) {
	const canvas = document.createElement("canvas");
	canvas.width = 512;
	canvas.height = 256;
	const ctx = canvas.getContext("2d");
	ctx.filter = "blur(18px)";
	ctx.fillStyle = "rgba(20, 22, 30, 0.55)";
	ctx.beginPath();
	if (ctx.roundRect) ctx.roundRect(48, 40, 416, 176, 14);
	else ctx.rect(48, 40, 416, 176);
	ctx.fill();
	const texture = new THREE.CanvasTexture(canvas);
	texture.colorSpace = THREE.SRGBColorSpace;
	return texture;
}

// Where the flaps of a display w x h (vh) go, and what each shows: a list of { x, y (from the display's middle), h
// (the flap's height), letter (its index in FLAPS.letters), face and ink (colours) }. On the left the date block
// (weekday, day, month above each other), on the right the title (one line, or two smaller ones if it is long) and the
// details below it. Every line of flaps runs the whole width there; the flaps after the text stay blank.
function layOut(text, w, h, today) {
	const { colours, aspect, pitch } = FLAPS;
	const flaps = [];
	const step = (fh) => fh * aspect * pitch;   // from one flap to the next
	const line = (string, n, x, y, fh, face, ink, centred = false) => {
		const chars = [...string];
		const left = centred ? x - (chars.length * step(fh)) / 2 : x;
		for (let c = 0; c < (centred ? chars.length : n); c++) {
			const index = FLAPS.letters.indexOf(chars[c] ?? " ");
			flaps.push({ x: left + (c + 0.5) * step(fh), y, h: fh, letter: Math.max(0, index), face, ink });
		}
	};
	const pad = Math.min(0.12 * h, 2.2);
	const inner = h - 2 * pad;

	// The date: the day big, the weekday and month above and below it.
	const small = inner * 0.24, big = inner * 0.42, gap = (inner - 2 * small - big) / 2;
	const dateW = Math.max(3 * step(small), 2 * step(big));
	const dateX = -w / 2 + pad + dateW / 2;
	const dateFace = today ? colours.todayDate : colours.date;
	line(flapText(text.weekday).slice(0, 3), 3, dateX, inner / 2 - small / 2, small, dateFace, colours.white, true);
	line(flapText(text.day).slice(0, 2), 2, dateX, inner / 2 - small - gap - big / 2, big, dateFace, colours.white, true);
	line(flapText(text.month).slice(0, 3), 3, dateX, -inner / 2 + small / 2, small, dateFace, colours.white, true);

	// The title and the details, as a block in the middle of the height.
	const left = -w / 2 + pad + dateW + pad * 1.3;
	const room = w / 2 - pad - left;
	const title = flapText(text.title), details = flapText(text.details);
	const one = inner * 0.5, two = inner * 0.33, detailsH = inner * 0.27;
	let titleLines, titleH;
	const n1 = Math.floor(room / step(one));
	if (title.length <= n1) [titleLines, titleH] = [[title], one];
	else {
		titleH = two;
		titleLines = wrapFlaps(title, Math.floor(room / step(two)), 2);
	}
	const nTitle = Math.floor(room / step(titleH)), nDetails = Math.floor(room / step(detailsH));
	const between = titleH * 0.12;
	const total = titleLines.length * titleH + (titleLines.length - 1) * between + detailsH + inner * 0.08;
	let y = total / 2;
	for (const words of titleLines) {
		line(words, nTitle, left, y - titleH / 2, titleH, colours.face, colours.title);
		y -= titleH + between;
	}
	line(fitFlaps(details, nDetails), nDetails, left, -total / 2 + detailsH / 2, detailsH, colours.face, colours.details);
	return flaps;
}

// Text as the flaps can show it: capitals without accents; letters they don't have become a space.
function flapText(text) {
	const plain = String(text ?? "").normalize("NFD").replace(/[̀-ͯ]/g, "").toUpperCase()
		.replace(/[‘’`´]/g, "'").replace(/[“”"]/g, "'").replace(/[–—]/g, "-").replace(/ß/g, "SS").replace(/…/g, "...");
	return [...plain].map((c) => (FLAPS.letters.includes(c) ? c : " ")).join("").replace(/\s+/g, " ").trim();
}

// At most n letters: a location loses its last parts after a comma first, then it is cut at a space.
function fitFlaps(text, n) {
	if (text.length <= n) return text;
	const parts = text.split(", ");
	while (parts.length > 1 && parts.join(", ").length > n) parts.pop();
	text = parts.join(", ");
	if (text.length > n) {
		const space = text.lastIndexOf(" ", n);
		text = text.slice(0, space > n / 2 ? space : n);
	}
	return text.replace(/[\s·,:-]+$/, "");
}

// The words in at most `most` lines of n letters; what doesn't fit is cut off the last line.
function wrapFlaps(text, n, most) {
	const lines = [];
	let words = text.split(" ");
	while (words.length && lines.length < most) {
		if (lines.length === most - 1) {
			lines.push(fitFlaps(words.join(" "), n));
			break;
		}
		let line = words.shift();
		while (words.length && `${line} ${words[0]}`.length <= n) line += ` ${words.shift()}`;
		lines.push(line.length > n ? line.slice(0, n) : line);
	}
	return lines;
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

// One flap position, 1 high and 1 wide (the instance matrix stretches it to the flap's size): five quads, each with
// its `part`: 0 the fixed top half, 1 the fixed bottom half, 2 and 3 the falling flap's front and back (at rest over
// the top half, slightly in front), 4 the black window behind. uv is where on the letter's tile each point is.
const FLAP_Z = 0.02;
function flapGeometry(THREE) {
	const seam = 0.012;   // half the gap between the halves
	const positions = [], uvs = [], parts = [], index = [];
	const quad = (x0, y0, x1, y1, z, part, uv, back = false) => {
		const at = positions.length / 3;
		for (const [x, y] of [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]) {
			positions.push(x, y, z);
			uvs.push(...uv(x, y));
			parts.push(part);
		}
		index.push(...(back ? [at, at + 2, at + 1, at, at + 3, at + 2] : [at, at + 1, at + 2, at, at + 2, at + 3]));
	};
	const letter = (x, y) => [x + 0.5, y + 0.5];
	const half = FLAPS.pitch / 2;
	quad(-half, -0.56, half, 0.56, -0.03, 4, letter);
	quad(-0.5, seam, 0.5, 0.5, 0, 0, letter);
	quad(-0.5, -0.5, 0.5, -seam, 0, 1, letter);
	quad(-0.5, seam, 0.5, 0.5, FLAP_Z, 2, letter);
	quad(-0.5, seam, 0.5, 0.5, FLAP_Z, 3, (x, y) => [x + 0.5, 0.5 - y], true);   // turned over, it shows a bottom half
	const geometry = new THREE.BufferGeometry();
	geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
	geometry.setAttribute("uv", new THREE.Float32BufferAttribute(uvs, 2));
	geometry.setAttribute("part", new THREE.Float32BufferAttribute(parts, 1));
	geometry.setIndex(index);
	return geometry;
}

// The flaps' shader: per flap (instance) the four letters (top, bottom, front, back), the falling flap's angle and the
// colours of its face and letter. Lit by a light from the top left front; a flap falling shades the half below it.
function flapShader(THREE, atlas) {
	const columns = LETTER_TILE.columns, rows = Math.ceil(FLAPS.letters.length / columns);
	return new THREE.ShaderMaterial({
		uniforms: {
			atlas: { value: atlas },
			grid: { value: new THREE.Vector2(columns, rows) },
			aspect: { value: FLAPS.aspect },
		},
		vertexShader: `
			attribute float part;
			attribute vec4 aChars;
			attribute float aAngle;
			attribute vec3 aFace;
			attribute vec3 aInk;
			uniform vec2 grid;
			varying vec2 vUv;
			varying vec2 vTile;
			varying vec3 vFace;
			varying vec3 vInk;
			varying float vShade;
			varying float vPart;
			void main() {
				vec3 p = position;
				vec3 n = vec3(0.0, 0.0, part > 2.5 && part < 3.5 ? -1.0 : 1.0);
				if (part > 1.5 && part < 3.5) {   // the falling flap: around the middle, towards us and down
					float s = sin(aAngle), c = cos(aAngle);
					float z = p.z - ${FLAP_Z.toFixed(3)};
					p.yz = vec2(p.y * c - z * s, p.y * s + z * c + ${FLAP_Z.toFixed(3)});
					n.yz = vec2(n.y * c - n.z * s, n.y * s + n.z * c);
				}
				float letter = part < 0.5 ? aChars.x : part < 1.5 ? aChars.y : part < 2.5 ? aChars.z : aChars.w;
				vTile = vec2(mod(letter, grid.x), floor((letter + 0.5) / grid.x));
				vUv = uv;
				vFace = aFace;
				vInk = aInk;
				vPart = part;
				vec4 world = modelMatrix * instanceMatrix * vec4(p, 1.0);
				gl_Position = projectionMatrix * viewMatrix * world;
				vec3 normal = normalize(mat3(modelMatrix) * mat3(instanceMatrix) * n);
				vec3 light = normalize(vec3(-0.35, 0.55, 1.0));
				float shade = 0.42 + 0.62 * max(dot(normal, light), 0.0);
				shade *= 0.86 + 0.28 * abs(uv.y - 0.5);   // a little darker towards the split
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
			void main() {
				if (vPart > 3.5) { gl_FragColor = vec4(0.02, 0.02, 0.025, 1.0); return; }   // the black window
				vec2 size = vec2(aspect, 1.0);   // rounded corners
				vec2 q = abs(vUv - 0.5) * size - (size * 0.5 - 0.07);
				if (length(max(q, 0.0)) > 0.07) discard;
				vec2 at = vec2((vTile.x + vUv.x) / grid.x, 1.0 - (vTile.y + 1.0 - vUv.y) / grid.y);
				float ink = texture2D(atlas, at).r;
				gl_FragColor = vec4(mix(vFace, vInk, ink) * vShade, 1.0);
			}
		`,
	});
}
