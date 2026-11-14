// The books slide in real 3D (templates/slides/books.html, providers/books.py), drawn with Three.js (static/vendor/three).
//
// In the background stands a bookcase with all the books for sale (<canvas data-books-case>: each book's title, colour
// and shape, in order). The books of this slide are taken out of it: one just after the other, each slides out of its
// place on the shelf, flies to the front while it turns its cover to us, and hovers there with a slow bob and sway, above
// its title and price (HTML). Each is a hardcover: a front and back board, a rounded spine with the title on it, and a
// block of pages, lit by a white light from the front left and a crimson one from behind (the colour of its glow).
//
// Kept within what the TV PC can do (docs/07-3d-limits.md): the bookcase doesn't move, so it is drawn only once, onto
// .books-case (a plain picture from then on); its books are a single mesh with one texture holding every spine. Every
// frame draws only the books taken out: 3 books are 15 draw calls, a few thousand triangles (and one more for an invisible copy of the bookcase that hides them where they are behind it) and 7 textures, no shadows. Antialiasing is on (the
// turning edges would flicker without it). If it still draws slowly (frames over 20 ms in the first seconds) it drops
// to 75% resolution. Without WebGL the slide shows the covers flat and no bookcase (.books-flat, style.css).
//
// One unit in the 3D world is 1vh: the camera is DISTANCE in front of the screen, so at z = 0 the world is the size of
// the page. The page (HTML and CSS) is in charge of where the books land (each where its .book-flat is) and of their
// size (--w, --h and --d on .books-slide, times the book's size and thickness from providers/books.py).

const BOOKS_3D = {
	distance: 140,   // the camera, in front of the screen
	shelves: 3,   // the bookcase: CASE_SIZE books (providers/books.py) on this many shelves
	caseTop: 17,   // where the bookcase is on the screen: from under the title (so no book is taken out behind it) to the bottom
	caseBottom: 103,
	navy: 0x142c55,   // the poster behind it (style.css), which the bookcase fades into a little
};

function setupBooks3d(canvas) {
	const slide = canvas.closest(".books-slide");
	loadThree().then((THREE) => {
		if (document.contains(canvas)) drawBooks3d(THREE, canvas, slide);
	}).catch((error) => {
		console.warn("Books in 3D:", error);
		slide.classList.add("books-flat");
	});
}

