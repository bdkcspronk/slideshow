// Widgets inside slides, set up by setupWidgets() after a slide is drawn (player.js) or in a
// preview (preview.html):
// - data-map: a Leaflet map (static/vendor/leaflet) with tiles from data-tiles. Tapping it puts a
//   pin there and makes "lat,lng" its value. With data-pins ({"guess": [lat, lng], "answer": [...]})
//   it shows both pins and a line between them instead (e.g. TimeGuessr's answer).
// - data-field: a value that an action button with data-send-fields sends along, in page order: a
//   map's pin, or an <input type="range">. [data-field-output="name"] shows a field's value,
//   data-nudge="name" buttons change a range by data-by, and data-needs-fields buttons stay
//   disabled until every field has a value.
// - data-marquee: a one-line text that scrolls round and round like a ticker when it's too long to
//   fit (e.g. Spotify's song, artist and album); one that fits stays put.
// - data-marquee-up: a list too tall for its box (e.g. a full day in the timetable) slowly scrolls down
//   to its end, waits, and scrolls back up, over and over; one that fits stays put.
// - data-lyrics: synced lyrics (Spotify): lines with data-time (seconds into the song). The line being
//   sung gets .current (lines before it .past) and is kept in view, counting on from data-start
//   while data-playing is set. The server redraws the slide when the song changes, pauses or jumps.
// - data-lyric-video: a lyric video (providers/lyric_video.py): of the lines in its hidden list (data-time:
//   seconds into the song), the one being sung is shown big, each line in one of LYRIC_STYLES and the next
//   of LYRIC_PALETTES; its words pop in one by one over the time until the next line (about as they're
//   sung), the line before flies out. An empty line (a pause) shows bouncing notes. Counts on from
//   data-start while data-playing is set; [data-lyric-video-bar] is the song's progress (data-total).
// - data-zoom: a photo (an <img> in a .zoom-view) that can be zoomed while it's full screen (.selected,
//   e.g. TimeGuessr): two fingers or the mouse wheel zoom, dragging moves it, data-zoom-by buttons zoom
//   by that factor (0: back to the whole photo). A tap without dragging still toggles full screen.
// - data-qr: a QR code of the link in data-qr (static/vendor/qrcode), e.g. the weekly dilemma's form.
//   data-qr-level="H" makes it readable with a picture over its middle (the membership slide's professor).
// - data-matrix: Matrix code rain on a <canvas>; now and then a column spells one of data-words
//   (separated by spaces; | for a space inside a word). The Compucie slide.
// - data-decode: a title that decodes: each letter of data-decode flickers through random glyphs and
//   settles, left to right, starting after data-decode-wait seconds.
// - data-terminal: a terminal session that types itself after data-terminal-wait seconds: each child's
//   data-command is typed after data-prompt, then the child (its answer) appears. When it's done the
//   slide gets .typed (e.g. to show what comes after).
// - data-three: a Three.js scene (see THREE_SCENES) with a live frames-per-second readout and buttons to switch scene and resolution: a test of the TV PC's graphics.
// - data-books-3d: the books slide's books in real 3D on a <canvas> (static/books_3d.js).
// - data-activities-3d: the upcoming activities as split-flap displays in 3D on a <canvas> (static/activities_3d.js).
// - data-three-benchmark: the 3D benchmark's slide: its Start button runs static/three_benchmark.js and sends the results to the server.
// - data-play-at-start: a <video> that plays from the start of its slide, also while it is out of view
//   (a post further down the Instagram feed): the browser holds back a video with the autoplay
//   attribute until it is on screen. startVideos() is called when the slide is drawn and again when it fades in.

const maps = new Set();

function setupWidgets(root) {
	for (const map of maps) {   // maps of slides that are gone
		if (!document.contains(map.getContainer())) {
			map.remove();
			maps.delete(map);
		}
	}
	root.querySelectorAll("[data-map]").forEach(setupMap);
	root.querySelectorAll("[data-lyrics]").forEach(setupLyrics);
	root.querySelectorAll("[data-lyric-video]").forEach(setupLyricVideo);
	root.querySelectorAll("[data-marquee]").forEach(setupMarquee);
	root.querySelectorAll("[data-marquee-up]").forEach(setupMarqueeUp);
	root.querySelectorAll("[data-qr]").forEach(setupQr);
	root.querySelectorAll("[data-zoom]").forEach(setupZoom);
	root.querySelectorAll("canvas[data-matrix]").forEach(setupMatrix);
	root.querySelectorAll("[data-decode]").forEach(setupDecode);
	root.querySelectorAll("[data-terminal]").forEach(setupTerminal);
	root.querySelectorAll("canvas[data-three]").forEach(setupThree);
	root.querySelectorAll("canvas[data-books-3d]").forEach(setupBooks3d);
	root.querySelectorAll("canvas[data-activities-3d]").forEach(setupActivities3d);
	root.querySelectorAll("[data-three-benchmark]").forEach(setupThreeBenchmark);
	startVideos(root);
	root.querySelectorAll("input[type=range][data-field]").forEach((input) => {
		input.addEventListener("input", () => fieldChanged(input));
		fieldChanged(input);
	});
}

function startVideos(root, fromStart = false) {
	for (const video of root.querySelectorAll("video[data-play-at-start]")) {
		if (fromStart || video.dataset.startedAt === undefined) {
			video.currentTime = 0;
			video.dataset.startedAt = performance.now();
		}
		video.play().catch(() => {});   // e.g. a video that isn't there
		if (!video.dataset.syncing) {
			video.dataset.syncing = "1";
			syncVideo(video);
		}
	}
}

// The browser may keep a video paused while it is scrolling into view (or only let it play once the
// scrolling has stopped). Meanwhile we seek it along with the slide's clock, so it still moves.
function syncVideo(video) {
	const tick = () => {
		if (!document.contains(video)) return;
		if (video.paused && video.duration) {
			const elapsed = (performance.now() - Number(video.dataset.startedAt)) / 1000;
			video.currentTime = elapsed % video.duration;
			video.play().catch(() => {});
		}
		setTimeout(tick, 100);
	};
	tick();
}

