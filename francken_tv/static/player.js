// Plays the slides the server sends, one after another.
// What is shown, and for how long, is decided in Python (francken_tv/scheduler.py);
// this file only loads each slide, fades it in, and waits.
//
// Keys: right/down = next, left/up = previous, space = pause, m = read quotes aloud on/off.
// Interactive slides (the puzzle): clicking pauses the slideshow there; see "Interactive slides" below.
// Messages from the server (e.g. Ctrl+M / Ctrl+R in the terminal) appear in the corner.

const layers = [document.getElementById("layer-a"), document.getElementById("layer-b")];
const toast = document.getElementById("toast");
let front = 0;
let nextTimer = null;
let refreshTimer = null;
let paused = false;
let current = null;
const history = [];      // recently shown slides, for the left arrow key
let historyIndex = -1;
let toastTimer = null;
let lastNoticeId = null;
let interacting = false;   // someone is playing an interactive slide
let idleTimer = null;
let takeoverTimer = null;
const IDLE_SECONDS = 60;   // continue the slideshow after this long without clicks
let showCount = 0;       // every slide change gets a number; only the newest may touch the screen

async function getJson(url, options) {
	const response = await fetch(url, options);
	if (!response.ok) throw new Error(`${url}: ${response.status}`);
	return response.json();
}

async function show(slide, { canRefresh = true } = {}) {
	const mine = ++showCount;
	stopInteracting();
	clearTimeout(nextTimer);
	clearInterval(refreshTimer);
	const back = layers[1 - front];
	back.innerHTML = slide.html;
	// Wait until the images are decoded, so slides never appear half-loaded.
	const images = [...back.querySelectorAll("img")];
	await Promise.all(images.map((img) => img.decode().catch(() => {})));
	if (mine !== showCount) return;   // skipped again while loading: the newer change takes over
	if (images.some((img) => img.naturalWidth === 0)) {
		// A missing or broken image would show as a black screen: skip this slide instead.
		console.warn("Skipping a slide with a broken image:", images.map((img) => img.src));
		back.innerHTML = "";
		nextTimer = setTimeout(next, 500);
		return;
	}
	const old = layers[front];
	back.classList.add("visible");
	old.classList.remove("visible");
	front = 1 - front;
	// Empty the old layer after the fade, unless a newer slide is already loading into it.
	setTimeout(() => { if (mine === showCount) old.innerHTML = ""; }, 1000);

	current = slide;
	if (slide.refresh && canRefresh) refreshTimer = setInterval(refresh, slide.refresh * 1000);
	if (!paused) nextTimer = setTimeout(next, slide.seconds * 1000);
}

async function next() {
	if (historyIndex < history.length - 1) {   // after going back, move forward through history first
		historyIndex += 1;
		return show(history[historyIndex], { canRefresh: false });
	}
	try {
		const slide = await getJson("/api/next");
		history.push(slide);
		if (history.length > 30) history.shift();
		historyIndex = history.length - 1;
		await show(slide);
	} catch (error) {
		console.error(error);
		nextTimer = setTimeout(next, 5000);   // server not reachable: keep the current slide, try again
	}
}

function previous() {
	if (historyIndex <= 0) return;
	historyIndex -= 1;
	show(history[historyIndex], { canRefresh: false });
}

// Redraw the current slide (e.g. the ticking countdown). If the slide's data-state is unchanged,
// only elements marked data-live="..." are updated, so animations keep running smoothly.
async function refresh() {
	try {
		const started = showCount;
		const slide = await getJson("/api/current");
		if (started !== showCount) return;   // the slide changed meanwhile
		const layer = layers[front];
		const fresh = document.createElement("div");
		fresh.innerHTML = slide.html;
		const oldState = layer.querySelector("[data-state]")?.dataset.state;
		const newState = fresh.querySelector("[data-state]")?.dataset.state;
		if (oldState === undefined || oldState !== newState) {
			layer.innerHTML = slide.html;
			return;
		}
		for (const element of fresh.querySelectorAll("[data-live]")) {
			const target = layer.querySelector(`[data-live="${element.dataset.live}"]`);
			if (!target) continue;
			for (const attribute of element.attributes) target.setAttribute(attribute.name, attribute.value);
			if (element.children.length === 0) target.textContent = element.textContent;
		}
	} catch (error) {
		console.error(error);
	}
}

function showToast(text) {
	toast.textContent = text;
	toast.classList.add("visible");
	clearTimeout(toastTimer);
	toastTimer = setTimeout(() => toast.classList.remove("visible"), 3000);
}

async function checkNotice() {
	try {
		const notice = await getJson("/api/notice");
		if (lastNoticeId !== null && notice.id !== lastNoticeId) showToast(notice.text);
		lastNoticeId = notice.id;   // the first check only remembers, so old messages don't pop up on load
	} catch (error) {
		// server not reachable; next() already handles that
	}
}