async function drawBooks3d(THREE, canvas, slide) {
	let renderer;
	try {
		renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true, powerPreference: "high-performance" });
	} catch (error) {
		console.warn("Books in 3D: no WebGL", error);
		return slide.classList.add("books-flat");
	}
	await document.fonts.load('700 20px "Familjen Grotesk"').catch(() => {});   // for the drawn covers and the spines
	// The covers: this runs as soon as the slide is on the page, before player.js has waited for its pictures.
	await Promise.all([...slide.querySelectorAll(".book-flat img")].map((img) => img.decode().catch(() => {})));
	if (!document.contains(canvas)) return renderer.dispose();

	// Sizes in vh, from the CSS.
	const style = getComputedStyle(slide);
	const size = (name) => parseFloat(style.getPropertyValue(name));
	const W = size("--w"), H = size("--h"), D = size("--d");
	const vh = innerHeight / 100;
	const box = canvas.getBoundingClientRect();
	const width = box.width / vh, height = box.height / vh;
	const { distance } = BOOKS_3D;

	let quality = 1;
	const resize = () => {
		renderer.setPixelRatio(devicePixelRatio * quality);   // the screen's real pixels (display scaling gives a ratio above 1)
		renderer.setSize(canvas.clientWidth, canvas.clientHeight, false);
	};
	resize();

	const camera = new THREE.PerspectiveCamera(2 * Math.atan(height / 2 / distance) * 180 / Math.PI, width / height, 10, 1000);
	camera.position.set(0, 0, distance);
	// Where a point of the page is at z = 0.
	const onPage = (x, y) => ({ x: (x - box.left) / vh - width / 2, y: height / 2 - (y - box.top) / vh });

	const textures = [];
	const texture = (source, srgb = true) => {
		const t = new THREE.CanvasTexture(source);
		if (srgb) t.colorSpace = THREE.SRGBColorSpace;
		t.anisotropy = 4;
		textures.push(t);
		return t;
	};
	const dispose = (scene) => {
		scene.traverse((o) => { o.geometry?.dispose(); [o.material].flat().forEach((m) => m?.dispose()); });
	};

	// The bookcase, and where each place on its shelves is.
	const caseCanvas = slide.querySelector("canvas[data-books-case]");
	const shelved = JSON.parse(caseCanvas?.dataset.booksCase || "[]");
	const caseSize = Number(caseCanvas?.dataset.caseSize) || shelved.length;
	const bookcase = makeBookcase(THREE, { W, H, D, books: shelved, caseSize, distance, height, texture });
	const cards = [...slide.querySelectorAll(".book-card")];
	const taken = new Set(cards.map((card) => Number(card.dataset.slot)));

	// Drawn once: the bookcase without the books taken out, copied onto its own canvas, after which this canvas
	// only draws the books that move.
	let occluder = null;
	if (caseCanvas) {
		const caseScene = new THREE.Scene();
		caseScene.fog = new THREE.Fog(BOOKS_3D.navy, distance + 60, distance + 700);   // a little hazy: it is the background
		addLights(THREE, caseScene, 0.75);
		const shelfBooks = bookcase.shelfBooks(taken);
		caseScene.add(bookcase.wood, shelfBooks);
		// The same bookcase, invisible, in front of which the books that move are drawn: it only fills the depth buffer,
		// so the shelves, the books next to them and the sides hide them where they are behind those (the picture of
		// the bookcase can't). One draw call: every plank and book in one geometry, positions only.
		caseScene.updateMatrixWorld();
		const parts = [];
		caseScene.traverse((o) => {
			if (!o.isMesh) return;
			const g = new THREE.BufferGeometry();
			g.setAttribute("position", o.geometry.attributes.position.clone());
			if (o.geometry.index) g.setIndex(o.geometry.index.clone());
			parts.push(g.applyMatrix4(o.matrixWorld));
		});
		occluder = new THREE.Mesh(mergeGeometries(THREE, parts), new THREE.MeshBasicMaterial({ colorWrite: false }));
		occluder.renderOrder = -1;   // first, so the books are tested against it
		parts.forEach((g) => g.dispose());
		renderer.render(caseScene, camera);
		caseCanvas.width = canvas.width;
		caseCanvas.height = canvas.height;
		const ctx = caseCanvas.getContext("2d");
		ctx.drawImage(canvas, 0, 0);   // straight after drawing it, while the picture is still there
		// Darker behind the titles and prices, so they stay easy to read.
		const shade = ctx.createLinearGradient(0, 0, 0, caseCanvas.height);
		shade.addColorStop(0.5, "rgba(13, 31, 60, 0)");
		shade.addColorStop(0.72, "rgba(13, 31, 60, 0.7)");
		shade.addColorStop(1, "rgba(13, 31, 60, 0.85)");
		ctx.fillStyle = shade;
		ctx.fillRect(0, 0, caseCanvas.width, caseCanvas.height);
		renderer.clear();
		dispose(caseScene);
		bookcase.dispose();
	}

	// The books taken out.
	const scene = new THREE.Scene();
	scene.fog = new THREE.Fog(BOOKS_3D.navy, distance + 60, distance + 700);   // as hazy as the bookcase while in it
	const lights = addLights(THREE, scene, 1);
	const full = Object.fromEntries(Object.entries(lights).map(([name, light]) => [name, light.intensity]));
	if (occluder) scene.add(occluder);
	const pages = texture(pagesCanvas(), false);
	pages.wrapS = THREE.RepeatWrapping;
	pages.repeat.set((D - 0.7) / 0.4, 1);   // a line every 0.4vh
	const pagesMaterial = new THREE.MeshLambertMaterial({ map: pages, vertexColors: true });   // the headbands are coloured
	const deg = Math.PI / 180;
	const books = cards.map((card, i) => {
		const slot = Number(card.dataset.slot);
		const shelf = shelved[slot] || { cloth: "#444", size: 1, thickness: 1 };
		const flat = card.querySelector(".book-flat");
		const image = flat.querySelector("img");
		const cover = image?.naturalWidth ? image : null;   // one that didn't load gets a drawn cover
		const hue = Number(card.style.getPropertyValue("--hue")) || 0;
		const title = card.dataset.title || "", authors = card.dataset.authors || "";
		// As thick as its place on the shelf (squeezed there if the shelf is full), less what the raised bands and the caps
		// on its spine stick out, so it fits back between its neighbours.
		const room = bookcase.slots[slot]?.thickness ?? D * shelf.thickness;
		const w = W * shelf.size, h = H * shelf.size, d = room - 0.5;
		const book = makeBook(THREE, {
			W: w, H: h, D: d, pagesMaterial,
			cover: texture(coverCanvas(w, h, cover, hue, title, authors)),
			spine: texture(spineCanvas(d, h, shelf.cloth, title)),
			cloth: shelf.cloth,
			bands: !cover,   // a cloth-bound book: raised bands across the spine
		});
		scene.add(book);
		// Where it lands: standing on the bottom of its .book-flat, in the middle, hovering a little above it; turned
		// towards the camera by as much as it is to the side, so all books look turned alike.
		const place = flat.getBoundingClientRect();
		const end = onPage(place.left + place.width / 2, place.bottom);
		end.y += h / 2 + 4;
		end.turn = 18 - Math.atan2(end.x, distance) / deg;
		const start = bookcase.slots[slot] || { x: end.x, y: -height, z: 0 };
		return { book, card, i, start, end, depth: w };
	});

	// The same clock as the CSS animations of the glows and the text: from when the slide is shown (player.js removes
	// .loading). Book i starts 0.6 s + STEP s per book in, slides out of the shelf (0.8 s), then flies to the front (1.6 s).
	// At the end of the slide they go back the same way, the last one first, so they are in the bookcase when it ends.
	// STEP is as short as it can be without two books going through each other in any frame (0.7 s isn't, 0.8 s is: a
	// simulation of their paths over many bookcases), with a little to spare; the glows and texts (style.css) follow it.
	const STEP = 0.9;
	const seconds = Number(canvas.dataset.seconds) || 15;
	const outEase = cubicBezier(0.45, 0, 0.3, 1), flyEase = cubicBezier(0.3, 0.1, 0.2, 1);
	const pose = (t) => {
		let least = 1, most = 0;   // how far the books furthest from and nearest to the front are on their way there
		for (const { book, card, i, start, end, depth } of books) {
			const back = seconds - 0.4 - (books.length - 1 - i) * STEP - t;   // how long before it is back in its place
			const s = Math.min(t - 0.6 - i * STEP, back);
			card.classList.toggle("returning", back < 2.4);   // its glow fades as it leaves (style.css)
			const out = outEase(Math.min(Math.max(s / 0.8, 0), 1));
			const fly = flyEase(Math.min(Math.max((s - 0.8) / 1.6, 0), 1));
			// Hovering: up and down, 5 s each way, each book out of step with the others; and a little sway, all
			// books together (out of step, one book would look turned differently from the rest).
			const bob = swing((t + i * 1.7) / 5), sway = swing(t / 5);
			const pulled = { x: start.x, y: start.y, z: start.z + out * (depth + 3) };
			const lift = Math.sin(fly * Math.PI) * 12;   // an arc up on its way
			book.position.set(
				pulled.x + (end.x - pulled.x) * fly,
				pulled.y + (end.y + bob * 2.5 - pulled.y) * fly + lift,
				pulled.z * (1 - fly),
			);
			// On the shelf its spine faces us (90 degrees); it turns its cover to us, a bit too far on the way.
			const turn = 90 + (end.turn - 4 + sway * 9 - 90) * fly - Math.sin(fly * Math.PI) * 25;
			book.rotation.set(0, turn * deg, Math.sin(fly * Math.PI) * -6 * deg);
			least = Math.min(least, fly);
			most = Math.max(most, fly);
		}
		// The light: in the bookcase as bright as the bookcase (lights at 0.75, like its picture); the crimson light from
		// behind only once all books are at the front, as on the way their covers face it and would light up red.
		const light = 0.75 + 0.25 * most;
		lights.hemisphere.intensity = full.hemisphere * light;
		lights.key.intensity = full.key * light;
		lights.rim.intensity = full.rim * least * least;
	};
	pose(0);

	// One frame at a time while the slide is on the page; freed when it's gone (the browser has only a few WebGL contexts).
	const layer = canvas.closest(".layer");
	let started = null, measured = false;
	const times = [];
	const frame = (now) => {
		if (!document.contains(canvas)) {
			textures.forEach((t) => t.dispose());
			dispose(scene);
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
		// Too slow for this PC? Measure from 0.5 to 3 s (the books coming out) and drop to 75% resolution once.
		if (!measured && t > 0.5) {
			times.push(now);
			if (t > 3) {
				measured = true;
				const gaps = times.slice(1).map((time, n) => time - times[n]).sort((p, q) => p - q);
				if (gaps[Math.floor(gaps.length / 2)] > 20) {
					quality = 0.75;
					resize();
					console.info("Books in 3D: slow frames, drawing at 75% resolution");
				}
			}
		}
	};
	requestAnimationFrame(frame);
}

