// Plays the slides the server sends, one after another.
// What is shown, and for how long, is decided in Python (francken_tv/scheduler.py);
// this file only loads each slide, fades it in, and waits.
//
// Keys: right/down = next, left/up = previous, space = pause (or the slide's data-space-action,
// e.g. pausing the music on the Spotify slide), m = read quotes aloud on/off,
// number keys = jump to a slide type, e.g. 1 = Daily puzzles (see [shortcuts] in config.toml).
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
const IDLE_SECONDS = 240;   // continue the slideshow after this long without clicks (data-idle-seconds on a slide overrides it)
let showCount = 0;       // every slide change gets a number; only the newest may touch the screen
let loadedVersion = null;   // of style.css and player.js; when they change on disk, the page reloads

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
		return showAgain(history[historyIndex]);
	}
	try {
		const started = showCount;
		const slide = await getJson("/api/next");
		if (started !== showCount) return;   // another slide (e.g. a shortcut) was shown meanwhile
		// style.css or player.js was edited: reload, so the slides get the new styles (this skips one slide).
		if (loadedVersion !== null && slide.version !== loadedVersion) return location.reload();
		loadedVersion = slide.version;
		history.push(slide);
		if (history.length > 30) history.shift();
		historyIndex = history.length - 1;
		await show(slide);
	} catch (error) {
		console.error(error);
		nextTimer = setTimeout(next, 5000);   // server not reachable: keep the current slide, try again
	}
}

// A shortcut key: the server draws that slide type now. An interactive one (puzzles, Spotify)
// stays on screen like after a click, so people can use it.
async function jumpTo(key) {
	try {
		const response = await fetch(`/api/shortcut/${key}`);
		if (response.status === 404) return;   // not a shortcut
		if (!response.ok) throw new Error(`shortcut ${key}: ${response.status}`);
		const slide = await response.json();
		if (slide.message) return showToast(slide.message);
		history.splice(historyIndex + 1);   // jumping drops the slides ahead after going back
		history.push(slide);
		if (history.length > 30) history.shift();
		historyIndex = history.length - 1;
		await show(slide);
		const shown = interactiveSlide();
		if (shown) keepPaused(idleSeconds(shown));
	} catch (error) {
		console.error(error);
	}
}

function previous() {
	if (historyIndex <= 0) return;
	historyIndex -= 1;
	showAgain(history[historyIndex]);
}

// A slide from the history, drawn again by the server: it's up to date and keeps updating (e.g. the
// Spotify slide follows the music). Too long ago, or the server is unreachable: the copy we have, as is.
async function showAgain(slide) {
	try {
		return await show(await getJson(`/api/slide/${slide.id}`));
	} catch (error) {
		return show(slide, { canRefresh: false });
	}
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
// A slide with data-interactive pauses the slideshow when clicked or typed on.
// - data-toggle elements can be selected (at most data-max-selected), e.g. Connections tiles;
// - data-action buttons send the selected data-values (or their own data-value) to the provider's
//   action() in Python (or to another provider, with data-provider on the button);
// - data-input-cell elements are filled by typing (keyboard or data-key buttons, e.g. Wordle),
//   or a data-input-text element takes free text (e.g. Catfishing);
//   Enter sends the typed text as data-submit-action.
// action() returns the redrawn slide and an optional message.

document.addEventListener("click", async (event) => {
	const slide = interactiveSlide();
	if (!slide || !slide.contains(event.target)) return;
	event.target.closest("button")?.blur();   // so Space/Enter later don't press it again
	keepPaused(idleSeconds(slide));
	const toggle = event.target.closest("[data-toggle]");
	const action = event.target.closest("[data-action]");
	const key = event.target.closest("[data-key]");
	const selected = () => [...slide.querySelectorAll("[data-toggle].selected")];
	if (toggle) {
		const max = parseInt(slide.dataset.maxSelected || "1000", 10);
		if (toggle.classList.contains("selected") || selected().length < max) toggle.classList.toggle("selected");
	} else if (key) {
		typeKey(slide, key.dataset.key);
	} else if (action && action.dataset.action === "deselect") {
		selected().forEach((element) => element.classList.remove("selected"));
	} else if (action) {
		const values = action.dataset.value ? [action.dataset.value] : selected().map((element) => element.dataset.value);
		action.classList.add("busy");   // shows the tap was seen, until the answer is there (style.css)
		sendAction(slide, action.dataset.action, values, action.dataset.provider).finally(() => action.classList.remove("busy"));
	}
});

function interactiveSlide() {
	return layers[front].querySelector("[data-interactive]");
}

// Typing: a character, "SPACE", "ENTER" or "BACK".
function typeKey(slide, key) {
	const text = slide.querySelector("[data-input-text]");
	if (text) {   // free text
		if (key === "ENTER") sendAction(slide, slide.dataset.submitAction, [text.textContent]);
		else if (key === "BACK") text.textContent = text.textContent.slice(0, -1);
		else text.textContent += key === "SPACE" ? " " : key;
		return;
	}
	const cells = [...slide.querySelectorAll("[data-input-cell]")];
	if (key === "ENTER") {
		sendAction(slide, slide.dataset.submitAction, [cells.map((cell) => cell.textContent.trim()).join("")]);
	} else if (key === "BACK") {
		const last = cells.filter((cell) => cell.textContent.trim()).pop();
		if (last) { last.textContent = ""; last.classList.remove("filled"); }
	} else {
		const empty = cells.find((cell) => !cell.textContent.trim());
		if (empty) { empty.textContent = key; empty.classList.add("filled"); }
	}
}

async function sendAction(slide, action, values, provider = slide.dataset.provider) {
	const result = await getJson("/api/action", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ provider, action, values }),
	});
	let messageDelay = 0;
	if (result.html) {
		const fresh = new DOMParser().parseFromString(result.html, "text/html");
		const effect = fresh.querySelector("[data-effect]");
		if (effect && effects[effect.dataset.effect]) await effects[effect.dataset.effect](slide);
		messageDelay = parseInt(fresh.querySelector("[data-message-delay]")?.dataset.messageDelay || "0", 10);
		layers[front].innerHTML = result.html;
		const resumeAfter = layers[front].querySelector("[data-resume-after]");
		if (resumeAfter) keepPaused(parseFloat(resumeAfter.dataset.resumeAfter));   // e.g. game over
	} else if (current && current.refresh) {
		refresh();   // nothing redrawn (e.g. the volume): show the change now, not at the next check
	}
	if (result.message) setTimeout(() => showToast(result.message), messageDelay);   // e.g. after the tiles flip
}

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