function setupZoom(element) {
	const img = element.querySelector(".zoom-view img");
	if (!img) return;
	let scale = 1, x = 0, y = 0;   // the photo's zoom and shift, in px from the middle
	let dragged = false;
	const pointers = new Map();   // pointerId -> {x, y}
	let pinch = null;             // {distance, scale} when two fingers went down

	const apply = () => {
		const view = img.parentElement.getBoundingClientRect();
		const maxX = view.width * (scale - 1) / 2, maxY = view.height * (scale - 1) / 2;   // not past the edges
		x = Math.max(-maxX, Math.min(maxX, x));
		y = Math.max(-maxY, Math.min(maxY, y));
		img.style.transform = `translate(${x}px, ${y}px) scale(${scale})`;
		element.classList.toggle("zoomed", scale > 1);
	};
	// Zoom by `factor` around a point on the screen (the fingers, the mouse); the photo stays under it.
	const zoom = (factor, at) => {
		const view = img.parentElement.getBoundingClientRect();
		const next = factor === 0 ? 1 : Math.max(1, Math.min(6, scale * factor));
		const cx = (at ? at.x : view.left + view.width / 2) - (view.left + view.width / 2);
		const cy = (at ? at.y : view.top + view.height / 2) - (view.top + view.height / 2);
		x = cx - (cx - x) * next / scale;
		y = cy - (cy - y) * next / scale;
		scale = next;
		apply();
	};
	const full = () => element.classList.contains("selected");

	element.addEventListener("wheel", (event) => {
		if (!full()) return;
		event.preventDefault();
		zoom(event.deltaY < 0 ? 1.2 : 1 / 1.2, { x: event.clientX, y: event.clientY });
	}, { passive: false });
	element.addEventListener("pointerdown", (event) => {
		if (event.target.closest("button")) return;
		pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
		dragged = false;
		if (pointers.size === 2) {
			const [a, b] = [...pointers.values()];
			pinch = { distance: Math.hypot(a.x - b.x, a.y - b.y), scale };
		}
	});
	element.addEventListener("pointermove", (event) => {
		const last = pointers.get(event.pointerId);
		if (!last || !full()) return;
		const now = { x: event.clientX, y: event.clientY };
		pointers.set(event.pointerId, now);
		if (pointers.size === 2 && pinch) {
			const [a, b] = [...pointers.values()];
			zoom(pinch.scale * Math.hypot(a.x - b.x, a.y - b.y) / pinch.distance / scale, { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });
			dragged = true;
		} else if (pointers.size === 1 && scale > 1) {
			x += now.x - last.x;
			y += now.y - last.y;
			if (Math.abs(now.x - last.x) + Math.abs(now.y - last.y) > 1) dragged = true;
			apply();
		}
	});
	const up = (event) => {
		pointers.delete(event.pointerId);
		if (pointers.size < 2) pinch = null;
	};
	element.addEventListener("pointerup", up);
	element.addEventListener("pointercancel", up);
	// A drag, a pinch or a zoom button is not a tap: it mustn't close full screen (player.js toggles on click).
	element.addEventListener("click", (event) => {
		const button = event.target.closest("[data-zoom-by]");
		if (button) {
			event.stopPropagation();
			zoom(Number(button.dataset.zoomBy));
		} else if (dragged) {
			event.stopPropagation();
		}
		dragged = false;
	}, true);
	// Back to the whole photo when it leaves full screen.
	new MutationObserver(() => { if (!full() && scale !== 1) zoom(0); }).observe(element, { attributes: true, attributeFilter: ["class"] });
}

function setupQr(element) {
	if (typeof qrcode === "undefined") return;   // the QR library didn't load
	const qr = qrcode(0, element.dataset.qrLevel || "M");   // 0: as small as the link allows; M: still readable when a bit dirty
	qr.addData(element.dataset.qr);
	qr.make();
	element.innerHTML = qr.createSvgTag({ cellSize: 1, margin: 2, scalable: true });
}

function setupMap(element) {
	if (typeof L === "undefined") return;   // Leaflet didn't load
	const map = L.map(element, { worldCopyJump: true, minZoom: 1, zoomSnap: 0.5 });
	maps.add(map);
	L.tileLayer(element.dataset.tiles, { attribution: element.dataset.attribution || "", maxZoom: 19 }).addTo(map);
	const pins = element.dataset.pins ? JSON.parse(element.dataset.pins) : null;
	if (pins) {
		const guess = L.latLng(pins.guess);
		const answer = L.latLng(pins.answer);
		L.polyline([guess, answer], { color: "#173249", weight: 3, dashArray: "8 8", interactive: false }).addTo(map);   // Francken blue (--blue in style.css)
		mapPin(guess, "guess").addTo(map);
		mapPin(answer, "answer").addTo(map);
		map.fitBounds(L.latLngBounds([guess, answer]), { padding: [60, 60], maxZoom: 13 });
		return;
	}
	map.fitBounds([[-50, -150], [70, 170]]);   // the whole world, without most of the ice
	let pin = null;
	map.on("click", (event) => {
		if (pin) pin.setLatLng(event.latlng);
		else pin = mapPin(event.latlng, "guess").addTo(map);
		const at = event.latlng.wrap();   // the world repeats sideways: back to -180..180
		element.dataset.value = `${at.lat.toFixed(6)},${at.lng.toFixed(6)}`;
		fieldChanged(element);
	});
}