// A white light from the front left, a crimson one from behind (the glows), and light from all around.
function addLights(THREE, scene, strength) {
	const hemisphere = new THREE.HemisphereLight(0xfff8f0, 0x40507a, 2.3 * strength);
	scene.add(hemisphere);
	const key = new THREE.DirectionalLight(0xfff4e6, 2.2 * strength);
	key.position.set(-5, 4, 8);
	scene.add(key);
	const rim = new THREE.DirectionalLight(0xff2a4a, 3 * strength);
	rim.position.set(6, 1, -4);
	scene.add(rim);
	return { hemisphere, key, rim };
}

// The bookcase: a wooden case with `shelves` shelves, as wide as caseSize books of normal thickness (D) need, and the
// books in it in order, left to right and top to bottom, their spines flush with the front of the shelves. It stands
// as far back as it must to fill the screen from BOOKS_3D.caseTop to caseBottom. Returns
// - wood: its wood (a group);
// - slots: where each book stands (the middle of its spine: x, y, and z of the front);
// - shelfBooks(leaveOut): one mesh with all books but those in the set leaveOut, all their spines in one texture.
function makeBookcase(THREE, { W, H, D, books, caseSize, distance, height, texture }) {
	const { shelves } = BOOKS_3D;
	const perShelf = Math.ceil(caseSize / shelves);
	const inside = perShelf * D;   // a shelf's length
	const gap = H + 5;   // between two shelves
	const board = 2.5, side = 3, depth = W + 2;
	const outerW = inside + 2 * side, outerH = shelves * gap + (shelves + 1) * board;

	// How far back: so that it is (caseBottom - caseTop) vh tall on the screen, centred between them.
	const scale = (BOOKS_3D.caseBottom - BOOKS_3D.caseTop) / outerH;   // on-screen size / real size
	const front = distance - distance / scale;   // z of its front
	const middle = (height / 2 - (BOOKS_3D.caseTop + BOOKS_3D.caseBottom) / 2) / scale;   // y of its middle there
	const top = middle + outerH / 2;

	// The wood: every plank has rounded (bevelled) edges that catch the light. It is drawn only once, so it can have
	// as much detail as looks good. The grain runs along each plank: across for the shelves, up for the sides.
	const wood = new THREE.Group();
	const grain = texture(woodCanvas());
	grain.wrapS = grain.wrapT = THREE.RepeatWrapping;
	grain.repeat.set(1 / 60, 1 / 60);
	const upright = grain.clone();
	upright.rotation = Math.PI / 2;
	const woodMaterial = new THREE.MeshStandardMaterial({ map: grain, color: 0xb48a62, roughness: 0.6 });
	const uprightMaterial = new THREE.MeshStandardMaterial({ map: upright, color: 0xb48a62, roughness: 0.6 });
	const backMaterial = new THREE.MeshStandardMaterial({ map: upright, color: 0x5a4030, roughness: 0.85 });
	const metal = new THREE.MeshStandardMaterial({ color: 0x2a2d33, roughness: 0.35, metalness: 0.8 });
	const plank = (w, h, d, x, y, z, { material = woodMaterial, bevel = 0.6 } = {}) => {
		const mesh = new THREE.Mesh(bevelledBox(THREE, w, h, d, bevel), material);
		mesh.position.set(x, y, z);
		wood.add(mesh);
	};
	const back = front - depth / 2;   // the middle of the case, front to back
	// The sides, each with a raised pilaster on its front.
	for (const sign of [-1, 1]) {
		const x = sign * (outerW / 2 - side / 2);
		plank(side, outerH, depth, x, middle, back, { material: uprightMaterial });
		plank(side + 1.2, outerH - 3, 1.2, x, middle, front + 0.4, { material: uprightMaterial, bevel: 0.45 });
	}
	// The shelves, with a rounded front edge; the top and bottom ones too.
	for (let n = 0; n <= shelves; n++) {
		const y = top - board / 2 - n * (gap + board);
		plank(inside + 0.4, board, depth, 0, y, back, { bevel: 0.9 });
	}
	// The back: upright boards side by side, a little gap between them.
	const boards = Math.round(inside / 10);
	for (let n = 0; n < boards; n++) {
		const w = inside / boards;
		plank(w - 0.35, outerH - 2 * board, 1, -inside / 2 + (n + 0.5) * w, middle, front - depth + 0.5, { material: backMaterial, bevel: 0.3 });
	}
	// A cornice on top, stepping out, and a plinth.
	plank(outerW + 1.5, 2, depth + 1.5, 0, top + 1, back + 0.75);
	plank(outerW + 4.5, 1.6, depth + 3, 0, top + 2.8, back + 1.5, { bevel: 0.7 });
	plank(outerW + 2.5, 1.2, depth + 2, 0, top + 4.2, back + 1, { bevel: 0.5 });
	plank(outerW + 1, 4, depth + 0.5, 0, top - outerH - 2, back + 0.25, { bevel: 0.8 });

	// The places: each shelf holds perShelf books, set back a little from its rounded front edge (level with it, their
	// bottoms would hang over the edge and seem to sink into the shelf); thicker books than normal are squeezed a little if they don't fit.
	const slots = [];
	for (let start = 0; start < books.length; start += perShelf) {
		const row = books.slice(start, start + perShelf);
		const shelf = start / perShelf;
		const floor = top - board - shelf * (gap + board) - gap;
		const total = row.reduce((sum, book) => sum + D * book.thickness, 0);
		const squeeze = Math.min(1, (inside - 1) / total);
		let x = -inside / 2 + 0.5;
		for (const book of row) {
			const t = D * book.thickness * squeeze;
			slots.push({ x: x + t / 2, y: floor + H * book.size / 2, z: front - 1.5 - W * book.size / 2, thickness: t, book });
			x += t;
		}
		// A shelf that isn't full: a bookend holds the books up.
		if (row.length < perShelf) {
			const end = new THREE.Mesh(mergeGeometries(THREE, [
				bevelledBox(THREE, 0.5, 15, 12, 0.2).translate(0.25, 7.5, 0),
				bevelledBox(THREE, 7, 0.4, 12, 0.15).translate(3.5, 0.2, 0),
			]), metal);
			end.position.set(x + 0.1, floor, front - 7);
			wood.add(end);
		}
	}

	// All spines in one picture: TILE pixels each, in rows; the last pixels of the picture are white, for the sides
	// of the books (coloured by their vertices).
	const tileW = 40, tileH = 320, columns = Math.floor(2048 / tileW);
	const atlas = document.createElement("canvas");
	atlas.width = 2048;
	atlas.height = Math.ceil((books.length + 1) / columns) * tileH;
	const ctx = atlas.getContext("2d");
	books.forEach((book, n) => drawSpine(ctx, (n % columns) * tileW, Math.floor(n / columns) * tileH, tileW, tileH, book.cloth, book.title));
	ctx.fillStyle = "#ffffff";
	ctx.fillRect(atlas.width - 8, atlas.height - 8, 8, 8);
	const spines = texture(atlas);
	const white = [1 - 4 / atlas.width, 4 / atlas.height];

	// Each book on the shelf: a rounded spine, the two boards and the pages between them, set back a little.
	const shelfBooks = (leaveOut) => {
		const cream = new THREE.Color(0xf2ead8), clothColour = new THREE.Color();
		const parts = [];
		slots.forEach((slot, n) => {
			if (leaveOut.has(n)) return;
			const { book, thickness: t } = slot;
			const h = H * book.size, d = W * book.size;
			const bulge = Math.min(t * 0.3, 0.9);
			clothColour.set(book.cloth).convertSRGBToLinear();
			const u0 = (n % columns) * tileW / atlas.width, v1 = 1 - Math.floor(n / columns) * tileH / atlas.height;
			// The spine: half an oval, its picture taken from the atlas; its ends are cloth.
			const spine = new THREE.CylinderGeometry(1, 1, h, 8, 1, false, -Math.PI / 2, Math.PI);
			spine.scale(t / 2, 1, bulge).translate(0, 0, d / 2 - bulge);
			paint(spine, (u, v, normal) => Math.abs(normal.y) > 0.5
				? [white, clothColour]
				: [[u0 + u * tileW / atlas.width, v1 - (1 - v) * tileH / atlas.height], null]);
			parts.push(spine);
			const body = d - bulge;
			for (const sign of [-1, 1]) {
				const cover = new THREE.BoxGeometry(0.35, h, body).translate(sign * (t / 2 - 0.175), 0, -bulge / 2);
				parts.push(paint(cover, () => [white, clothColour]));
			}
			const pages = new THREE.BoxGeometry(Math.max(t - 0.7, 0.2), h - 0.8, body - 0.4).translate(0, 0, -bulge / 2 - 0.2);
			parts.push(paint(pages, () => [white, cream]));
			for (const part of parts.slice(-4)) part.translate(slot.x, slot.y, slot.z);
		});
		const geometry = mergeGeometries(THREE, parts);
		parts.forEach((part) => part.dispose());
		return new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ map: spines, vertexColors: true, roughness: 0.75 }));
	};

	return {
		wood,
		shelfBooks,
		slots: slots.map(({ x, y, z, thickness }) => ({ x, y, z, thickness })),
		dispose: () => { grain.dispose(); upright.dispose(); spines.dispose(); },
	};
}

