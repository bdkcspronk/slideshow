// The vrijmibo takeover (templates/slides/vrijmibo.html, providers/vrijmibo.py): a neon maze seen from straight above,
// in 3D (Three.js, static/vendor/three). A chomper comes in through the left tunnel and eats its way along a fixed
// route through the maze, a beer every few cells, while four ghosts roam it as in the arcade game (below). With the
// last beer eaten it stops in the middle, turns its mouth to the top of the screen, grows, hiccups, and barfs out
// "Vrijmibo?" (the HTML letters of the slide, flying out of its mouth) in a spray of beer and foam. 15 seconds.
//
// Everything on screen is a function of the time alone (draw(t)): the ghosts' walks are worked out once at the start,
// from fixed rules, so every showing is the same. The time runs at the slide's rate (slideRate(), the menu's Speed).
//
// Kept within what the TV PC can do (docs/07-3d-limits.md): the maze's glow is painted once on the floor (one
// texture), the tubes are two InstancedMeshes, the beers five; some 40 draw calls and a few thousand triangles in all,
// no shadows, no full-screen effects (the soft glows are small quads, added on). Everything moves, so it draws every
// frame; like the books it drops to 75% resolution if its first frames come slowly. Without WebGL the slide shows
// "Vrijmibo?" as text.
//
// One unit in the 3D world is one maze cell. Column c, row r of the map sits at x = c - 10, z = r - 5 (row 0 at the
// top of the screen); the camera looks straight down.

const VM = {
	duration: 15,
	maze: [
		"#####################",
		"#.........#.........#",
		"#.###.###.#.###.###.#",
		"#...................#",
		"#.###.#.#####.#.###.#",
		"......#...#...#......",
		"#.###.###.#.###.###.#",
		"#...................#",
		"#.###.#.#####.#.###.#",
		"#.....#.......#.....#",
		"#####################",
	],
	// The chomper's route: corners as [column, row], straight lines between them. It starts outside, in the tunnel.
	route: [[-1, 5], [5, 5], [5, 3], [1, 3], [1, 1], [9, 1], [9, 3], [11, 3], [11, 1], [19, 1], [19, 3], [19, 5],
		[15, 5], [15, 7], [13, 7], [13, 9], [7, 9], [7, 7], [10, 7]],
	beerEvery: 3,   // a beer every so many cells along the route (and one at the very end)
	neonOn: 0.6,   // seconds the neon takes to flicker on
	chomp: { from: 0.6, to: 10.6, rate: 4.5, open: 0.6 },   // when it runs the route; chomps a second; mouth radians
	// The ghosts move as in the arcade game: on entering a cell each picks, of the ways on (never straight back), the
	// one whose next cell is nearest (in a straight line) to its target cell; ties go up, left, down, right. In
	// scatter its target is its own corner (just outside the maze), in chase it depends on the ghost (`aim`):
	//   chase:  the chomper's cell
	//   ambush: 4 cells ahead of the chomper
	//   flank:  the cell ahead of the chomper by 2, doubled away from the chaser (so the two pinch it)
	//   shy:    the chomper's cell, but its corner when within `shy` cells of it
	// The modes switch at the times in `modes` (scatter first); at every switch all ghosts turn round.
	// One rule the arcade hasn't: the chomper's route is fixed, so a ghost never catches it. A way that would bring it
	// within `keepAway` cells of the chomper in the next two cells is skipped for the next best (near misses).
	ghosts: [
		{ start: [10, 3], dir: [1, 0], colour: 0xe03a50, aim: "chase", corner: [21, -1] },   // Francken red
		{ start: [9, 7], dir: [-1, 0], colour: 0xb65cff, aim: "ambush", corner: [-1, -1] },   // violet
		{ start: [19, 9], dir: [0, -1], colour: 0x35e0b0, aim: "flank", corner: [21, 11] },   // mint
		{ start: [1, 9], dir: [0, -1], colour: 0xff7b3a, aim: "shy", corner: [-1, 11] },   // coral
	],
	ghostsFrom: 0.3,   // seconds in when they set off
	modes: [2.5, 7, 8.5],   // scatter until 2.5 s, chase until 7, scatter until 8.5, chase to the end
	shy: 5,
	ghostSpeed: 4.6,   // cells a second (the chomper does about 6)
	keepAway: 1.5,
	// The finale: the turn, hiccups, the barf (letters `stagger` apart, each `flight` seconds in the air).
	finale: { turn: 10.6, turnTime: 0.6, hiccups: [11.25, 11.6], barf: 11.9, stagger: 0.07, flight: 0.55, grow: 2.3 },
	colours: {
		floor: "#04050d",
		grid: "rgba(60, 90, 200, 0.10)",
		neon: "#2f6bff",   // the maze's glow
		neonCore: 0xc8dcff,   // the tubes themselves: almost white, as a neon tube's core
		chomper: 0xffd23a,
		mouth: 0x3a0b12,
		beer: 0xffa514,
		foam: 0xfff3da,
		eyes: 0xffffff,
		pupils: 0x1b2a8a,
	},
};