// ---- Interactive slides -----------------------------------------------------------------
// A slide with data-interactive pauses the slideshow when clicked. Elements with data-toggle
// can be selected (at most data-max-selected); buttons with data-action are sent to the
// provider's action() in Python, which returns the redrawn slide and an optional message.

document.addEventListener("click", async (event) => {
	const slide = layers[front].querySelector("[data-interactive]");
	if (!slide || !slide.contains(event.target)) return;
	keepPaused(IDLE_SECONDS);
	const toggle = event.target.closest("[data-toggle]");
	const action = event.target.closest("[data-action]");
	const selected = () => [...slide.querySelectorAll("[data-toggle].selected")];
	if (toggle) {
		const max = parseInt(slide.dataset.maxSelected || "1000", 10);
		if (toggle.classList.contains("selected") || selected().length < max) toggle.classList.toggle("selected");
	} else if (action && action.dataset.action === "deselect") {
		selected().forEach((element) => element.classList.remove("selected"));
	} else if (action) {
		const result = await getJson("/api/action", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({
				provider: slide.dataset.provider,
				action: action.dataset.action,
				values: selected().map((element) => element.dataset.value),
			}),
		});
		if (result.html) {
			const effect = new DOMParser().parseFromString(result.html, "text/html").querySelector("[data-effect]");
			if (effect && effects[effect.dataset.effect]) await effects[effect.dataset.effect](slide);
			layers[front].innerHTML = result.html;
			const resumeAfter = layers[front].querySelector("[data-resume-after]");
			if (resumeAfter) keepPaused(parseFloat(resumeAfter.dataset.resumeAfter));   // e.g. game over
		}
		if (result.message) showToast(result.message);
	}
});

// Animations that play on the current slide before the redrawn one replaces it.
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const effects = {
	// Connections, like the NYT page: the four tiles hop one after another, then swap into the
	// top row (the server swaps the words the same way), which then becomes the coloured bar.
	"solve-group": async (slide) => {
		const tiles = [...slide.querySelectorAll(".connections-tile")];
		const chosen = tiles.filter((tile) => tile.classList.contains("selected"));
		chosen.forEach((tile, i) => {
			tile.classList.remove("shake");
			tile.style.animationDelay = `${i * 0.1}s`;
			tile.classList.add("hop");
		});
		await wait(350 + chosen.length * 100);

		const topRow = tiles.slice(0, 4);
		const movingUp = chosen.filter((tile) => !topRow.includes(tile));
		const makingRoom = topRow.filter((tile) => !chosen.includes(tile));
		chosen.forEach((tile) => tile.classList.remove("hop"));
		movingUp.forEach((up, i) => {
			const down = makingRoom[i];
			const a = up.getBoundingClientRect();
			const b = down.getBoundingClientRect();
			for (const [tile, x, y] of [[up, b.x - a.x, b.y - a.y], [down, a.x - b.x, a.y - b.y]]) {
				tile.classList.add("moving");
				tile.style.transform = `translate(${x}px, ${y}px)`;
			}
		});
		await wait(movingUp.length ? 550 : 0);
	},
};

function keepPaused(seconds) {
	if (!interacting) {
		interacting = true;
		clearTimeout(nextTimer);
		showToast("Paused: the slideshow continues after a minute without clicks");
		takeoverTimer = setInterval(checkTakeover, 5000);
	}
	clearTimeout(idleTimer);
	idleTimer = setTimeout(next, seconds * 1000);
}

function stopInteracting() {
	interacting = false;
	clearTimeout(idleTimer);
	clearInterval(takeoverTimer);
}

async function checkTakeover() {   // bieruur interrupts even a paused puzzle
	try {
		if ((await getJson("/api/takeover")).due) next();
	} catch (error) {
		console.error(error);
	}
}

// Show the mouse pointer while it moves; hide it again after 3 seconds.
let cursorTimer = null;
document.addEventListener("mousemove", () => {
	document.body.classList.add("show-cursor");
	clearTimeout(cursorTimer);
	cursorTimer = setTimeout(() => document.body.classList.remove("show-cursor"), 3000);
});

document.addEventListener("keydown", async (event) => {
	if (event.key === "ArrowRight" || event.key === "ArrowDown") {
		next();
	} else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
		previous();
	} else if (event.key === " ") {
		paused = !paused;
		showToast(paused ? "Paused" : "Playing");
		if (paused) clearTimeout(nextTimer);
		else if (current) nextTimer = setTimeout(next, current.seconds * 1000);
	} else if (event.key === "m") {
		await getJson("/api/narration", { method: "POST" });
		checkNotice();   // the server's confirmation shows up as a notice
	}
});

next();
checkNotice();
setInterval(checkNotice, 1000);
