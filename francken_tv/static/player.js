// Plays the slides the server sends, one after another.
// What is shown, and for how long, is decided in Python (francken_tv/scheduler.py);
// this file only loads each slide, fades it in, and waits.
//
// Keys: right/down = next, left/up = previous, space = pause for 4 minutes, or until space again with
// Settings → "Pause until unpaused" (or the slide's data-space-action,
// e.g. pausing the music on the Spotify slide), m = mute/unmute all sound,
// number keys = jump to a slide type, e.g. 1 = Daily puzzles (see [shortcuts] in config.toml),
// Esc = the menu: previews of those slide types, Settings and Power (see "The menu" below).
// Interactive slides (the puzzle): clicking pauses the slideshow there; see "Interactive slides" below.
// Messages from the server (e.g. Ctrl+M / Ctrl+R in the terminal) appear in the corner.

const layers = [document.getElementById("layer-a"), document.getElementById("layer-b")];
let front = 0;
let nextTimer = null;
let refreshTimer = null;
let paused = false;
let pauseTimer = null;         // ends a pause by itself (PAUSE_SECONDS), unless the pause is permanent
let permanentPause = false;    // Settings → "Pause until unpaused" (sent with every slide and by the menu)
let current = null;
const history = [];      // recently shown slides, for the left arrow key
let historyIndex = -1;
let interacting = false;   // someone is playing an interactive slide
let idleTimer = null;
let takeoverTimer = null;
const IDLE_SECONDS = 240;   // continue the slideshow after this long without clicks (data-idle-seconds on a slide overrides it)
const PAUSE_SECONDS = 240;  // a pause (space) ends by itself after this long, unless permanentPause
let showCount = 0;       // every slide change gets a number; only the newest may touch the screen
let loadedVersion = null;   // of style.css and player.js; when they change on disk, the page reloads

async function getJson(url, options) {
	const response = await fetch(url, options);
	if (!response.ok) throw new Error(`${url}: ${response.status}`);
	return response.json();
}