// A hardcover book standing upright, its front cover facing +z and the spine on the left (-x); W x H x D in total.
// The boards have rounded edges and corners and the front one is embossed by its own picture (a bump map: the gold
// title of a drawn cover stands out, a printed one a little); the pages are set back, their fore edge curved in, with a
// headband at the top and bottom; cloth-bound books (drawn covers) have raised bands across the spine. 5 draw calls.
function makeBook(THREE, { W, H, D, pagesMaterial, cover, spine, cloth, bands }) {
	const board = 0.5, over = 0.45;   // the boards' thickness, and how far they stick out past the pages
	const r = D / 2;   // the rounded spine
	const hinge = -W / 2 + r;
	const group = new THREE.Group();
	const clothColour = new THREE.Color(cloth).multiplyScalar(0.8);
	const clothMaterial = new THREE.MeshStandardMaterial({ color: clothColour, roughness: 0.85 });
	const coverMaterial = new THREE.MeshStandardMaterial({ map: cover, bumpMap: cover, bumpScale: 1.5, roughness: 0.45 });   // a little gloss: a moving highlight

	// The boards: a rounded rectangle with bevelled edges. The picture covers the flat front only (u and v from 0 to 1
	// over it); the edges are cloth.
	const boardW = W - r + 0.15;
	const boardGeometry = bevelledBox(THREE, boardW, H, board, 0.2, 0.6);
	const box = new THREE.Box3().setFromBufferAttribute(boardGeometry.attributes.position);
	const position = boardGeometry.attributes.position, uv = boardGeometry.attributes.uv;
	for (let v = 0; v < uv.count; v++) {
		uv.setXY(v, (position.getX(v) - box.min.x) / (box.max.x - box.min.x), (position.getY(v) - box.min.y) / (box.max.y - box.min.y));
	}
	const front = new THREE.Mesh(boardGeometry, [coverMaterial, clothMaterial]);
	front.position.set(hinge - 0.15 + boardW / 2, 0, r - board / 2);

	// The back board, and on the spine the raised bands and the caps at its ends: one mesh, all cloth.
	const cloth3d = [boardGeometry.clone().translate(hinge - 0.15 + boardW / 2, 0, -r + board / 2)];
	if (bands) {
		for (const y of [-0.3, -0.1, 0.1, 0.3]) {
			const band = new THREE.TorusGeometry(r, 0.22, 6, 16, Math.PI);
			band.rotateX(Math.PI / 2).rotateY(-Math.PI / 2).translate(hinge, y * H, 0);
			cloth3d.push(band);
		}
	}
	for (const sign of [-1, 1]) {
		const cap = new THREE.TorusGeometry(r - 0.1, 0.18, 6, 16, Math.PI);
		cap.rotateX(Math.PI / 2).rotateY(-Math.PI / 2).translate(hinge, sign * (H / 2 - 0.18), 0);
		cloth3d.push(cap);
	}
	const backMesh = new THREE.Mesh(mergeGeometries(THREE, cloth3d), clothMaterial);
	cloth3d.forEach((g) => g.dispose());

	const spineMesh = new THREE.Mesh(new THREE.CylinderGeometry(r, r, H, 24, 1, true, Math.PI, Math.PI),
		new THREE.MeshStandardMaterial({ map: spine, roughness: 0.7, side: THREE.DoubleSide }));
	spineMesh.position.x = hinge;

	// The pages: the lines of the texture run along the thickness on the fore edge, the top and the bottom (a box maps
	// its top and bottom the other way round, so their u and v are swapped). The whole block is bent a little, as the
	// rounded spine pushes the middle pages out: the fore edge curves in. Headbands at the top and bottom of the spine.
	const blockW = W - r - over, blockD = D - 2 * board;
	const block = new THREE.BoxGeometry(blockW, H - 2 * over, blockD, 1, 1, 8);
	const blockUv = block.attributes.uv, blockNormal = block.attributes.normal, blockPosition = block.attributes.position;
	for (let v = 0; v < blockUv.count; v++) {
		if (Math.abs(blockNormal.getY(v)) > 0.5) blockUv.setXY(v, blockUv.getY(v), blockUv.getX(v));
		const across = 2 * blockPosition.getZ(v) / blockD;
		blockPosition.setX(v, blockPosition.getX(v) - 0.5 * (1 - across * across));
	}
	block.computeVertexNormals();
	block.translate(hinge + blockW / 2 + 0.25, 0, 0);
	paint(block, () => [null, new THREE.Color(1, 1, 1)]);
	const headbands = [-1, 1].map((sign) => {
		const band = new THREE.CylinderGeometry(0.28, 0.28, blockD, 8).rotateX(Math.PI / 2);
		band.translate(hinge + 0.15, sign * (H / 2 - over - 0.1), 0);
		return paint(band, (u) => [[0.1, 0.5], Math.floor(u * 8 * 4) % 2 ? new THREE.Color(0.5, 0.05, 0.08) : new THREE.Color(0.9, 0.85, 0.7)]);
	});
	const pagesMesh = new THREE.Mesh(mergeGeometries(THREE, [block, ...headbands]), pagesMaterial);
	block.dispose();
	headbands.forEach((g) => g.dispose());

	group.add(front, backMesh, spineMesh, pagesMesh);
	return group;
}

