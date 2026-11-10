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
// - data-matrix: Matrix code rain on a <canvas>; now and then a column spells one of data-words
//   (separated by spaces; | for a space inside a word). The Compucie slide.
// - data-decode: a title that decodes: each letter of data-decode flickers through random glyphs and
//   settles, left to right, starting after data-decode-wait seconds.
// - data-terminal: a terminal session that types itself after data-terminal-wait seconds: each child's
//   data-command is typed after data-prompt, then the child (its answer) appears. When it's done the
//   slide gets .typed (e.g. to show what comes after).
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
	const qr = qrcode(0, "M");   // 0: as small as the link allows; M: still readable when a bit dirty
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