async function show(slide, { canRefresh = true } = {}) {
	const mine = ++showCount;
	closeMenu(false);   // e.g. bieruur starts while the menu is open
	stopInteracting();
	clearTimeout(nextTimer);
	clearInterval(refreshTimer);
	if (slide.permanent_pause !== undefined) setPermanentPause(slide.permanent_pause);
	const back = layers[1 - front];
	back.classList.add("loading");   // its animations wait until it's shown (style.css), or they'd run ahead of the timer
	back.innerHTML = slide.html;
	setupWidgets(back);
	// Wait until the images are decoded, so slides never appear half-loaded.
	const images = [...back.querySelectorAll("img")].filter((img) => !img.closest(".leaflet-container"));   // not map tiles
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
	back.classList.remove("loading");
	back.classList.add("visible");
	old.classList.remove("visible");
	startVideos(back, true);   // so they start with the slide, not while it is still loading
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
		if (slide.message) return;   // nothing to show for that key right now
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
			setupWidgets(layer);
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


// ---- Interactive slides -----------------------------------------------------------------
// A slide with data-interactive pauses the slideshow when clicked or typed on.
// - data-toggle elements can be selected (at most data-max-selected), e.g. Connections tiles;
// - data-action buttons send the selected data-values (or their own data-value) to the provider's
//   action() in Python (or to another provider, with data-provider on the button);
// - data-input-cell elements are filled by typing (keyboard or data-key buttons, e.g. Wordle),
//   or a data-input-text element takes free text (e.g. Catfishing, Spotify search), with a cursor
//   that the arrow keys, Home and End move; Enter sends the typed text as data-submit-action;
// - maps, sliders and other data-field widgets are in widgets.js.
// action() returns the redrawn slide and an optional message.

document.addEventListener("click", async (event) => {
	const slide = interactiveSlide();
	if (!slide || !slide.contains(event.target)) return;
	event.target.closest("button")?.blur();   // so Space/Enter later don't press it again
	keepPaused(idleSeconds(slide));
	const toggle = event.target.closest("[data-toggle]");
	const action = event.target.closest("[data-action]");
	const key = event.target.closest("[data-key]");
	const input = event.target.closest("[data-input-text]");
	const seek = event.target.closest("[data-seek]");   // a song's timeline: the click position, 0-1, as the value
	const selected = () => [...slide.querySelectorAll("[data-toggle].selected")];
	if (input) {
		clickInput(input, event);
	} else if (seek) {
		const box = seek.getBoundingClientRect();
		const fraction = Math.max(0, Math.min(1, (event.clientX - box.left) / box.width));
		sendAction(slide, seek.dataset.seek, [fraction.toFixed(4)], seek.dataset.provider);
	} else if (toggle) {
		const max = parseInt(slide.dataset.maxSelected || "1000", 10);
		if (toggle.classList.contains("selected") || selected().length < max) toggle.classList.toggle("selected");
	} else if (key) {
		typeKey(slide, key.dataset.key);
	} else if (action && action.dataset.action === "deselect") {
		selected().forEach((element) => element.classList.remove("selected"));
	} else if (action) {
		const values = action.dataset.value ? [action.dataset.value]
			: action.hasAttribute("data-send-fields") ? fieldValues(slide)   // e.g. TimeGuessr: the pin and the year (widgets.js)
			: selected().map((element) => element.dataset.value);
		action.classList.add("busy");   // shows the tap was seen, until the answer is there (style.css)
		sendAction(slide, action.dataset.action, values, action.dataset.provider).finally(() => action.classList.remove("busy"));
	}
});

const PUZZLE_PROVIDERS = ["puzzles", "connections", "wordle", "timeguessr", "catfishing"];

// The enabled, visible button in the slide closest to `from` in the direction of an arrow key (null if none).
function nearestButton(slide, from, key) {
	const [dx, dy] = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[key];
	const centre = (rect) => [rect.left + rect.width / 2, rect.top + rect.height / 2];
	const [fx, fy] = centre(from.getBoundingClientRect());
	let best = null, bestScore = Infinity;
	for (const button of slide.querySelectorAll("button:not([disabled])")) {
		if (button === from) continue;
		const rect = button.getBoundingClientRect();
		if (!rect.width || !rect.height) continue;
		const [x, y] = centre(rect);
		const along = (x - fx) * dx + (y - fy) * dy;     // distance in the arrow's direction
		const across = Math.abs((x - fx) * dy + (y - fy) * dx);   // sideways
		if (along <= 1 || across > along * 2 + rect.height) continue;   // not (mostly) in that direction
		const score = along + across * 2;
		if (score < bestScore) { best = button; bestScore = score; }
	}
	return best;
}

function interactiveSlide() {
	return layers[front].querySelector("[data-interactive]");
}

// Typing: a character, "SPACE", "ENTER" or "BACK"; in free text also "DELETE" and the cursor
// keys "LEFT", "RIGHT", "HOME" and "END".
function typeKey(slide, key) {
	const text = slide.querySelector("[data-input-text]");
	if (text) {   // free text
		const [value, at] = inputState(text);
		if (key === "ENTER") sendAction(slide, slide.dataset.submitAction, [value]);
		else if (key === "BACK") { if (at > 0) showInput(text, value.slice(0, at - 1) + value.slice(at), at - 1); }
		else if (key === "DELETE") showInput(text, value.slice(0, at) + value.slice(at + 1), at);
		else if (key === "LEFT") showInput(text, value, Math.max(0, at - 1));
		else if (key === "RIGHT") showInput(text, value, Math.min(value.length, at + 1));
		else if (key === "HOME") showInput(text, value, 0);
		else if (key === "END") showInput(text, value, value.length);
		else {
			const typed = key === "SPACE" ? " " : key;
			showInput(text, value.slice(0, at) + typed + value.slice(at), at + 1);
		}
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

// Free text and where its cursor is. The cursor is an empty .input-caret span inside the text, or,
// at the end, no span at all: then the slide's CSS draws it after the text (and a placeholder when empty).
function inputState(text) {
	const caret = text.querySelector(".input-caret");
	if (!caret) return [text.textContent, text.textContent.length];
	const before = document.createRange();
	before.selectNodeContents(text);
	before.setEndBefore(caret);
	return [text.textContent, before.toString().length];
}

// A click on a free-text field: the placeholder goes away (.editing) and the cursor goes where
// it was clicked.
function clickInput(text, event) {
	text.classList.add("editing");
	const [value] = inputState(text);
	const point = document.caretPositionFromPoint(event.clientX, event.clientY);
	let at = value.length;   // e.g. clicked after the text
	if (point && text.contains(point.offsetNode)) {
		const before = document.createRange();
		before.selectNodeContents(text);
		before.setEnd(point.offsetNode, point.offset);
		at = before.toString().length;
	}
	showInput(text, value, at);
}

function showInput(text, value, at) {
	if (at >= value.length) {
		text.textContent = value;
		return;
	}
	const caret = document.createElement("span");
	caret.className = "input-caret";
	text.replaceChildren(value.slice(0, at), caret, value.slice(at));
}

async function sendAction(slide, action, values, provider = slide.dataset.provider) {
	const result = await getJson("/api/action", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ provider, action, values }),
	});
	if (result.html) {
		const fresh = new DOMParser().parseFromString(result.html, "text/html");
		const effect = fresh.querySelector("[data-effect]");
		if (effect && effects[effect.dataset.effect]) await effects[effect.dataset.effect](slide);
		layers[front].innerHTML = result.html;
		setupWidgets(layers[front]);
		const resumeAfter = layers[front].querySelector("[data-resume-after]");
		if (resumeAfter) keepPaused(parseFloat(resumeAfter.dataset.resumeAfter));   // e.g. game over
	} else if (current && current.refresh) {
		refresh();   // nothing redrawn (e.g. the volume): show the change now, not at the next check
	}
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

// Show the mouse pointer while it moves; hide it again after 3 seconds (except on interactive
// slides, where it always shows: see style.css).
let cursorTimer = null;
document.addEventListener("mousemove", () => {
	document.body.classList.add("show-cursor");
	clearTimeout(cursorTimer);
	cursorTimer = setTimeout(() => document.body.classList.remove("show-cursor"), 3000);
});

document.addEventListener("focusin", (event) => {   // arrowing over the tabs shows each group's slides
	const tab = event.target.closest?.(".menu-tab");
	if (!tab || !menuIsOpen() || tab.getAttribute("aria-selected") === "true") return;
	clearTimeout(menuTabTimer);
	menuTabTimer = setTimeout(() => selectMenuTab(tab.dataset.value), 150);   // not for every tab passed on the way
});

document.addEventListener("keydown", async (event) => {
	if (menuIsOpen()) return menuKey(event);
	if (event.key === "Escape") {
		// A photo shown full screen (e.g. TimeGuessr's, data-zoom): Esc makes it small again first.
		const full = interactiveSlide()?.querySelector("[data-zoom].selected");
		if (full) {
			full.classList.remove("selected");
			keepPaused(idleSeconds(interactiveSlide()));
			return;
		}
		return openMenu();
	}
	// On a slide you can type on, keys go to the game instead of the shortcuts below.
	const slide = interactiveSlide();
	// A button marked data-enter (e.g. Catfishing's "Next article") is pressed by Enter.
	const enter = slide?.querySelector("[data-enter]");
	if (enter && event.key === "Enter" && !event.ctrlKey && !event.altKey && !event.metaKey) {
		event.preventDefault();
		keepPaused(idleSeconds(slide));
		enter.click();
		return;
	}
	if (slide && slide.querySelector("[data-input-text]") && !event.ctrlKey && !event.altKey && !event.metaKey) {
		const names = { Enter: "ENTER", Backspace: "BACK", " ": "SPACE", Delete: "DELETE",
			ArrowLeft: "LEFT", ArrowRight: "RIGHT", Home: "HOME", End: "END" };
		const key = names[event.key] || event.key;
		if (key.length === 1 || Object.values(names).includes(key)) {
			event.preventDefault();
			keepPaused(idleSeconds(slide));
			typeKey(slide, key);
			return;
		}
		if (event.key.startsWith("Arrow")) return;   // up and down don't change slides while typing either
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
	// Once you've Tabbed onto a button in a puzzle, the arrow keys move to the nearest button in that direction.
	// Where there is none (the edge) they do what they always did: change slides.
	if (event.key.startsWith("Arrow") && slide && PUZZLE_PROVIDERS.includes(slide.dataset.provider)
			&& !event.ctrlKey && !event.altKey && !event.metaKey && event.target.closest?.("button")
			&& slide.contains(event.target)) {
		const target = nearestButton(slide, event.target, event.key);
		if (target) {
			event.preventDefault();
			keepPaused(idleSeconds(slide));
			target.focus();
			return;
		}
	}
	if (event.key.startsWith("Arrow") && event.target.closest?.("input, .leaflet-container")) return;   // they move the slider or map
	// Up and down scroll a text that's longer than the screen (data-scroll, e.g. a news article).
	const scroller = slide?.querySelector("[data-scroll]");
	if (scroller && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
		event.preventDefault();
		keepPaused(idleSeconds(slide));
		scroller.scrollBy({ top: (event.key === "ArrowDown" ? 0.6 : -0.6) * scroller.clientHeight, behavior: "smooth" });
		return;
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
		const values = button?.dataset.value ? [button.dataset.value] : [];   // what the button sends, e.g. "lyrics" to stay in that view
		sendAction(slide, slide.dataset.spaceAction, values).finally(() => button?.classList.remove("busy"));
	} else if (event.key === " ") {
		setPaused(!paused);
	} else if (/^[0-9]$/.test(event.key) && !event.ctrlKey && !event.altKey && !event.metaKey) {
		jumpTo(event.key);
	} else if (event.key === "m") {
		await getJson("/api/mute", { method: "POST" });   // all sound on the TV PC, like "Mute all sound" in the settings
	}
});

// Space pauses the slideshow; a pause ends by itself after PAUSE_SECONDS (with the next slide), unless
// "Pause until unpaused" is on in the settings. Pressing space again goes on as usual.
function setPaused(on) {
	paused = on;
	clearTimeout(pauseTimer);
	if (paused) {
		clearTimeout(nextTimer);
		if (!permanentPause) pauseTimer = setTimeout(() => { paused = false; next(); }, PAUSE_SECONDS * 1000);
	} else if (current) {
		nextTimer = setTimeout(next, current.seconds * 1000);
	}
}

// The setting changed (in the menu, or on another screen): a pause that's on now follows it.
function setPermanentPause(on) {
	if (on === permanentPause) return;
	permanentPause = on;
	if (paused) {
		clearTimeout(pauseTimer);
		if (!permanentPause) pauseTimer = setTimeout(() => { paused = false; next(); }, PAUSE_SECONDS * 1000);
	}
}

// ---- The menu --------------------------------------------------------------------------------
// Esc opens it: tabs with the slide types in groups (the same groups as in the emulator, menu.py), the first
// tab "Quick" being the slide types in [shortcuts] (config.toml), then the sound (mute and volume), Settings and
// Power. Left and right choose a group, down goes to its slides.
// What it shows comes from the server (francken_tv/menu.py), and choices go back there.
// While it's open the slideshow waits; Esc again (or a minute without input) continues it.

const menu = document.getElementById("menu");
const MENU_IDLE_SECONDS = 60;
let menuData = null;
let menuPage = "overview";
let menuTab = "quick";        // the overview's tab: "quick", or the title of a group (kept while the page is open)
let menuGroups = {};          // group title -> which of its slides have something to show right now (asked when the tab is chosen)
let menuTabTimer = null;
let menuIdleTimer = null;
let menuTakeoverTimer = null;
let confirming = null;     // a button that needs a second press (start a puzzle over, shut down)
let confirmTimer = null;

const ICONS = {
	settings: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z"/></svg>',
	power: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2v10"/><path d="M18.4 6.6a9 9 0 1 1-12.8 0"/></svg>',
	restart: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/></svg>',
	sound: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M11 5 6 9H2v6h4l5 4V5Z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M19 5a10 10 0 0 1 0 14"/></svg>',
	muted: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M11 5 6 9H2v6h4l5 4V5Z"/><path d="m22 9-6 6"/><path d="m16 9 6 6"/></svg>',
};

// Mute and the volume, on the overview: a bar that can be tapped anywhere, with - and + for the keys.
function soundControls(settings) {
	return `
		<div class="menu-sound${settings.muted ? " muted" : ""}">
			<button class="menu-button" data-focus="mute" data-menu="toggle" data-value="muted" aria-pressed="${settings.muted}">
				${settings.muted ? ICONS.muted + "Unmute" : ICONS.sound + "Mute"}</button>
			<span class="menu-stepper">
				<button data-focus="volume-down" data-menu="volume" data-value="-10" aria-label="Quieter"${settings.volume <= 0 ? " disabled" : ""}>&minus;</button>
				<span class="menu-volume" data-menu="volume_at" title="Volume"><i style="width: ${settings.volume}%"></i></span>
				<button data-focus="volume-up" data-menu="volume" data-value="10" aria-label="Louder"${settings.volume >= 100 ? " disabled" : ""}>+</button>
				<output>${settings.volume}%</output>
			</span>
		</div>`;
}

const escapeHtml = (text) => String(text).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

function menuIsOpen() {
	return !menu.hidden;
}

async function openMenu() {
	try {
		menuData = await getJson("/api/menu");
		setPermanentPause(menuData.settings.permanent_pause);
	} catch (error) {
		console.error(error);
		return;   // the menu isn't available right now
	}
	showCount += 1;   // a slide that is still loading doesn't appear (and close the menu)
	clearTimeout(nextTimer);
	clearTimeout(idleTimer);
	clearInterval(menuTakeoverTimer);
	menuTakeoverTimer = setInterval(checkTakeover, 5000);   // bieruur still starts on time
	menu.hidden = false;
	menuGroups = {};
	showMenuPage("overview");
	if (menuTab !== "quick") selectMenuTab(menuTab);   // opens on the group it was on
}

// resume = false when a slide was chosen in the menu: that slide sets its own timer.
function closeMenu(resume = true) {
	if (!menuIsOpen()) return;
	menu.hidden = true;
	menu.innerHTML = "";   // also stops the previews
	clearTimeout(menuIdleTimer);
	clearInterval(menuTakeoverTimer);
	if (!resume) return;
	const slide = interactiveSlide();
	if (interacting && slide) keepPaused(idleSeconds(slide));
	else if (!paused && current) nextTimer = setTimeout(next, current.seconds * 1000);
}

function menuActivity() {
	clearTimeout(menuIdleTimer);
	menuIdleTimer = setTimeout(() => closeMenu(), MENU_IDLE_SECONDS * 1000);
}

// focus: the data-focus of the element to select, e.g. the button that was just pressed.
function showMenuPage(page, focus) {
	const entering = page !== menuPage || !menu.firstElementChild;   // a new page zooms in; a redraw after a change doesn't
	menuPage = page;
	confirming = null;
	menu.innerHTML = `<div class="menu-panel menu-page-${page}${entering ? " menu-enter" : ""}">${menuPages[page](menuData)}</div>`;
	const target = (focus && menu.querySelector(`[data-focus="${focus}"]:not([disabled])`))
		|| menu.querySelector(".menu-tab-content [data-focus]:not([disabled])")   // the overview: the first slide of the group
		|| menu.querySelector("[data-focus]:not([disabled]):not(.menu-back)");
	target?.focus();
	menuActivity();
}

// How many previews side by side in the overview: up to 4 in one row, more in rows of (nearly) equal
// length, at most 4 to a row (7: 4 and 3).
function menuColumns(count) {
	return count <= 4 ? Math.max(count, 1) : Math.ceil(count / Math.ceil(count / 4));
}

function menuTabs(data) {
	const tabs = [{ title: "quick", label: "Quick" }, ...data.groups.map((group) => ({ title: group.title, label: group.title }))];
	if (!tabs.some((tab) => tab.title === menuTab)) menuTab = "quick";   // a group that has gone
	return tabs.map((tab, number) => `
		<button class="menu-tab" role="tab" data-focus="tab-${number}" data-menu="tab" data-value="${escapeHtml(tab.title)}"
			aria-selected="${tab.title === menuTab}">${escapeHtml(tab.label)}</button>`).join("");
}

// The cards of a tab: the shortcuts' previews (Quick), or the slides of a group (greyed out while it isn't known yet
// whether they have something to show, then as soon as it is).
function menuTabContent(data) {
	const card = (focus, jump, preview, key, label, available, empty) => `
		<button class="menu-card" data-focus="${escapeHtml(focus)}" data-menu="jump" data-value="${escapeHtml(jump)}"${available === false ? " disabled" : ""}>
			<span class="menu-preview">${available
				? `<iframe src="/preview/${encodeURIComponent(preview)}" tabindex="-1"></iframe>`
				: `<span>${escapeHtml(empty)}</span>`}</span>
			<span class="menu-card-title">${key ? `<kbd>${escapeHtml(key)}</kbd>` : ""}${escapeHtml(label)}</span>
		</button>`;
	let cards;
	if (menuTab === "quick") {
		cards = data.previews.map((preview) => card(`slide-${preview.key}`, preview.key, preview.name, preview.key, preview.title, preview.available, preview.empty));
	} else {
		const group = data.groups.find((candidate) => candidate.title === menuTab);
		const status = menuGroups[menuTab];
		const keys = Object.fromEntries(data.previews.map((preview) => [preview.name, preview.key]));
		cards = group.channels.map((channel) => {
			const found = status?.find((entry) => entry.name === channel.name);
			return card(`go-${channel.name}`, `go-${channel.name}`, channel.name, keys[channel.name], channel.label,
				found ? found.available : null, found ? found.empty : "…");   // null: not known yet
		});
	}
	return `<div class="menu-cards" style="--columns: ${menuColumns(cards.length)}">${cards.join("")}</div>`;
}

// Show another tab's cards (the focus stays where it is), asking the server first which slides have anything to show.
async function selectMenuTab(title) {
	menuTab = title;
	for (const tab of menu.querySelectorAll(".menu-tab")) tab.setAttribute("aria-selected", String(tab.dataset.value === title));
	const draw = () => {
		if (menuTab !== title || !menuIsOpen() || menuPage !== "overview") return;
		const content = menu.querySelector(".menu-tab-content");
		if (content) content.innerHTML = menuTabContent(menuData);
	};
	draw();
	if (title !== "quick" && !menuGroups[title]) {
		try {
			menuGroups[title] = await getJson(`/api/menu/group/${encodeURIComponent(title)}`);
		} catch (error) {
			console.error(error);
			menuGroups[title] = [];
		}
		draw();
	}
}

const menuPages = {
	overview: (data) => `
		<nav class="menu-tabs" role="tablist" aria-label="Groups of slides">${menuTabs(data)}</nav>
		<div class="menu-tab-content">${menuTabContent(data)}</div>
		<div class="menu-actions">
			${soundControls(data.settings)}
			<button class="menu-button" data-focus="settings" data-menu="page" data-value="settings">${ICONS.settings}Settings</button>
			${data.power.length ? `<button class="menu-button" data-focus="power" data-menu="page" data-value="power">${ICONS.power}Power</button>` : ""}
		</div>
		<p class="menu-hint">&larr; &rarr; group &middot; &darr; its slides &middot; Enter to open &middot; Esc to close</p>`,

	settings: (data) => {
		const settings = data.settings;
		const toggle = (name, label, note = "") => `
			<button class="menu-row menu-toggle" role="switch" aria-checked="${settings[name]}" data-focus="${name}"
				data-menu="toggle" data-value="${name}">
				<span>${label}${note && `<small>${note}</small>`}</span><span class="menu-switch"></span>
			</button>`;
		return `
		<header class="menu-header">
			<button class="menu-back" data-focus="back" data-menu="page" data-value="overview">&larr; Back</button>
			<h1>Settings</h1>
		</header>
		<div class="menu-settings">
			<div class="menu-column">
				<section>
					<h2>Sound</h2>
					${toggle("muted", "Mute all sound", "Everything on the TV PC: Spotify, greetings, quotes and the bieruur song")}
					${toggle("quotes_aloud", "Read quotes aloud")}
					${toggle("greetings", "Greet people who walk in")}
					<div class="menu-row">
						<span>Volume<small>Of everything, Spotify too</small></span>
						<span class="menu-stepper">
							<button data-focus="volume-down" data-menu="volume" data-value="-10" aria-label="Quieter"${settings.volume <= 0 ? " disabled" : ""}>&minus;</button>
							<output>${settings.volume}%</output>
							<button data-focus="volume-up" data-menu="volume" data-value="10" aria-label="Louder"${settings.volume >= 100 ? " disabled" : ""}>+</button>
						</span>
					</div>
				</section>
				<section>
					<h2>Today's puzzles</h2>
					${data.puzzles.map((puzzle) => `
					<div class="menu-row">
						<span>${escapeHtml(puzzle.title)}<small>${escapeHtml(puzzle.status)}</small></span>
						<button class="menu-small-button" data-focus="reset-${puzzle.name}" data-menu="reset" data-value="${puzzle.name}"
							data-confirm="Sure?"${puzzle.state === "new" ? " disabled" : ""}>Start over</button>
					</div>`).join("") || '<p class="menu-note">No puzzles today (yet).</p>'}
					${data.puzzles.length > 1 ? `<button class="menu-small-button menu-wide" data-focus="reset-all" data-menu="reset" data-value=""
						data-confirm="Sure? All of them?"${data.puzzles.every((puzzle) => puzzle.state === "new") ? " disabled" : ""}>Start all puzzles over</button>` : ""}
				</section>
			</div>
			<div class="menu-column">
				<section>
					<h2>Slides</h2>
					<div class="menu-row">
						<span>Speed</span>
						<span class="menu-choices">${data.speeds.map((speed) => `
							<button data-focus="speed-${speed}" data-menu="speed" data-value="${speed}" aria-pressed="${speed === settings.speed}">${speed}&times;</button>`).join("")}
						</span>
					</div>
					<p class="menu-note">2&times; = every slide is shown half as long</p>
					${toggle("permanent_pause", "Pause until unpaused", "Space pauses the slideshow; when this is off it goes on by itself after 4 minutes")}
					<h3>Shown in the slideshow</h3>
					<div class="menu-chips">${data.slide_types.map((type) => `
						<button class="menu-chip" data-focus="type-${type.name}" data-menu="slide_type" data-value="${type.name}"
							aria-pressed="${!settings.hidden.includes(type.name)}">${escapeHtml(type.title)}</button>`).join("")}
					</div>
				</section>
				<section>
					<h2>Other</h2>
					<button class="menu-row menu-row-button" data-focus="reload-devices" data-menu="reload_devices">
						<span>Reload devices.json<small>After adding someone's phone, so the chart and greetings know them</small></span>
					</button>
				</section>
			</div>
		</div>`;
	},

	power: () => `
		<header class="menu-header">
			<button class="menu-back" data-focus="back" data-menu="page" data-value="overview">&larr; Back</button>
			<h1>Power</h1>
		</header>
		<div class="menu-power">
			<button class="menu-power-button" data-focus="shutdown" data-menu="power" data-value="shutdown" data-confirm="Press again to shut down">${ICONS.power}<span>Shut down</span></button>
			<button class="menu-power-button" data-focus="restart" data-menu="power" data-value="restart" data-confirm="Press again to restart">${ICONS.restart}<span>Restart</span></button>
		</div>
		<p class="menu-hint">Shuts down or restarts the TV PC</p>`,
};

async function menuChoose(button) {
	menuActivity();
	const { menu: action, value } = button.dataset;
	if (button.dataset.confirm && confirming !== button) {   // the first press only asks "sure?"
		confirming?.classList.remove("confirming");
		confirming = button;
		button.classList.add("confirming");
		clearTimeout(confirmTimer);
		confirmTimer = setTimeout(() => {
			button.classList.remove("confirming");
			if (confirming === button) confirming = null;
		}, 4000);
		return;
	}
	const settings = menuData.settings;
	if (action === "tab") {
		await selectMenuTab(value);
		menu.querySelector(".menu-tab-content [data-focus]:not([disabled])")?.focus();   // into its slides
		return;
	}
	if (action === "jump") {
		closeMenu(false);
		jumpTo(value);
	} else if (action === "page") {
		showMenuPage(value, menuPage);   // back to the overview: select the button of the page we came from
	} else if (action === "toggle") {
		sendMenu(button, "settings", { [value]: !settings[value] });
	} else if (action === "volume") {
		sendMenu(button, "settings", { volume: settings.volume + Number(value) });
	} else if (action === "speed") {
		sendMenu(button, "settings", { speed: Number(value) });
	} else if (action === "slide_type") {
		const hidden = settings.hidden.includes(value) ? settings.hidden.filter((name) => name !== value) : [...settings.hidden, value];
		sendMenu(button, "settings", { hidden });
	} else if (action === "reset") {
		sendMenu(button, "reset_puzzle", value || null);
	} else if (action === "reload_devices" || action === "power") {
		sendMenu(button, action, value ?? null);
	}
}

async function sendMenu(button, command, value) {
	button.classList.add("busy");
	try {
		const answer = await getJson("/api/menu", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ command, value }),
		});
		menuData = answer.menu;
		setPermanentPause(menuData.settings.permanent_pause);
		if (menuIsOpen() && menuPage !== "overview") showMenuPage(menuPage, button.dataset.focus);
		else if (menuIsOpen()) {   // the overview: only the sound controls, so the previews keep playing
			menu.querySelector(".menu-sound")?.replaceWith(...htmlElements(soundControls(menuData.settings)));
			menu.querySelector(`[data-focus="${button.dataset.focus}"]:not([disabled])`)?.focus();
		}
	} catch (error) {
		console.error(error);
	} finally {
		button.classList.remove("busy");
	}
}