function setupMarquee(element) {
	// <span.marquee-inner><span.marquee-copy><span.marquee-text>the text</span></span>(a second copy)</span>:
	// the copies scroll left together, and when the first has gone by the second is where it began,
	// so the loop has no seam. The gap between them is the copies' padding (style.css).
	const text = document.createElement("span");
	text.className = "marquee-text";
	text.append(...element.childNodes);
	const copy = document.createElement("span");
	copy.className = "marquee-copy";
	copy.append(text);
	const inner = document.createElement("span");
	inner.className = "marquee-inner";
	inner.append(copy);
	element.append(inner);
	let second = null;
	const measure = () => {
		const sliding = text.offsetWidth > element.clientWidth + 2;   // the text doesn't fit
		element.classList.toggle("marquee", sliding);
		if (!sliding) {
			second?.remove();
			second = null;
			return;
		}
		if (!second) {
			second = copy.cloneNode(true);
			second.setAttribute("aria-hidden", "true");
			inner.append(second);
		}
		const distance = copy.offsetWidth;   // one copy and its gap
		if (element.style.getPropertyValue("--marquee-distance") === `${-distance}px`) return;   // already right
		element.style.setProperty("--marquee-distance", `${-distance}px`);
		element.style.setProperty("--marquee-seconds", `${distance / 40}s`);   // 40 px a second
	};
	// Measured now, and again once the slide has settled (it's drawn in a hidden layer, and pictures
	// and fonts can still change the layout).
	measure();
	setTimeout(measure, 500);
	setTimeout(measure, 2000);
}

function setupMarqueeUp(element) {
	// <div.marquee-up-inner><div.marquee-up-copy>the list</div></div>, moved up by as much as doesn't fit.
	const copy = document.createElement("div");
	copy.className = "marquee-up-copy";
	copy.append(...element.childNodes);
	const inner = document.createElement("div");
	inner.className = "marquee-up-inner";
	inner.append(copy);
	element.append(inner);
	const measure = () => {
		const hidden = copy.offsetHeight - element.clientHeight;   // how much doesn't fit
		const sliding = hidden > 2;
		element.classList.toggle("marquee-up", sliding);
		if (!sliding || element.style.getPropertyValue("--marquee-distance") === `${-hidden}px`) return;   // nothing to do / already right
		element.style.setProperty("--marquee-distance", `${-hidden}px`);
		// 20 px a second while moving (slow, to read along); the waits at both ends are 15% of the time each.
		element.style.setProperty("--marquee-seconds", `${hidden / 20 / 0.7}s`);
	};
	measure();
	setTimeout(measure, 500);
	setTimeout(measure, 2000);
}

function setupLyrics(element) {
	const lines = [...element.querySelectorAll("[data-time]")];
	const start = parseFloat(element.dataset.start || "0");
	const playing = element.hasAttribute("data-playing");
	const shownAt = performance.now();
	let current = null;
	const follow = () => {
		if (!document.contains(element)) return clearInterval(timer);   // the slide is gone
		const seconds = start + (playing ? (performance.now() - shownAt) / 1000 : 0);
		const index = lines.findLastIndex((line) => parseFloat(line.dataset.time) <= seconds + 0.15);
		const line = lines[index] || null;
		if (line === current) return;
		current = line;
		lines.forEach((other, i) => {
			other.classList.toggle("current", i === index);
			other.classList.toggle("past", i < index);
		});
		if (line) element.scrollTo({ top: line.offsetTop - element.clientHeight * 0.4, behavior: "smooth" });
	};
	const timer = setInterval(follow, 200);
	follow();
}

// The styles a line can get (.lv-style-... in style.css). by: what pops in one by one, words or letters.
// stack: one word per row, each as wide as the screen (only for lines of a few words).
const LYRIC_STYLES = [
	{ name: "slam", by: "word" },
	{ name: "rise", by: "word" },
	{ name: "stack", by: "word", maxWords: 5 },
	{ name: "sticker", by: "word" },
	{ name: "outline", by: "word" },
	{ name: "wave", by: "letter" },
	{ name: "type", by: "letter" },
];
// [background, text, accent]: Francken's own colours among them.
const LYRIC_PALETTES = [
	["#173249", "#ffffff", "#ff5a6a"],
	["#ffd23f", "#141414", "#e4002b"],
	["#ff4f9a", "#ffffff", "#24124a"],
	["#101010", "#f4f4f4", "#1ed760"],
	["#f3ece0", "#173249", "#dc3545"],
	["#5b2bff", "#ffffff", "#ffd23f"],
	["#00c2a8", "#0b1d26", "#ffffff"],
	["#dc3545", "#ffffff", "#ffd23f"],
];