// A box w x h x d, centred, with bevelled edges (`bevel` deep) and, seen from the front, corners rounded by `corner`.
// Its front and back (the caps) are group 0, the edges group 1.
function bevelledBox(THREE, w, h, d, bevel, corner = 0) {
	const b = Math.max(0.01, Math.min(bevel, w / 3, h / 3, d / 3));
	const iw = w / 2 - b, ih = h / 2 - b, c = Math.min(corner, iw, ih);
	const shape = new THREE.Shape();
	shape.moveTo(-iw + c, -ih);
	shape.lineTo(iw - c, -ih);
	if (c) shape.quadraticCurveTo(iw, -ih, iw, -ih + c);
	shape.lineTo(iw, ih - c);
	if (c) shape.quadraticCurveTo(iw, ih, iw - c, ih);
	shape.lineTo(-iw + c, ih);
	if (c) shape.quadraticCurveTo(-iw, ih, -iw, ih - c);
	shape.lineTo(-iw, -ih + c);
	if (c) shape.quadraticCurveTo(-iw, -ih, -iw + c, -ih);
	const geometry = new THREE.ExtrudeGeometry(shape, {
		depth: d - 2 * b, bevelEnabled: true, bevelThickness: b, bevelSize: b, bevelSegments: 3, curveSegments: 4,
	});
	return geometry.translate(0, 0, -(d - 2 * b) / 2);
}