function htmlElements(html) {
	const template = document.createElement("template");
	template.innerHTML = html.trim();
	return [...template.content.children];
}

function menuKey(event) {
	menuActivity();
	if (event.key === "Escape") {
		event.preventDefault();
		if (menuPage === "overview") closeMenu();
		else showMenuPage("overview", menuPage);
	} else if (event.key.startsWith("Arrow")) {
		event.preventDefault();
		moveMenuFocus(event.key);
	} else if (menuPage === "overview" && /^[0-9]$/.test(event.key)) {
		closeMenu(false);
		jumpTo(event.key);
	} else if (!["Enter", " ", "Tab"].includes(event.key)) {
		event.preventDefault();   // Enter and space press the selected button; other keys do nothing here
	}
}

// The arrow keys select the nearest button in that direction, like a TV remote.
function moveMenuFocus(key) {
	const items = [...menu.querySelectorAll("[data-focus]:not([disabled])")];
	const from = items.includes(document.activeElement) ? document.activeElement : null;
	const onTab = from?.classList.contains("menu-tab");
	if (!from) return items[0]?.focus();
	if (onTab) {   // the tabs wrap onto two lines: left and right go along them, down goes into the slides
		const tabs = [...menu.querySelectorAll(".menu-tab")];
		if (key === "ArrowLeft" || key === "ArrowRight") return tabs[tabs.indexOf(from) + (key === "ArrowRight" ? 1 : -1)]?.focus();
		if (key === "ArrowUp") return;
		const cards = [...menu.querySelectorAll(".menu-tab-content [data-focus]:not([disabled])")];
		const middle = (element) => element.getBoundingClientRect().left + element.getBoundingClientRect().width / 2;
		const nearest = cards.sort((a, b) => Math.abs(middle(a) - middle(from)) - Math.abs(middle(b) - middle(from)))[0];
		if (nearest) return nearest.focus();
	}
	const [dx, dy] = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[key];
	const a = from.getBoundingClientRect();
	let best = null;
	let bestScore = Infinity;
	for (const item of items) {
		const b = item.getBoundingClientRect();
		const x = b.left + b.width / 2 - (a.left + a.width / 2);
		const y = b.top + b.height / 2 - (a.top + a.height / 2);
		const along = x * dx + y * dy;              // how far in the arrow's direction
		if (item === from || along <= 1) continue;
		if (!onTab && item.classList.contains("menu-tab")) continue;   // from a slide, a tab is only reached by going up (below)
		const score = along + 2 * Math.abs(x * dy + y * dx);   // ...and how far off to the side
		if (score < bestScore) {
			best = item;
			bestScore = score;
		}
	}
	if (best) {
		best.focus();
		best.scrollIntoView({ block: "nearest" });
	} else if (key === "ArrowUp" && !onTab) {   // above the top row of slides: the tab of this group
		menu.querySelector('.menu-tab[aria-selected="true"]')?.focus();
	}
}