function setupVrijmibo3d(canvas) {
	const slide = canvas.closest(".vrijmibo-slide");
	slide.classList.add("vrijmibo-live");   // the letters wait for their cue instead of standing there
	loadThree().then((THREE) => {
		if (document.contains(canvas)) return playVrijmibo3d(THREE, canvas, slide);
	}).catch((error) => {
		console.warn("Vrijmibo in 3D:", error);
		slide.classList.remove("vrijmibo-live");   // the text instead
	});
}

async function playVrijmibo3d(THREE, canvas, slide) {
	let renderer;
	try {
		renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: "high-performance" });
	} catch (error) {
		throw new Error(`no WebGL: ${error}`);
	}
	await document.fonts.load('900 100px "Londrina Solid"').catch(() => {});
	if (!document.contains(canvas)) return renderer.dispose();

	const scene = vrijmiboScene(THREE, renderer, canvas, slide.querySelector(".vrijmibo-text"));
	let quality = 1;
	const resize = () => {
		renderer.setPixelRatio(devicePixelRatio * quality);
		renderer.setSize(canvas.clientWidth, canvas.clientHeight, false);
		scene.resize();
	};
	resize();
	scene.draw(0);

	// Every frame while the slide is on the page; freed when it's gone (the browser has only a few WebGL contexts).
	let t = 0, last = null, measured = false;
	const gaps = [];
	const frame = (now) => {
		if (!document.contains(canvas)) {
			scene.dispose();
			renderer.dispose();
			renderer.forceContextLoss();
			return;
		}
		requestAnimationFrame(frame);
		if (last !== null) {
			gaps.push(now - last);
			t += (now - last) / 1000 * slideRate(canvas);   // faster or slower with the slide (the menu's Speed)
		}
		last = now;
		scene.draw(t);
		// Too slow for this PC? Over the first 30 frames, drop to 75% resolution once if they come slower than 50 a second.
		if (!measured && gaps.length >= 30) {
			measured = true;
			gaps.sort((p, q) => p - q);
			if (gaps[Math.floor(gaps.length / 2)] > 20) {
				quality = 0.75;
				resize();
				console.info("Vrijmibo in 3D: slow frames, drawing at 75% resolution");
			}
		}
	};
	requestAnimationFrame(frame);
}