// Gives a geometry a colour per vertex and, where the function says so, new uv: f(u, v, normal) -> [uv or null, colour or null]
// (null: keep the uv; white).
function paint(geometry, f) {
	const uv = geometry.attributes.uv, normal = geometry.attributes.normal;
	const colours = new Float32Array(uv.count * 3);
	const n = { x: 0, y: 0, z: 0 };
	for (let v = 0; v < uv.count; v++) {
		n.x = normal.getX(v); n.y = normal.getY(v); n.z = normal.getZ(v);
		const [newUv, colour] = f(uv.getX(v), uv.getY(v), n);
		if (newUv) uv.setXY(v, newUv[0], newUv[1]);
		colours.set(colour ? [colour.r, colour.g, colour.b] : [1, 1, 1], v * 3);
	}
	geometry.setAttribute("color", new geometry.attributes.position.constructor(colours, 3));
	return geometry;
}

// Several geometries as one (fewer draw calls): their position, normal, uv and, if they all have it, colour.
function mergeGeometries(THREE, geometries) {
	const names = ["position", "normal", "uv", "color"].filter((name) => geometries.every((g) => g.attributes[name]));
	const data = Object.fromEntries(names.map((name) => [name, []]));
	const indices = [];
	let offset = 0;
	for (const g of geometries) {
		for (const name of names) data[name].push(...g.attributes[name].array);
		const count = g.attributes.position.count;
		if (g.index) indices.push(...Array.from(g.index.array, (i) => i + offset));
		else for (let i = 0; i < count; i++) indices.push(i + offset);
		offset += count;
	}
	const merged = new THREE.BufferGeometry();
	for (const name of names) merged.setAttribute(name, new THREE.Float32BufferAttribute(data[name], name === "uv" ? 2 : 3));
	merged.setIndex(indices);
	return merged;
}