function setupLyricVideo(stage) {
	const slide = stage.closest(".lyric-video");
	const lines = [...stage.querySelectorAll("li[data-time]")].map((item) => ({
		time: parseFloat(item.dataset.time),
		text: item.textContent.replace(/<\d+:\d+(?:\.\d+)?>/g, "").replace(/\s+/g, " ").trim(),   // without word times
	}));
	const start = parseFloat(stage.dataset.start || "0");
	const total = parseFloat(stage.dataset.total || "0");
	const playing = stage.hasAttribute("data-playing");
	const bar = slide.querySelector("[data-lyric-video-bar]");
	const shownAt = performance.now();
	let current, shown = null, lastStyle = null, colour = Math.floor(start / 7) % LYRIC_PALETTES.length;

	const hash = (text) => [...text.toLowerCase()].reduce((sum, char) => (sum * 31 + char.charCodeAt(0)) >>> 0, 7);
	const pickStyle = (text, words) => {   // the same line (a chorus) gets the same style each time it comes back
		const fitting = LYRIC_STYLES.filter((style) => !style.maxWords || words <= style.maxWords);
		let style = fitting[hash(text) % fitting.length];
		if (style === lastStyle) style = fitting[(fitting.indexOf(style) + 1) % fitting.length];
		return (lastStyle = style);
	};

	const show = (index) => {
		const line = lines[index];
		const next = lines[index + 1];
		const seconds = Math.min(8, Math.max(1, (next ? next.time : line ? line.time + 4 : 4) - (line ? line.time : 0)));
		const element = document.createElement("div");
		if (!line || !line.text) {   // before the first line, or a pause in the singing
			element.className = "lv-line lv-pause";
			element.innerHTML = "<span>&#9834;</span><span>&#9835;</span><span>&#9834;</span>";
		} else {
			const words = line.text.split(" ");
			const style = pickStyle(line.text, words.length);
			element.className = `lv-line lv-style-${style.name}`;
			// The words (or letters) come in over most of the line's time, in proportion to their length.
			const spread = Math.min(seconds * 0.7, 0.35 * words.length + 0.4);
			const letters = line.text.replace(/ /g, "").length || 1;
			const longest = words.reduce((best, word) => (word.replace(/\W/g, "").length > best.replace(/\W/g, "").length ? word : best), "");
			let before = 0;
			words.forEach((word, w) => {
				const span = document.createElement("span");
				span.className = "lv-word" + (word === longest && words.length > 2 ? " lv-key" : "");
				span.style.setProperty("--delay", `${(before / letters) * spread}s`);
				span.style.setProperty("--i", w);
				if (style.by === "letter") {
					[...word].forEach((char, c) => {
						const letter = document.createElement("span");
						letter.className = "lv-letter";
						letter.textContent = char;
						letter.style.setProperty("--delay", `${((before + c) / letters) * spread}s`);
						letter.style.setProperty("--c", c + w * 3);
						span.append(letter);
					});
				} else {
					span.textContent = word;
				}
				before += word.length;
				element.append(span, " ");
			});
		}
		if (shown) {   // the line before flies out
			const old = shown;
			old.classList.add("leaving");
			setTimeout(() => old.remove(), 700);
		}
		colour = (colour + 1) % LYRIC_PALETTES.length;
		const [background, text, accent] = LYRIC_PALETTES[colour];
		slide.style.setProperty("--lv-bg", background);
		slide.style.setProperty("--lv-fg", text);
		slide.style.setProperty("--lv-accent", accent);
		stage.append(element);
		fitLyricLine(element, stage);
		shown = element;
	};

	const follow = () => {
		if (!document.contains(stage)) return clearInterval(timer);   // the slide is gone
		const seconds = start + (playing ? (performance.now() - shownAt) / 1000 : 0);
		if (bar && total) bar.style.width = `${Math.min(100, (seconds / total) * 100)}%`;
		const index = lines.findLastIndex((line) => line.time <= seconds + 0.1);   // a little early: the words take a moment to pop in
		if (index === current) return;
		current = index;
		show(index);
	};
	const timer = setInterval(follow, 100);
	follow();
	document.fonts?.ready.then(() => shown && fitLyricLine(shown, stage));   // measured again in the real fonts
}

// The biggest font size at which the line fits the stage; a stacked line sizes each word to the width.
// Measured without the animations: a word that starts at twice its size would count as too wide.
function fitLyricLine(line, stage) {
	line.classList.add("lv-measuring");
	measureLyricLine(line, stage);
	line.offsetWidth;   // (applies the sizes before the animations come back)
	line.classList.remove("lv-measuring");
}

function measureLyricLine(line, stage) {
	const width = stage.clientWidth, height = stage.clientHeight;
	if (line.classList.contains("lv-style-stack")) {
		const words = [...line.querySelectorAll(".lv-word")];
		for (const word of words) {
			word.style.fontSize = "10vh";
			word.style.fontSize = `${Math.min(height / words.length / 0.9, (10 * window.innerHeight / 100) * (width * 0.92) / word.scrollWidth)}px`;
		}
		for (let tries = 0; line.scrollHeight > height && tries < 15; tries++) {   // too tall together: all a little smaller
			for (const word of words) word.style.fontSize = `${parseFloat(word.style.fontSize) * 0.92}px`;
		}
		return;
	}
	let size = Math.min(height * 0.42, width * 0.13);
	line.style.fontSize = `${size}px`;
	while ((line.scrollWidth > width || line.scrollHeight > height) && size > 20) {
		size *= 0.92;
		line.style.fontSize = `${size}px`;
	}
}

function mapPin(latlng, kind) {
	const icon = L.divIcon({ className: `map-pin map-pin-${kind}`, iconSize: [26, 26], iconAnchor: [13, 13] });
	return L.marker(latlng, { icon, interactive: false, keyboard: false });
}

function fieldValue(field) {
	return field.matches("input") ? field.value : field.dataset.value || "";
}

function fieldValues(slide) {
	return [...slide.querySelectorAll("[data-field]")].map(fieldValue);
}

function fieldChanged(field) {
	const slide = field.closest("[data-interactive]") || document;
	for (const output of slide.querySelectorAll(`[data-field-output="${field.dataset.field}"]`)) {
		output.textContent = fieldValue(field);
	}
	const ready = [...slide.querySelectorAll("[data-field]")].every((other) => fieldValue(other) !== "");
	slide.querySelectorAll("[data-needs-fields]").forEach((button) => { button.disabled = !ready; });
}

document.addEventListener("click", (event) => {
	const nudge = event.target.closest("[data-nudge]");
	const slide = nudge?.closest("[data-interactive]");
	const input = slide?.querySelector(`input[data-field="${nudge.dataset.nudge}"]`);
	if (!input) return;
	input.value = Number(input.value) + Number(nudge.dataset.by);   // the range keeps it within min..max
	fieldChanged(input);
});

const MATRIX_GLYPHS = "アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワン0123456789ΣΔΨπ∫{}<>=+";
const randomGlyph = () => MATRIX_GLYPHS[Math.floor(Math.random() * MATRIX_GLYPHS.length)];