function idleSeconds(slide) {
	return parseFloat(slide?.dataset.idleSeconds || IDLE_SECONDS);   // e.g. 4 minutes for the puzzles
}

function keepPaused(seconds) {
	if (!interacting) {
		interacting = true;
		clearTimeout(nextTimer);
		const minutes = Math.round(seconds / 60);
		showToast(`Paused: the slideshow continues after ${minutes === 1 ? "a minute" : minutes + " minutes"} without clicks`);
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
	// On a slide you can type on, keys go to the game instead of the shortcuts below.
	const slide = interactiveSlide();
	if (slide && slide.querySelector("[data-input-text]") && !event.ctrlKey && !event.altKey && !event.metaKey) {
		const key = event.key === "Enter" ? "ENTER" : event.key === "Backspace" ? "BACK" : event.key === " " ? "SPACE" : event.key;
		if (key.length === 1 || ["ENTER", "BACK", "SPACE"].includes(key)) {
			event.preventDefault();
			keepPaused(idleSeconds(slide));
			typeKey(slide, key);
			return;
		}
		if (event.key.startsWith("Arrow")) return;   // while typing, the arrows don't change slides
	}
	if (slide && slide.querySelector("[data-input-cell]") && !event.ctrlKey && !event.altKey && !event.metaKey) {
		const key = event.key === "Enter" ? "ENTER" : event.key === "Backspace" ? "BACK" : event.key.toUpperCase();
		if (key === "ENTER" || key === "BACK" || /^[A-Z]$/.test(key)) {
			event.preventDefault();
			keepPaused(idleSeconds(slide));
			typeKey(slide, key);
			return;
		}
	}
	if (event.key === "ArrowRight" || event.key === "ArrowDown") {
		next();
	} else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
		previous();
	} else if (event.key === " " && slide?.dataset.spaceAction) {
		// e.g. Spotify: space pauses the music (data-space-action on the slide) instead of the slideshow
		event.preventDefault();
		keepPaused(idleSeconds(slide));
		const button = slide.querySelector(`[data-action="${slide.dataset.spaceAction}"]`);
		button?.classList.add("busy");
		sendAction(slide, slide.dataset.spaceAction, []).finally(() => button?.classList.remove("busy"));
	} else if (event.key === " ") {
		paused = !paused;
		showToast(paused ? "Paused" : "Playing");
		if (paused) clearTimeout(nextTimer);
		else if (current) nextTimer = setTimeout(next, current.seconds * 1000);
	} else if (/^[0-9]$/.test(event.key) && !event.ctrlKey && !event.altKey && !event.metaKey) {
		jumpTo(event.key);
	} else if (event.key === "m") {
		await getJson("/api/narration", { method: "POST" });
		checkNotice();   // the server's confirmation shows up as a notice
	}
});

next();
checkNotice();
setInterval(checkNotice, 1000);