// The front cover as a picture 512 pixels wide: the cover from Open Library cut to the book's shape (like
// object-fit: cover), or a cloth cover with a gold title for books without one; then the hinge's groove.
function coverCanvas(W, H, image, hue, title, authors) {
	const canvas = document.createElement("canvas");
	const scale = 512 / W;   // pixels per vh
	canvas.width = 512;
	canvas.height = Math.round(H * scale);
	const ctx = canvas.getContext("2d");
	if (image) {
		const fit = Math.max(canvas.width / image.naturalWidth, canvas.height / image.naturalHeight);
		const w = image.naturalWidth * fit, h = image.naturalHeight * fit;
		ctx.drawImage(image, (canvas.width - w) / 2, (canvas.height - h) / 2, w, h);
	} else {
		// Sizes in vh like the CSS (.book-drawn), drawn in pixels: px(). Not with ctx.scale(): Firefox leaves out
		// text with a font size of a few pixels, even when it is scaled up.
		const px = (v) => v * scale;
		const cloth = ctx.createLinearGradient(0, 0, px(W * 0.34), px(H));   // like 160deg in CSS
		cloth.addColorStop(0, `hsl(${hue} 32% 34%)`);
		cloth.addColorStop(1, `hsl(${hue} 35% 22%)`);
		ctx.fillStyle = cloth;
		ctx.fillRect(0, 0, canvas.width, canvas.height);
		ctx.fillStyle = "#e8d29b";
		ctx.fillRect(px(3.8), px(4), px(4), px(0.25));
		const textWidth = px(W - 3.8 - 2.5);
		// The authors at the bottom, then the title above them in what room is left: smaller for a long title or a
		// long word (down to 2vh), cut off with an ellipsis only if even that doesn't fit.
		ctx.font = `700 ${px(1.6)}px "Familjen Grotesk", "DejaVu Sans", sans-serif`;
		if ("letterSpacing" in ctx) ctx.letterSpacing = `${px(0.1)}px`;
		const lines = wrapText(ctx, authors.toUpperCase(), textWidth, 2);
		ctx.globalAlpha = 0.8;
		ctx.textBaseline = "bottom";
		lines.forEach((line, n) => ctx.fillText(line, px(3.8), px(H - 4 - (lines.length - 1 - n) * 1.6 * 1.3)));
		ctx.globalAlpha = 1;
		if ("letterSpacing" in ctx) ctx.letterSpacing = "0px";
		const room = H - 4 - lines.length * 1.6 * 1.3 - 1.5 - 5;   // between the gold line and the authors, in vh
		let fontSize = 2.7, titleLines;
		for (; ; fontSize -= 0.1) {
			ctx.font = `700 ${px(fontSize)}px "Familjen Grotesk", "DejaVu Sans", sans-serif`;
			const most = Math.max(1, Math.floor(room / (fontSize * 1.25)));
			const longestWord = Math.max(...title.split(/\s+/).map((word) => ctx.measureText(word).width));
			titleLines = wrapText(ctx, title, textWidth, most);
			const fits = longestWord <= textWidth && !titleLines.at(-1)?.endsWith("…");
			if (fits || fontSize <= 2) break;
		}
		ctx.textBaseline = "top";
		titleLines.forEach((line, n) => ctx.fillText(line, px(3.8), px(5 + n * fontSize * 1.25)));
	}
	const groove = ctx.createLinearGradient(0, 0, 2 * scale, 0);
	groove.addColorStop(0, "rgba(0, 0, 0, 0.3)");
	groove.addColorStop(0.45, "rgba(255, 255, 255, 0.15)");
	groove.addColorStop(0.75, "rgba(0, 0, 0, 0.1)");
	groove.addColorStop(1, "rgba(0, 0, 0, 0)");
	ctx.fillStyle = groove;
	ctx.fillRect(0, 0, 2 * scale, canvas.height);
	return canvas;
}