function setupMatrix(canvas) {
	// Columns of glyphs falling each at their own speed: a bright head that turns green as it moves on,
	// leaving a trail that fades. One glyph per cell (the cell is cleared first), so glyphs never stack.
	const ctx = canvas.getContext("2d");
	const words = (canvas.dataset.words || "").split(" ").filter(Boolean).map((word) => word.replaceAll("|", " "));
	let size = 0, drops = [];
	const speed = () => 0.18 + Math.random() * 0.35;   // cells per frame
	const resize = () => {
		canvas.width = canvas.clientWidth * devicePixelRatio;
		canvas.height = canvas.clientHeight * devicePixelRatio;
		size = Math.max(8, Math.round(canvas.height / 40));
		drops = Array.from({ length: Math.ceil(canvas.width / size) }, () => ({ y: -Math.random() * 25, speed: speed(), word: null, i: 0, last: null }));
		ctx.fillStyle = "#000";
		ctx.fillRect(0, 0, canvas.width, canvas.height);
	};
	resize();
	const frame = () => {
		if (!document.contains(canvas)) return;   // the slide is gone
		if (canvas.width !== canvas.clientWidth * devicePixelRatio) resize();
		ctx.fillStyle = "rgba(0, 0, 0, 0.05)";
		ctx.fillRect(0, 0, canvas.width, canvas.height);
		ctx.font = `${size}px Consolas, "DejaVu Sans Mono", monospace`;
		ctx.textAlign = "center";
		drops.forEach((drop, x) => {
			const before = Math.floor(drop.y);
			drop.y += drop.speed;
			const row = Math.floor(drop.y);
			if (row === before) return;
			let glyph = randomGlyph();
			if (drop.word) {
				glyph = drop.word[drop.i++] || glyph;
				if (drop.i >= drop.word.length) drop.word = null;
			}
			const draw = (text, y, colour) => {
				ctx.fillStyle = "#000";
				ctx.fillRect(x * size, (y - 1) * size, size, size * 1.15);
				ctx.fillStyle = colour;
				ctx.fillText(text, x * size + size / 2, y * size - size * 0.15);
			};
			if (drop.last) draw(drop.last, row - 1, "#00ff41");   // the previous head settles into green
			draw(glyph, row, "#c8ffd4");                          // the new head, bright
			drop.last = glyph;
			if (drop.y * size > canvas.height && Math.random() > 0.975) {   // past the bottom: again from the top
				Object.assign(drop, { y: 0, speed: speed(), i: 0, last: null,
					word: words.length && Math.random() < 0.08 ? words[Math.floor(Math.random() * words.length)] : null });
			}
		});
		requestAnimationFrame(frame);
	};
	requestAnimationFrame(frame);
}

function setupDecode(element) {
	const text = element.dataset.decode;
	const begin = performance.now() + Number(element.dataset.decodeWait || 0) * 1000;
	const settleAt = (i) => 250 + i * 140;   // ms after the start, per letter
	element.innerHTML = "&nbsp;";
	const frame = (now) => {
		if (!document.contains(element)) return;
		const t = now - begin;
		if (t >= 0) {
			element.replaceChildren(...[...text].map((letter, i) => {
				const span = document.createElement("span");
				span.textContent = t >= settleAt(i) ? letter : randomGlyph();
				span.classList.toggle("settled", t >= settleAt(i));
				return span;
			}));
		}
		if (t < settleAt(text.length)) requestAnimationFrame(frame);
	};
	requestAnimationFrame(frame);
}

async function setupTerminal(element) {
	const lines = [...element.children].map((child) => ({ command: child.dataset.command, answer: child.innerHTML }));
	const prompt = element.dataset.prompt || "$";
	element.replaceChildren();
	const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
	const promptLine = () => {
		const line = document.createElement("div");
		const label = document.createElement("span");
		label.className = "terminal-prompt";
		label.textContent = prompt + " ";
		const cursor = document.createElement("span");
		cursor.className = "terminal-cursor";
		line.append(label, cursor);
		element.append(line);
		return cursor;
	};
	await wait(Number(element.dataset.terminalWait || 0) * 1000);
	for (const { command, answer } of lines) {
		if (!document.contains(element)) return;   // the slide is gone
		const cursor = promptLine();
		for (const ch of command) {
			cursor.before(ch);
			await wait(45 + Math.random() * 60);
		}
		await wait(350);
		cursor.remove();
		const out = document.createElement("div");
		out.className = "terminal-answer";
		out.innerHTML = answer;
		element.append(out);
		await wait(900);
	}
	promptLine();
	element.closest(".slide")?.classList.add("typed");
}

// data-three="<scene>" on a <canvas> (the scene it starts with): a Three.js scene (static/vendor/three, loaded the first time one is needed)
// for finding out what the TV PC's graphics can do (providers/three.py). [data-three-stats] next to it shows the frames per
// second (now, the average and the slowest half second so far), what is drawn and which graphics chip does it. The renderer is
// freed once the slide is gone, so the browser doesn't run out of WebGL contexts.
let threeLoading = null;

function loadThree() {
	threeLoading ??= new Promise((resolve, reject) => {
		if (window.THREE) return resolve(window.THREE);
		loadScript("/static/vendor/three/three.min.js").then(() => resolve(window.THREE),
			() => { threeLoading = null; reject(new Error("three.js did not load")); });
	});
	return threeLoading;
}

// In the emulator (tools/emulator.py) there is no server behind the page, only its fetch(): the script is fetched
// and run from a blob: URL there.
async function loadScript(src) {
	let url = src;
	if (window.emulator) {
		const response = await fetch(src.split("?")[0]);
		if (!response.ok) throw new Error(`${src} did not load`);
		url = URL.createObjectURL(new Blob([await response.text()], { type: "text/javascript" }));
	}
	await new Promise((resolve, reject) => {
		const script = document.createElement("script");
		script.src = url;
		script.onload = resolve;
		script.onerror = () => reject(new Error(`${src} did not load`));
		document.head.append(script);
	});
}