menu.addEventListener("click", (event) => {
	if (event.target === menu) return closeMenu();   // a click next to the menu
	const button = event.target.closest("[data-menu]");
	if (button?.dataset.menu === "volume_at") {   // a tap on the volume bar: that volume, in steps of 5
		const bar = button.getBoundingClientRect();
		const volume = Math.round(Math.max(0, Math.min(1, (event.clientX - bar.left) / bar.width)) * 20) * 5;
		menuActivity();
		return sendMenu(button, "settings", { volume });
	}
	if (button && !button.disabled) menuChoose(button);
});
menu.addEventListener("mousemove", menuActivity);

// ---- Overlays -----------------------------------------------------------------------------------
// Every few seconds: anything to show over whatever slide is on (the Francken pet thanking for a streep,
// providers/pet.py)? It goes in #overlay (above the slides, not in the way of taps) for its seconds.
const overlay = document.getElementById("overlay");
let overlayTimer = null;
setInterval(async () => {
	try {
		const shown = await getJson("/api/overlay");
		if (!shown.html) return;
		overlay.innerHTML = shown.html;   // a new one replaces one still showing (its animation starts over)
		clearTimeout(overlayTimer);
		overlayTimer = setTimeout(() => { overlay.innerHTML = ""; }, shown.seconds * 1000);
	} catch (error) {
		console.error(error);
	}
}, 5000);

next();