// The spine of a book taken out: it wraps around half a cylinder, so it is pi * D / 2 wide.
function spineCanvas(D, H, cloth, title) {
	const canvas = document.createElement("canvas");
	canvas.height = 512;
	canvas.width = Math.round(Math.PI * D / 2 * 512 / H);
	drawSpine(canvas.getContext("2d"), 0, 0, canvas.width, canvas.height, cloth, title);
	return canvas;
}

// A spine at (x, y), w x h pixels: cloth with gold bands at the top and bottom and the title reading from top to bottom.
function drawSpine(ctx, x, y, w, h, cloth, title) {
	ctx.save();
	ctx.beginPath();
	ctx.rect(x, y, w, h);
	ctx.clip();
	ctx.fillStyle = cloth;
	ctx.fillRect(x, y, w, h);
	ctx.fillStyle = "rgba(0, 0, 0, 0.25)";   // the cloth of the spine a bit darker than the cover
	ctx.fillRect(x, y, w, h);
	ctx.fillStyle = "#e8d29b";
	const band = Math.max(1, Math.round(h / 170));
	for (const at of [0.035, 0.051, 1 - 0.055, 1 - 0.039]) ctx.fillRect(x, y + Math.round(at * h), w, band);
	ctx.translate(x + w / 2, y + h * 0.086);
	ctx.rotate(Math.PI / 2);
	ctx.font = `700 ${Math.round(w * 0.32)}px "Familjen Grotesk", "DejaVu Sans", sans-serif`;
	ctx.textBaseline = "middle";
	ctx.fillText(wrapText(ctx, title, h * 0.83, 1)[0] || "", 0, 0);
	ctx.restore();
}

// The edge of the pages: cream with a thin grey line, repeated.
function pagesCanvas() {
	const canvas = document.createElement("canvas");
	canvas.width = 8;
	canvas.height = 2;
	const ctx = canvas.getContext("2d");
	ctx.fillStyle = "#f7f2e8";
	ctx.fillRect(0, 0, 6, 2);
	ctx.fillStyle = "#cfc4b0";
	ctx.fillRect(6, 0, 2, 2);
	return canvas;
}

// Wood: light and dark streaks along the grain, the same everywhere (random, but always the same streaks).
function woodCanvas() {
	const canvas = document.createElement("canvas");
	canvas.width = canvas.height = 256;
	const ctx = canvas.getContext("2d");
	ctx.fillStyle = "#c8c8c8";
	ctx.fillRect(0, 0, 256, 256);
	let seed = 7;
	const random = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
	for (let n = 0; n < 70; n++) {
		const y = random() * 256, light = random() < 0.5;
		ctx.strokeStyle = light ? `rgba(255, 255, 255, ${0.1 + random() * 0.15})` : `rgba(0, 0, 0, ${0.08 + random() * 0.15})`;
		ctx.lineWidth = 1 + random() * 3;
		ctx.beginPath();
		const wave = random() * 6, phase = random() * 6;
		for (let x = 0; x <= 256; x += 16) ctx.lineTo(x, y + Math.sin(x / 40 + phase) * wave);
		ctx.stroke();
	}
	return canvas;
}

// The words of `text` in lines no wider than `width`, at most `most` lines (the last one cut off with an ellipsis).
function wrapText(ctx, text, width, most) {
	const lines = [];
	let line = "";
	for (const word of text.split(/\s+/).filter(Boolean)) {
		const longer = line ? `${line} ${word}` : word;
		if (ctx.measureText(longer).width <= width || !line) line = longer;
		else {
			lines.push(line);
			line = word;
		}
	}
	if (line) lines.push(line);
	if (lines.length > most || (lines.length && ctx.measureText(lines[most - 1] ?? "").width > width)) {
		let last = lines.slice(most - 1).join(" ");
		while (last && ctx.measureText(`${last}…`).width > width) last = last.slice(0, -1);
		lines.splice(most - 1, Infinity, `${last.trimEnd()}…`);
	}
	return lines;
}

// Back and forth like a CSS animation with "ease-in-out infinite alternate": 0 to 1 over each unit of phase, then back.
function swing(phase) {
	const f = Math.floor(phase) % 2 === 1 ? 1 - (phase % 1) : phase % 1;
	return 0.5 - 0.5 * Math.cos(Math.PI * f);
}

// A CSS cubic-bezier() timing function: progress (0 to 1) -> eased progress.
function cubicBezier(x1, y1, x2, y2) {
	const at = (t, p1, p2) => 3 * (1 - t) * (1 - t) * t * p1 + 3 * (1 - t) * t * t * p2 + t * t * t;
	return (x) => {
		if (x <= 0) return 0;
		if (x >= 1) return 1;
		let lo = 0, hi = 1, t = x;
		for (let n = 0; n < 24; n++) {
			t = (lo + hi) / 2;
			if (at(t, x1, x2) < x) lo = t;
			else hi = t;
		}
		return at(t, y1, y2);
	};
}