// The benchmark slide (providers/three.py, ThreeBenchmarkProvider): [data-tb-start] runs the tests, shows what came out
// in [data-tb-results] and has the server save it (POST /api/benchmark) in benchmarks/, to be committed.
function setupThreeBenchmark(root) {
	const start = root.querySelector("[data-tb-start]");
	const status = root.querySelector("[data-tb-status]");
	const results = root.querySelector("[data-tb-results]");
	const escape = (text) => String(text).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]);
	start.addEventListener("click", async () => {
		start.disabled = true;
		root.classList.add("running");
		root.classList.remove("done");
		results.innerHTML = "";
		try {
			const THREE = await loadThree();
			await loadScript(`/static/three_benchmark.js?${Date.now()}`);   // every time: a page that has been open for days may hold an old version
			const run = await window.threeBenchmark(root, THREE);
			results.innerHTML = `<h2>${escape(run.gpu)} &middot; ${escape(run.screen)}</h2>` + run.tests.map((test) =>
				`<p><b>${escape(test.title)}</b>${test.best !== undefined ? ": " + escape(test.best || "") : ""}</p>`).join("");
			status.textContent = "Done. Saving...";
			const response = await fetch("/api/benchmark", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(run) });
			const saved = await response.json();
			if (saved.error) throw new Error(saved.error);
			status.textContent = `Saved as ${saved.json} and ${saved.markdown}. Commit them (git add benchmarks && git commit).`;
		} catch (error) {
			console.error(error);
			status.textContent = document.contains(root) ? `Failed: ${error.message}` : "";
		}
		root.classList.remove("running");
		root.classList.add("done");
		start.disabled = false;
		start.textContent = "Run again";
	});
}

async function setupThree(canvas) {
	const slide = canvas.closest(".three-slide");
	const stats = slide.querySelector("[data-three-stats]");
	const say = (html) => { stats.innerHTML = html; };
	let THREE;
	try {
		THREE = await loadThree();
	} catch (error) {
		return say("<b>Three.js did not load</b>");
	}
	if (!document.contains(canvas)) return;
	let renderer;
	try {
		renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: "high-performance" });
	} catch (error) {
		return say("<b>No WebGL here</b>");
	}
	const gl = renderer.getContext();
	const debug = gl.getExtension("WEBGL_debug_renderer_info");
	const chip = debug ? gl.getParameter(debug.UNMASKED_RENDERER_WEBGL) : "unknown graphics";
	const sceneButtons = [...slide.querySelectorAll("[data-three-scene]")];
	const scaleButtons = [...slide.querySelectorAll("[data-three-scale]")];

	let scene, camera, update, name, scale = 1, run = 0;
	const start = (newName, newScale) => {
		const mine = ++run;   // the loop of the scene before stops by itself
		if (scene) scene.traverse((o) => { o.geometry?.dispose(); [o.material].flat().forEach((m) => m?.dispose()); });
		name = newName;
		scale = newScale;
		renderer.shadowMap.enabled = false;
		renderer.setPixelRatio(devicePixelRatio * scale);   // the screen's real pixels (a TV PC with display scaling has a pixel ratio above 1)
		renderer.setSize(canvas.clientWidth, canvas.clientHeight, false);
		scene = new THREE.Scene();
		camera = new THREE.PerspectiveCamera(50, canvas.clientWidth / canvas.clientHeight, 0.1, 200);
		update = THREE_SCENES[name](THREE, renderer, scene, camera);
		sceneButtons.forEach((b) => b.classList.toggle("selected", b.dataset.threeScene === name));
		scaleButtons.forEach((b) => b.classList.toggle("selected", Number(b.dataset.threeScale) === scale));
		const label = slide.querySelector(`[data-three-scene="${name}"]`);
		slide.querySelector(".three-title").innerHTML = label ? `<b>${label.textContent}</b> <span>${label.dataset.about}</span>` : "";
		measure(mine);
	};

	const measure = (mine) => {
		const started = performance.now();
		let last = started, windowStart = started, frames = 0, total = 0, slowest = Infinity;
		const frame = (now) => {
			if (mine !== run) return;   // another scene or resolution took over
			if (!document.contains(canvas)) {   // the slide is gone
				renderer.dispose();
				renderer.forceContextLoss();
				return;
			}
			requestAnimationFrame(frame);
			update((now - started) / 1000, (now - last) / 1000);
			renderer.render(scene, camera);
			last = now;
			frames++;
			total++;
			if (now - windowStart >= 500) {
				const fps = frames * 1000 / (now - windowStart);
				if (now - started > 1500) slowest = Math.min(slowest, fps);   // not the first moments: the shaders compile then
				const average = total * 1000 / (now - started);
				const verdict = average >= 50 ? ["smooth", "good"] : average >= 28 ? ["so-so", "ok"] : ["too slow", "bad"];
				const info = renderer.info.render;
				say(`<span class="three-fps">${Math.round(fps)}<small> fps</small></span>`
					+ `<span class="three-verdict ${verdict[1]}">${verdict[0]}</span>`
					+ `<span>average ${Math.round(average)} &middot; slowest ${slowest === Infinity ? "..." : Math.round(slowest)}</span>`
					+ `<span>${info.calls} draw calls &middot; ${info.triangles.toLocaleString("en")} triangles</span>`
					+ `<span>drawn at ${canvas.width} &times; ${canvas.height}</span>`
					+ `<span class="three-chip">${chip}</span>`);
				frames = 0;
				windowStart = now;
			}
		};
		requestAnimationFrame(frame);
	};

	sceneButtons.forEach((b) => b.addEventListener("click", () => start(b.dataset.threeScene, scale)));
	scaleButtons.forEach((b) => b.addEventListener("click", () => start(name, Number(b.dataset.threeScale))));
	// S: the next scene, R: the next resolution (clicks, so the slideshow stays on this slide like for a tap)
	const cycle = (buttons) => buttons[(buttons.findIndex((b) => b.classList.contains("selected")) + 1) % buttons.length].click();
	const keys = (event) => {
		if (!document.contains(canvas)) return document.removeEventListener("keydown", keys);
		if (event.ctrlKey || event.altKey || event.metaKey) return;
		if (event.key === "s") cycle(sceneButtons);
		else if (event.key === "r") cycle(scaleButtons);
	};
	document.addEventListener("keydown", keys);
	start(canvas.dataset.three, 1);
}