// The scene: returns draw(t) (t in seconds, 0 to VM.duration), resize() (after the canvas changed size) and dispose().
// `textLayer` holds the letters as spans; they fly out of the chomper's mouth.
function vrijmiboScene(THREE, renderer, canvas, textLayer) {
	const C = VM.colours;
	const rnd = (i) => { const x = Math.sin(i * 12.9898 + 78.233) * 43758.5453; return x - Math.floor(x); };
	const clamp01 = (x) => Math.min(1, Math.max(0, x));
	const easeOut = (x) => 1 - Math.pow(1 - clamp01(x), 3);
	const easeInOut = (x) => { x = clamp01(x); return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; };
	const easeBack = (x, s = 1.7) => { x = clamp01(x) - 1; return 1 + x * x * ((s + 1) * x + s); };
	const lerp = (a, b, f) => a + (b - a) * f;
	const lerpAngle = (a, b, f) => { let d = b - a; while (d > Math.PI) d -= 2 * Math.PI; while (d < -Math.PI) d += 2 * Math.PI; return a + d * f; };
	const X = (c) => c - 10, Z = (r) => r - 5;
	const wall = (c, r) => VM.maze[r]?.[c] === "#";

	renderer.setClearColor(C.floor);
	const scene = new THREE.Scene();
	const camera = new THREE.PerspectiveCamera(32, 16 / 9, 0.5, 100);
	camera.up.set(0, 0, -1);   // straight down, with row 0 at the top of the screen
	scene.add(new THREE.HemisphereLight(0xc6d6ff, 0x141428, 1.2));
	const sun = new THREE.DirectionalLight(0xffffff, 2.2);
	sun.position.set(-4, 10, 7);
	scene.add(sun);

	// --- The route --------------------------------------------------------------------------------------------
	const segs = [];
	let routeLength = 0;
	for (let i = 1; i < VM.route.length; i++) {
		const [c0, r0] = VM.route[i - 1], [c1, r1] = VM.route[i];
		const len = Math.abs(c1 - c0) + Math.abs(r1 - r0);
		const dx = Math.sign(c1 - c0), dz = Math.sign(r1 - r0);
		for (let k = 1; k <= len; k++) if (wall(c0 + dx * k, r0 + dz * k)) console.warn("Vrijmibo: the route runs through a wall at", c0 + dx * k, r0 + dz * k);
		segs.push({ x: X(c0), z: Z(r0), dx, dz, len, s: routeLength, yaw: Math.atan2(-dz, dx) });
		routeLength += len;
	}
	function at(s) {   // the point `s` cells along the route, and which way it faces there (turning round corners)
		s = Math.min(routeLength, Math.max(0, s));
		let i = segs.findIndex((g) => s <= g.s + g.len);
		if (i < 0) i = segs.length - 1;
		const g = segs[i], d = s - g.s;
		let yaw = g.yaw;
		const turn = 0.3;
		if (g.len - d < turn && segs[i + 1]) yaw = lerpAngle(g.yaw, segs[i + 1].yaw, (turn - (g.len - d)) / (2 * turn));
		else if (d < turn && segs[i - 1]) yaw = lerpAngle(segs[i - 1].yaw, g.yaw, 0.5 + d / (2 * turn));
		return { x: g.x + g.dx * d, z: g.z + g.dz * d, yaw };
	}
	const ch = VM.chomp;
	const sAt = (t) => routeLength * clamp01((t - ch.from) / (ch.to - ch.from));
	const tAt = (s) => ch.from + (s / routeLength) * (ch.to - ch.from);

	// --- The ghosts' walks, worked out once (all four together: the flanker needs the chaser): the cell each is in
	// every 1/speed seconds -----------------------------------------------------------------------------------------
	const gv = VM.ghostSpeed;
	const open = (c, r) => r >= 0 && r < VM.maze.length && c >= 0 && c < VM.maze[0].length && !wall(c, r);
	const DIRS = [[0, -1], [-1, 0], [0, 1], [1, 0]];   // up, left, down, right: the arcade's order for ties
	const modeAt = (t) => VM.modes.filter((m) => t >= m).length % 2 ? "chase" : "scatter";
	function chomperCell(t) {   // the chomper's cell and the way it faces, as the ghosts see it
		const p = at(sAt(t));
		return { c: Math.round(p.x + 10), r: Math.round(p.z + 5), dc: Math.round(Math.cos(p.yaw)), dr: Math.round(-Math.sin(p.yaw)) };
	}
	function walkAll() {
		const state = VM.ghosts.map((def) => ({ def, cur: def.start, dir: def.dir, cells: [def.start] }));
		for (let k = 0; k < Math.ceil((VM.duration + 1) * gv); k++) {
			const t = k / gv + VM.ghostsFrom;
			const turnRound = k > 0 && modeAt(t) !== modeAt(t - 1 / gv);
			const pac = chomperCell(t);
			for (const g of state) {
				const targetOf = () => {
					const { aim, corner } = g.def;
					if (modeAt(t) === "scatter") return corner;
					if (aim === "ambush") return [pac.c + 4 * pac.dc, pac.r + 4 * pac.dr];
					if (aim === "flank") {
						const chaser = state.find((s) => s.def.aim === "chase").cur, a = [pac.c + 2 * pac.dc, pac.r + 2 * pac.dr];
						return [2 * a[0] - chaser[0], 2 * a[1] - chaser[1]];
					}
					if (aim === "shy" && Math.hypot(g.cur[0] - pac.c, g.cur[1] - pac.r) < VM.shy) return corner;
					return [pac.c, pac.r];
				};
				if (turnRound) g.dir = [-g.dir[0], -g.dir[1]];
				g.dir = step(g.cur, g.dir, targetOf(), t, turnRound);
				g.cur = [g.cur[0] + g.dir[0], g.cur[1] + g.dir[1]];
				g.cells.push(g.cur);
			}
		}
		return state.map((g) => g.cells);
	}
	function step(cur, dir, target, t, justTurned) {   // the way a ghost goes on from `cur`
		const danger = ([dc, dr]) => {   // how close it would come to the chomper, going this way two cells
			const n = [cur[0] + dc, cur[1] + dr];
			const n2 = open(n[0] + dc, n[1] + dr) ? [n[0] + dc, n[1] + dr] : n;
			let near = Infinity;
			for (let tau = 0; tau <= 2 / gv; tau += 0.04) {
				const f = tau * gv, [a, b] = f < 1 ? [cur, n] : [n, n2], ff = f < 1 ? f : f - 1;
				const p = at(sAt(t + tau));
				near = Math.min(near, Math.hypot(X(lerp(a[0], b[0], ff)) - p.x, Z(lerp(a[1], b[1], ff)) - p.z));
			}
			return near;
		};
		const ways = DIRS.filter(([dc, dr]) => open(cur[0] + dc, cur[1] + dr));
		const back = (d) => d[0] === -dir[0] && d[1] === -dir[1];
		// Just turned round (a mode switch): carry on the new way if it can.
		if (justTurned && open(cur[0] + dir[0], cur[1] + dir[1]) && danger(dir) >= VM.keepAway) return dir;
		// The ways on, nearest to the target first (a stable sort: ties stay up, left, down, right).
		const ranked = ways.filter((d) => !back(d))
			.map((d) => [d, Math.hypot(cur[0] + d[0] - target[0], cur[1] + d[1] - target[1])])
			.sort((a, b) => a[1] - b[1]);
		for (const [d] of ranked) if (danger(d) >= VM.keepAway) return d;
		// Every way on runs into the chomper (or it is a dead end): the one that keeps furthest from it, back too.
		return ways.map((d) => [d, danger(d) - (back(d) ? 0.01 : 0)]).sort((a, b) => b[1] - a[1])[0][0];
	}
	function ghostAt(cells, t) {   // where a ghost is at time t, and which way it goes (on the screen: x right, y up)
		const k = Math.min(cells.length - 2, Math.floor(t * gv)), f = t * gv - k;
		const [a, b] = [cells[k], cells[k + 1]];
		return { x: X(lerp(a[0], b[0], f)), z: Z(lerp(a[1], b[1], f)), look: [b[0] - a[0], a[1] - b[1]] };
	}

	// --- The floor: the maze's glow and a faint grid, painted once on a canvas ----------------------------------
	const floorW = 25, floorD = 14, ppu = 80;   // 2000 x 1120: under the 2048 the TV PC takes in its stride
	const paint = document.createElement("canvas");
	paint.width = floorW * ppu; paint.height = floorD * ppu;
	const g2 = paint.getContext("2d");
	const px = (x) => (x + floorW / 2) * ppu, pz = (z) => (z + floorD / 2) * ppu;
	g2.fillStyle = C.floor; g2.fillRect(0, 0, paint.width, paint.height);
	g2.fillStyle = C.grid;
	for (let r = 0; r < VM.maze.length; r++) for (let c = 0; c < VM.maze[0].length; c++) {
		if (!wall(c, r)) { g2.beginPath(); g2.arc(px(X(c)), pz(Z(r)), 0.05 * ppu, 0, 7); g2.fill(); }
	}
	// The wall lines: runs of wall cells, across and down, and wall cells on their own.
	const runs = [], joints = new Set();
	const rows = VM.maze.length, cols = VM.maze[0].length;
	for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
		if (wall(c, r) && !wall(c - 1, r) && wall(c + 1, r)) { let e = c; while (wall(e + 1, r)) e++; runs.push([c, r, e, r]); joints.add(c + "," + r).add(e + "," + r); }
		if (wall(c, r) && !wall(c, r - 1) && wall(c, r + 1)) { let e = r; while (wall(c, e + 1)) e++; runs.push([c, r, c, e]); joints.add(c + "," + r).add(c + "," + e); }
		if (wall(c, r) && !wall(c - 1, r) && !wall(c + 1, r) && !wall(c, r - 1) && !wall(c, r + 1)) joints.add(c + "," + r);
	}
	const strokeWalls = (width, colour, blur, alpha) => {
		g2.save();
		g2.globalAlpha = alpha; g2.strokeStyle = colour; g2.fillStyle = colour; g2.lineWidth = width * ppu; g2.lineCap = "round";
		g2.shadowColor = colour; g2.shadowBlur = blur * ppu;
		g2.beginPath();
		for (const [c0, r0, c1, r1] of runs) { g2.moveTo(px(X(c0)), pz(Z(r0))); g2.lineTo(px(X(c1)), pz(Z(r1))); }
		g2.stroke();
		for (const j of joints) { const [c, r] = j.split(",").map(Number); g2.beginPath(); g2.arc(px(X(c)), pz(Z(r)), width * ppu / 2, 0, 7); g2.fill(); }
		g2.restore();
	};
	g2.globalCompositeOperation = "lighter";
	strokeWalls(0.9, C.neon, 0.9, 0.10);   // the wide haze
	strokeWalls(0.28, C.neon, 0.5, 0.55);   // the glow
	strokeWalls(0.12, C.neon, 0.25, 0.9);   // where the tube's light hits the floor
	const floorTex = new THREE.CanvasTexture(paint);
	floorTex.colorSpace = THREE.SRGBColorSpace;
	floorTex.anisotropy = 4;
	const floorMat = new THREE.MeshBasicMaterial({ map: floorTex });
	const floor = new THREE.Mesh(new THREE.PlaneGeometry(floorW, floorD), floorMat);
	floor.rotation.x = -Math.PI / 2;
	scene.add(floor);

	// --- The neon tubes, just above the floor: one InstancedMesh of cylinders, one of balls for the joints -------
	const tubeR = 0.065, tubeY = 0.22;
	const tubeMat = new THREE.MeshBasicMaterial({ color: C.neonCore });
	const tubes = new THREE.InstancedMesh(new THREE.CylinderGeometry(tubeR, tubeR, 1, 10, 1, true), tubeMat, runs.length);
	const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), v3 = new THREE.Vector3(), sc = new THREE.Vector3();
	const up = new THREE.Vector3(0, 1, 0);
	runs.forEach(([c0, r0, c1, r1], i) => {
		const a = new THREE.Vector3(X(c0), tubeY, Z(r0)), b = new THREE.Vector3(X(c1), tubeY, Z(r1));
		const dir = b.clone().sub(a);
		q.setFromUnitVectors(up, dir.clone().normalize());
		m4.compose(a.clone().add(b).multiplyScalar(0.5), q, sc.set(1, dir.length(), 1));
		tubes.setMatrixAt(i, m4);
	});
	scene.add(tubes);
	const jointList = [...joints].map((j) => j.split(",").map(Number));
	const balls = new THREE.InstancedMesh(new THREE.SphereGeometry(tubeR, 10, 6), tubeMat, jointList.length);
	jointList.forEach(([c, r], i) => balls.setMatrixAt(i, m4.makeTranslation(X(c), tubeY, Z(r))));
	scene.add(balls);

	// --- Soft glows on the floor under what moves (one radial texture, added on) ---------------------------------
	const glowCanvas = document.createElement("canvas");
	glowCanvas.width = glowCanvas.height = 128;
	const gg = glowCanvas.getContext("2d"), grad = gg.createRadialGradient(64, 64, 0, 64, 64, 64);
	grad.addColorStop(0, "rgba(255,255,255,1)"); grad.addColorStop(0.35, "rgba(255,255,255,0.35)"); grad.addColorStop(1, "rgba(255,255,255,0)");
	gg.fillStyle = grad; gg.fillRect(0, 0, 128, 128);
	const glowTex = new THREE.CanvasTexture(glowCanvas);
	const glowGeo = new THREE.PlaneGeometry(1, 1).rotateX(-Math.PI / 2);
	const glowMat = (colour, opacity) => new THREE.MeshBasicMaterial({ map: glowTex, color: colour, transparent: true, opacity, blending: THREE.AdditiveBlending, depthWrite: false });

	// --- The beers ------------------------------------------------------------------------------------------------
	const beers = [];
	const seen = new Set();
	const addBeer = (s) => {
		const p = at(s), key = Math.round(p.x) + "," + Math.round(p.z);
		if (seen.has(key) || p.x < -10) return;
		seen.add(key);
		beers.push({ x: p.x, z: p.z, s, eat: tAt(s - 0.35), spin: rnd(beers.length) * 6.28 });
	};
	for (let s = VM.beerEvery; s < routeLength - 1; s += VM.beerEvery) addBeer(s);
	addBeer(routeLength);
	const beerParts = [
		{ geo: new THREE.CylinderGeometry(0.15, 0.12, 0.36, 16).translate(0, 0.2, 0), mat: new THREE.MeshStandardMaterial({ color: C.beer, emissive: C.beer, emissiveIntensity: 0.45, roughness: 0.25 }) },
		{ geo: new THREE.TorusGeometry(0.09, 0.028, 8, 14, Math.PI).rotateZ(-Math.PI / 2).translate(0.15, 0.21, 0), mat: null },
		{ geo: new THREE.CylinderGeometry(0.165, 0.155, 0.08, 16).translate(0, 0.41, 0), mat: new THREE.MeshStandardMaterial({ color: C.foam, emissive: C.foam, emissiveIntensity: 0.3, roughness: 0.9 }) },
		{ geo: new THREE.SphereGeometry(0.165, 16, 6, 0, Math.PI * 2, 0, Math.PI / 2).scale(1, 0.45, 1).translate(0, 0.45, 0), mat: null },
	];
	beerParts[1].mat = beerParts[0].mat; beerParts[3].mat = beerParts[2].mat;
	// Centred on the middle of the mug (it sways and pops round that), laid flat facing the camera as the ghosts: the
	// foam to the top of the screen, the handle to the right.
	const beerMeshes = beerParts.map((p) => { const m = new THREE.InstancedMesh(p.geo.translate(0, -0.26, 0), p.mat, beers.length); scene.add(m); return m; });
	const flat = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), -Math.PI / 2);
	const beerGlows = new THREE.InstancedMesh(glowGeo, glowMat(C.beer, 0.55), beers.length);
	scene.add(beerGlows);

	// --- The chomper: two half balls hinged at the middle, each with a dark lid over its cut. The halves are rolled
	// onto their side (roll), so the jaw hinges round an upright axis and the mouth opens as a wedge seen from above,
	// as in the 2D game ------------------------------------------------------------------------------------------
	const chR = 0.4;
	const chMat = new THREE.MeshStandardMaterial({ color: C.chomper, emissive: C.chomper, emissiveIntensity: 0.35, roughness: 0.35 });
	const mouthMat = new THREE.MeshStandardMaterial({ color: C.mouth, emissive: C.mouth, emissiveIntensity: 0.6, roughness: 0.8, side: THREE.DoubleSide });
	const chomper = new THREE.Group(), roll = new THREE.Group();
	roll.rotation.x = Math.PI / 2;
	const half = (top) => {
		const g = new THREE.Group();
		g.add(new THREE.Mesh(new THREE.SphereGeometry(chR, 32, 12, 0, Math.PI * 2, top ? 0 : Math.PI / 2, Math.PI / 2), chMat));
		g.add(new THREE.Mesh(new THREE.CircleGeometry(chR * 0.999, 32).rotateX(Math.PI / 2), mouthMat));
		roll.add(g);
		return g;
	};
	const upper = half(true), lower = half(false);
	chomper.add(roll);
	scene.add(chomper);
	const chGlow = new THREE.Mesh(glowGeo, glowMat(C.chomper, 0.5));
	scene.add(chGlow);

	// --- The ghosts: a lathed dome with a wavy hem (one geometry for all), laid flat facing the camera as the 2D
	// sprites: the dome to the top of the screen, the skirt to the bottom. They never turn; only the pupils look the
	// way they go. Centred on the middle of the body (the geometry shifted down) ----------------------------------
	const profile = [new THREE.Vector2(0.4, 0), new THREE.Vector2(0.4, 0.42)];
	for (let i = 1; i <= 10; i++) { const a = (i / 10) * Math.PI / 2; profile.push(new THREE.Vector2(0.4 * Math.cos(a), 0.42 + 0.4 * Math.sin(a))); }
	const ghostGeo = new THREE.LatheGeometry(profile, 32);
	const hem = [];
	const gp = ghostGeo.attributes.position;
	for (let i = 0; i < gp.count; i++) if (gp.getY(i) < 0.01) hem.push([i, Math.atan2(gp.getZ(i), gp.getX(i))]);
	const ghostMid = 0.41;
	ghostGeo.translate(0, -ghostMid, 0);
	const eyeMat = new THREE.MeshStandardMaterial({ color: C.eyes, emissive: C.eyes, emissiveIntensity: 0.6 });
	const pupilMat = new THREE.MeshStandardMaterial({ color: C.pupils, emissive: C.pupils, emissiveIntensity: 0.4 });
	const eyeGeo = new THREE.SphereGeometry(0.11, 14, 10).scale(0.85, 1.15, 0.5), pupilGeo = new THREE.SphereGeometry(0.06, 10, 8).scale(1, 1, 0.5);
	const walks = walkAll();
	const ghosts = VM.ghosts.map((def, gi) => {
		const group = new THREE.Group();
		group.rotation.x = -Math.PI / 2;   // its up to the top of the screen, its front (+z) to the camera
		group.add(new THREE.Mesh(ghostGeo, new THREE.MeshStandardMaterial({ color: def.colour, emissive: def.colour, emissiveIntensity: 0.55, roughness: 0.4, side: THREE.DoubleSide })));
		const pupils = [];
		for (const side of [-1, 1]) {
			const eye = new THREE.Mesh(eyeGeo, eyeMat);
			eye.position.set(side * 0.15, 0.12, 0.36);
			const pupil = new THREE.Mesh(pupilGeo, pupilMat);
			pupil.position.set(side * 0.15, 0.12, 0.41);
			group.add(eye, pupil); pupils.push(pupil);
		}
		scene.add(group);
		const glow = new THREE.Mesh(glowGeo, glowMat(def.colour, 0.6));
		scene.add(glow);
		return { group, glow, pupils, cells: walks[gi] };
	});

	// --- Particles: sparks when a beer is eaten, the spray of the barf -------------------------------------------
	const maxParts = 300;
	const parts = new THREE.InstancedMesh(new THREE.IcosahedronGeometry(0.045), new THREE.MeshBasicMaterial({ transparent: true, blending: THREE.AdditiveBlending, depthWrite: false }), maxParts);
	parts.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(maxParts * 3), 3);
	scene.add(parts);
	const cBeer = new THREE.Color(C.beer), cFoam = new THREE.Color(C.foam), cTmp = new THREE.Color();

	// --- The letters: the slide's spans, flying out of the mouth ----------------------------------------------------
	const letters = [...textLayer.querySelectorAll("span")].map((span, i) => ({ span, i, home: { x: 0, y: 0 }, tilt: (rnd(i + 40) - 0.5) * 0.18 }));
	let width = 1, height = 1;
	function resize() {
		width = Math.max(1, canvas.clientWidth); height = Math.max(1, canvas.clientHeight);
		camera.aspect = width / height;
		camera.updateProjectionMatrix();
		const base = canvas.getBoundingClientRect();
		for (const l of letters) {   // where each letter rests (measured without its transform)
			l.span.style.transform = "none";
			const r = l.span.getBoundingClientRect();
			l.home = { x: r.left + r.width / 2 - base.left, y: r.top + r.height / 2 - base.top };
		}
	}

	// --- One frame ------------------------------------------------------------------------------------------------
	const fin = VM.finale;
	const endPoint = at(routeLength);
	const mouthWorld = new THREE.Vector3(), fwd = new THREE.Vector3();

	function draw(t) {
		t = Math.min(VM.duration, Math.max(0, t));

		// The neon flickers on, and dims for the finale.
		const flicker = [0, 0.85, 0.1, 0.95, 0.35, 1];
		let neon = t < VM.neonOn ? flicker[Math.floor((t / VM.neonOn) * flicker.length)] : 1;
		neon *= lerp(1, 0.5, easeInOut((t - fin.hiccups[0] + 0.3) / 0.7));
		floorMat.color.setScalar(lerp(0.06, 1, neon));
		tubeMat.color.set(C.neonCore).multiplyScalar(lerp(0.08, 1, neon));

		// The camera, straight down: a slow push in for the finale.
		camera.position.set(0, lerp(23, 20.5, easeInOut((t - fin.turn) / 1.4)), 0);
		camera.lookAt(0, 0, 0);

		// The beers: pop in along the route at the start, pop when eaten.
		let n = 0;
		beers.forEach((b, i) => {
			const appear = easeBack((t - 0.2 - (b.s / routeLength) * 0.6) / 0.35);
			const age = t - b.eat;
			let s = appear;
			if (age >= 0) s = age < 0.12 ? (1 + 0.5 * age / 0.12) * (1 - age / 0.12) : 0;
			q.setFromAxisAngle(up, 0.18 * Math.sin(t * 2.4 + b.spin)).multiply(flat);   // a gentle sway
			m4.compose(v3.set(b.x, 0.2, b.z), q, sc.setScalar(Math.max(s, 1e-4)));
			for (const m of beerMeshes) m.setMatrixAt(i, m4);
			m4.compose(v3.set(b.x, 0.012, b.z), q.identity(), sc.setScalar(Math.max(s, 1e-4) * 1.1));
			beerGlows.setMatrixAt(i, m4);
			// Sparks for 0.6 s after it is eaten.
			if (age >= 0 && age < 0.6) for (let j = 0; j < 10 && n < maxParts; j++, n++) {
				const a = rnd(i * 17 + j) * 6.28, sp = 1.2 + rnd(i * 31 + j) * 1.6, upv = 1.5 + rnd(i * 7 + j) * 1.5;
				const k = 1 - age / 0.6;
				m4.compose(v3.set(b.x + Math.cos(a) * sp * age, 0.3 + upv * age - 4 * age * age, b.z + Math.sin(a) * sp * age), q.identity(), sc.setScalar(k));
				parts.setMatrixAt(n, m4);
				parts.setColorAt(n, cTmp.copy(j % 3 ? cBeer : cFoam).multiplyScalar(k));
			}
		});
		for (const m of beerMeshes) m.instanceMatrix.needsUpdate = true;
		beerGlows.instanceMatrix.needsUpdate = true;

		// The chomper: along the route, then the finale.
		const p = at(sAt(t));
		let mouth = ch.open * 0.5 * (1 - Math.cos(2 * Math.PI * ch.rate * Math.max(0, t - ch.from)));
		let yaw = p.yaw, grow = 1, lift = chR, squash = 1;
		chomper.visible = t >= ch.from - 0.05;
		if (t >= fin.turn) {
			const k = easeBack((t - fin.turn) / fin.turnTime, 1.2);
			mouth = lerp(mouth, 0, clamp01((t - fin.turn) / 0.15));
			yaw = lerpAngle(endPoint.yaw, Math.PI / 2, k);   // mouth to the top of the screen, where the letters land
			grow = lerp(1, fin.grow, k);
			lift = lerp(chR, chR * fin.grow + 0.5, k);
			for (const h of fin.hiccups) { const a = (t - h) / 0.28; if (a > 0 && a < 1) squash += 0.16 * Math.sin(a * Math.PI) * (1 - a * 0.3); }
			const b = t - fin.barf;
			if (b > 0) mouth = b < 0.12 ? lerp(0, 1.0, b / 0.12) : b < 1.4 ? 1.0 + 0.06 * Math.sin(b * 30) * (1 - b / 1.4) : lerp(1.0, 0.3, easeInOut((b - 1.4) / 0.6));
		}
		chomper.position.set(p.x, lift, p.z);
		chomper.rotation.y = yaw;
		chomper.scale.set(grow * squash, grow * (2 - squash), grow * squash);
		upper.rotation.z = mouth / 2; lower.rotation.z = -mouth / 2;
		chGlow.position.set(p.x, 0.014, p.z);
		chGlow.scale.setScalar(2.2 * grow);

		// The ghosts: pop up with the neon, then roam.
		for (const [i, a] of hem) gp.setY(i, -ghostMid + 0.055 * Math.sin(a * 7 + t * 14));
		gp.needsUpdate = true;
		ghosts.forEach((g, i) => {
			const show = easeBack((t - VM.ghostsFrom - i * 0.12) / 0.4);
			const gpos = ghostAt(g.cells, Math.max(0, t - VM.ghostsFrom));
			g.group.position.set(gpos.x, 0.45, gpos.z);
			for (const [j, pu] of g.pupils.entries()) pu.position.set((j ? 1 : -1) * 0.15 + gpos.look[0] * 0.05, 0.12 + gpos.look[1] * 0.06, 0.41);
			g.group.scale.setScalar(Math.max(show, 1e-4));
			g.glow.position.set(gpos.x, 0.016 + i * 0.001, gpos.z);
			g.glow.scale.setScalar(2.4 * show);
		});

		// The barf: beer and foam spraying out of the mouth, the way it faces, fanned out either side.
		fwd.set(Math.cos(yaw), 0, -Math.sin(yaw));
		mouthWorld.set(p.x, lift, p.z).addScaledVector(fwd, chR * grow * 0.8);
		mouthWorld.y += chR * grow * 0.15;
		const b = t - fin.barf;
		if (b > 0) for (let j = 0; j < 90 && n < maxParts; j++) {
			const age = b - j * 0.012;
			if (age < 0 || age > 1.3) continue;
			const a = (rnd(j + 500) - 0.5) * 1.6, upv = 2 + rnd(j + 600) * 4, sp = 3 + rnd(j + 700) * 4;
			const k = 1 - age / 1.3;
			const dx = fwd.x * Math.cos(a) - fwd.z * Math.sin(a), dz = fwd.x * Math.sin(a) + fwd.z * Math.cos(a);
			v3.set(mouthWorld.x + dx * sp * age, mouthWorld.y + upv * age - 6 * age * age, mouthWorld.z + dz * sp * age);
			if (v3.y < 0.05) continue;
			m4.compose(v3, q.identity(), sc.setScalar((1 + rnd(j + 800) * 1.2) * Math.min(1, k * 2)));
			parts.setMatrixAt(n, m4);
			parts.setColorAt(n, cTmp.copy(rnd(j + 900) < 0.35 ? cFoam : cBeer).multiplyScalar(Math.min(1, k * 1.5)));
			n++;
		}
		parts.count = n;
		parts.instanceMatrix.needsUpdate = true;
		parts.instanceColor.needsUpdate = true;

		renderer.render(scene, camera);

		// The letters: from the mouth (on the screen) to their place, in an arc, landing with an overshoot, then
		// bobbing a little. Transform and opacity only.
		const m = mouthWorld.clone().project(camera);
		const mx = (m.x + 1) / 2 * width, my = (1 - m.y) / 2 * height;
		for (const l of letters) {
			const launch = fin.barf + 0.05 + l.i * fin.stagger;
			const f = (t - launch) / fin.flight;
			if (f <= 0) { l.span.style.opacity = "0"; continue; }
			const e = easeOut(f), sBack = easeBack(f, 2.2);
			const x = lerp(mx - l.home.x, 0, e);
			const y = lerp(my - l.home.y, 0, e) - Math.sin(Math.PI * clamp01(f)) * height * 0.12 + (f > 1 ? Math.sin((t - launch) * 2.2 + l.i * 0.7) * height * 0.006 : 0);
			const rot = lerp((rnd(l.i + 70) - 0.5) * 2.4, l.tilt, e);
			l.span.style.opacity = String(clamp01(f * 5));
			l.span.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px) rotate(${rot.toFixed(3)}rad) scale(${lerp(0.15, 1, sBack).toFixed(3)})`;
		}
	}

	const dispose = () => {
		scene.traverse((o) => { o.geometry?.dispose(); [o.material].flat().forEach((mat) => { mat?.map?.dispose(); mat?.dispose(); }); });
	};
	return { draw, resize, dispose };
}