// A grid of `side` x `rows` instanced spheres in rainbow colours, rippling like a wave: { mesh, wave(seconds) }.
function waveSpheres(THREE, scene, side, rows, geometry, material) {
	const mesh = new THREE.InstancedMesh(geometry, material, side * rows);
	mesh.receiveShadow = true;
	const colour = new THREE.Color(), matrix = new THREE.Matrix4();
	for (let i = 0; i < side * rows; i++) mesh.setColorAt(i, colour.setHSL(0.55 + (i % side) / side * 0.4, 0.8, 0.55));
	scene.add(mesh);
	const wave = (t) => {
		for (let i = 0; i < side * rows; i++) {
			const x = (i % side) - side / 2, z = Math.floor(i / side) - rows / 2;
			matrix.makeTranslation(x * 0.75, Math.sin(x * 0.35 + t * 1.6) * Math.cos(z * 0.3 + t * 1.2) * 2.2, z * 0.75);
			mesh.setMatrixAt(i, matrix);
		}
		mesh.instanceMatrix.needsUpdate = true;
	};
	return { mesh, wave };
}

// Each scene sets up `scene` and `camera` and returns update(seconds, delta), called before every frame.
const THREE_SCENES = {
	// Simple: a lit, spinning knot and a cube. Two objects, one light.
	simple(THREE, renderer, scene, camera) {
		scene.background = new THREE.Color(0x0b1b3a);
		camera.position.set(0, 0, 7);
		scene.add(new THREE.AmbientLight(0xffffff, 0.5));
		const sun = new THREE.DirectionalLight(0xffffff, 2.5);
		sun.position.set(3, 4, 5);
		scene.add(sun);
		const knot = new THREE.Mesh(new THREE.TorusKnotGeometry(1.4, 0.45, 128, 16), new THREE.MeshStandardMaterial({ color: 0xe0314b, roughness: 0.35, metalness: 0.2 }));
		knot.position.x = -1.6;
		const cube = new THREE.Mesh(new THREE.BoxGeometry(1.6, 1.6, 1.6), new THREE.MeshStandardMaterial({ color: 0xf5b800, roughness: 0.5 }));
		cube.position.x = 2.8;
		scene.add(knot, cube);
		return (t) => {
			knot.rotation.set(t * 0.6, t * 0.9, 0);
			cube.rotation.set(t * 0.7, t * 0.5, t * 0.3);
		};
	},

	// Medium: 400 separate meshes (400 draw calls) orbiting in fog under three coloured lights, with a reflective ground.
	medium(THREE, renderer, scene, camera) {
		scene.background = new THREE.Color(0x120a24);
		scene.fog = new THREE.Fog(0x120a24, 12, 38);
		camera.position.set(0, 7, 22);
		scene.add(new THREE.AmbientLight(0x404060, 1));
		const lights = [0xff3366, 0x33ccff, 0xffcc33].map((colour) => {
			const light = new THREE.PointLight(colour, 900, 40);
			scene.add(light);
			return light;
		});
		const shapes = [new THREE.IcosahedronGeometry(0.6, 1), new THREE.BoxGeometry(0.9, 0.9, 0.9), new THREE.TorusGeometry(0.5, 0.2, 12, 24), new THREE.ConeGeometry(0.5, 1.1, 16)];
		const things = [];
		for (let i = 0; i < 400; i++) {
			const material = new THREE.MeshStandardMaterial({ color: new THREE.Color().setHSL(i / 400, 0.75, 0.55), roughness: 0.3, metalness: 0.4 });
			const mesh = new THREE.Mesh(shapes[i % shapes.length], material);
			things.push({ mesh, radius: 3 + (i % 20) * 0.9, phase: i * 0.37, height: ((i * 7) % 11) - 3, speed: 0.15 + (i % 7) * 0.03 });
			scene.add(mesh);
		}
		const ground = new THREE.Mesh(new THREE.PlaneGeometry(80, 80), new THREE.MeshStandardMaterial({ color: 0x1b1235, roughness: 0.2, metalness: 0.6 }));
		ground.rotation.x = -Math.PI / 2;
		ground.position.y = -5;
		scene.add(ground);
		return (t) => {
			for (const o of things) {
				const a = o.phase + t * o.speed;
				o.mesh.position.set(Math.cos(a) * o.radius, o.height + Math.sin(a * 2) * 0.8, Math.sin(a) * o.radius);
				o.mesh.rotation.set(t * 0.8 + o.phase, t * 0.5, 0);
			}
			lights.forEach((light, i) => light.position.set(Math.cos(t * 0.5 + i * 2.1) * 9, 4 + i, Math.sin(t * 0.5 + i * 2.1) * 9));
			camera.position.x = Math.sin(t * 0.2) * 6;
			camera.lookAt(0, 0, 0);
		};
	},

	// Heavy: 1,000 lit spheres (about 340,000 triangles), two lights, no shadows: a step up from medium that isolates plain geometry.
	heavy(THREE, renderer, scene, camera) {
		scene.background = new THREE.Color(0x0a1020);
		camera.position.set(0, 10, 28);
		scene.add(new THREE.HemisphereLight(0x88aaff, 0x221133, 0.9));
		const sun = new THREE.DirectionalLight(0xffffff, 2.5);
		sun.position.set(10, 20, 10);
		scene.add(sun);
		const spheres = waveSpheres(THREE, scene, 40, 25, new THREE.SphereGeometry(0.4, 16, 12), new THREE.MeshStandardMaterial({ roughness: 0.3, metalness: 0.3 }));
		return (t) => {
			spheres.wave(t);
			camera.position.x = Math.sin(t * 0.15) * 10;
			camera.lookAt(0, 0, 0);
		};
	},

	// Shadows: only 300 spheres (about 100,000 triangles) but a 2048 shadow map: shows what the shadows cost by themselves.
	shadows(THREE, renderer, scene, camera) {
		scene.background = new THREE.Color(0x0a1020);
		camera.position.set(0, 12, 26);
		renderer.shadowMap.enabled = true;
		renderer.shadowMap.type = THREE.PCFSoftShadowMap;
		scene.add(new THREE.HemisphereLight(0x88aaff, 0x221133, 0.7));
		const sun = new THREE.DirectionalLight(0xfff0d0, 3);
		sun.position.set(12, 24, 8);
		sun.castShadow = true;
		sun.shadow.mapSize.set(2048, 2048);
		Object.assign(sun.shadow.camera, { left: -20, right: 20, top: 20, bottom: -20, near: 1, far: 70 });
		scene.add(sun);
		const floor = new THREE.Mesh(new THREE.PlaneGeometry(60, 60), new THREE.MeshStandardMaterial({ color: 0x223355, roughness: 0.8 }));
		floor.rotation.x = -Math.PI / 2;
		floor.position.y = -3;
		floor.receiveShadow = true;
		scene.add(floor);
		const spheres = waveSpheres(THREE, scene, 30, 10, new THREE.SphereGeometry(0.5, 20, 14), new THREE.MeshStandardMaterial({ roughness: 0.4 }));
		spheres.mesh.castShadow = true;
		return (t) => {
			spheres.wave(t);
			camera.position.x = Math.sin(t * 0.15) * 10;
			camera.lookAt(0, 0, 0);
		};
	},

	// Triangles: the same 6,000 spheres as "complex" (about 4 million triangles) but unlit and without shadows: raw triangle throughput.
	triangles(THREE, renderer, scene, camera) {
		scene.background = new THREE.Color(0x02060f);
		camera.position.set(0, 14, 34);
		const spheres = waveSpheres(THREE, scene, 80, 75, new THREE.SphereGeometry(0.28, 24, 16), new THREE.MeshBasicMaterial());
		return (t) => {
			spheres.wave(t);
			camera.position.x = Math.sin(t * 0.15) * 14;
			camera.lookAt(0, 4, 0);
		};
	},

	// Overdraw: 60 big see-through glowing layers on top of each other and almost nothing else: how many pixels it can blend (fill rate).
	overdraw(THREE, renderer, scene, camera) {
		scene.background = new THREE.Color(0x000000);
		camera.position.set(0, 0, 14);
		const layers = [];
		for (let i = 0; i < 60; i++) {
			const layer = new THREE.Mesh(new THREE.PlaneGeometry(40, 24), new THREE.MeshBasicMaterial({ color: new THREE.Color().setHSL(i / 60, 0.8, 0.5), transparent: true, opacity: 0.08, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide }));
			layer.position.z = -i * 0.3;
			layers.push(layer);
			scene.add(layer);
		}
		return (t) => layers.forEach((layer, i) => { layer.rotation.z = Math.sin(t * 0.3 + i * 0.1) * 0.5; layer.scale.setScalar(1 + 0.2 * Math.sin(t * 0.5 + i * 0.2)); });
	},

	// Complex: 6,000 instanced spheres rippling like a wave (about 4 million triangles, every instance moved by the CPU each frame),
	// 30,000 glowing points, a shiny high-detail knot, a shadow-casting light with a 2048 shadow map, and fog.
	complex(THREE, renderer, scene, camera) {
		scene.background = new THREE.Color(0x02060f);
		scene.fog = new THREE.FogExp2(0x02060f, 0.018);
		camera.position.set(0, 14, 34);
		renderer.shadowMap.enabled = true;
		renderer.shadowMap.type = THREE.PCFSoftShadowMap;
		scene.add(new THREE.HemisphereLight(0x88aaff, 0x221133, 0.8));
		const sun = new THREE.DirectionalLight(0xfff0d0, 3);
		sun.position.set(20, 30, 10);
		sun.castShadow = true;
		sun.shadow.mapSize.set(2048, 2048);
		Object.assign(sun.shadow.camera, { left: -30, right: 30, top: 30, bottom: -30, near: 1, far: 90 });
		scene.add(sun);

		const side = 80, count = side * 75;
		const spheres = new THREE.InstancedMesh(new THREE.SphereGeometry(0.28, 24, 16), new THREE.MeshStandardMaterial({ roughness: 0.25, metalness: 0.3 }), count);
		spheres.castShadow = spheres.receiveShadow = true;
		const colour = new THREE.Color();
		for (let i = 0; i < count; i++) spheres.setColorAt(i, colour.setHSL(0.55 + (i % side) / side * 0.4, 0.8, 0.55));
		scene.add(spheres);
		const matrix = new THREE.Matrix4();

		const points = 30000, positions = new Float32Array(points * 3);
		for (let i = 0; i < points; i++) {
			const r = 18 + Math.random() * 40, a = Math.random() * Math.PI * 2, b = Math.random() * Math.PI - Math.PI / 2;
			positions.set([Math.cos(a) * Math.cos(b) * r, Math.sin(b) * r * 0.6 + 10, Math.sin(a) * Math.cos(b) * r], i * 3);
		}
		const cloud = new THREE.BufferGeometry();
		cloud.setAttribute("position", new THREE.BufferAttribute(positions, 3));
		const dust = new THREE.Points(cloud, new THREE.PointsMaterial({ color: 0x9fd0ff, size: 0.18, transparent: true, opacity: 0.8, depthWrite: false, blending: THREE.AdditiveBlending }));
		scene.add(dust);

		const knot = new THREE.Mesh(new THREE.TorusKnotGeometry(3.2, 1, 400, 64), new THREE.MeshPhysicalMaterial({ color: 0xffb400, metalness: 1, roughness: 0.15, clearcoat: 1 }));
		knot.position.y = 8;
		knot.castShadow = true;
		scene.add(knot);
		return (t) => {
			for (let i = 0; i < count; i++) {
				const x = (i % side) - side / 2, z = Math.floor(i / side) - 37;
				const y = Math.sin(x * 0.35 + t * 1.6) * Math.cos(z * 0.3 + t * 1.2) * 2.2;
				matrix.makeTranslation(x * 0.75, y, z * 0.75);
				spheres.setMatrixAt(i, matrix);
			}
			spheres.instanceMatrix.needsUpdate = true;
			dust.rotation.y = t * 0.03;
			knot.rotation.set(t * 0.4, t * 0.6, 0);
			camera.position.x = Math.sin(t * 0.15) * 14;
			camera.lookAt(0, 4, 0);
		};
	},
};
