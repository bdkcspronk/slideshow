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
let idleClick = false;     // the last click was on nothing you can use: the arrows change slides again
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
	paused = false; clearTimeout(pauseTimer);   // a pause is for the slide that was paused: whatever shows next, the next space pauses again
	if (slide.permanent_pause !== undefined) setPermanentPause(slide.permanent_pause);
	const back = layers[1 - front];
	back.classList.add("loading");   // its animations wait until it's shown (style.css), or they'd run ahead of the timer
	back.innerHTML = slide.html;
	setRate(back, slide.rate || 1);   // before the widgets are set up: they time themselves by it
	for (const svg of back.querySelectorAll("svg")) svg.pauseAnimations?.();   // SVG (SMIL) animations wait for the show too, like the CSS ones
	setupWidgets(back);
	// Wait until the images are decoded, so slides never appear half-loaded.
	const images = [...back.querySelectorAll("img")].filter((img) => !img.closest(".leaflet-container"));   // not map tiles
	// A hanging image may not keep the old slide on screen for ever: after 5 s carry on (a still-missing image is skipped just below).
	const gaveUp = new Promise((resolve) => setTimeout(resolve, 5000));
	await Promise.race([Promise.all(images.map((img) => img.decode().catch(() => {}))), gaveUp]);
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
	back.dataset.shownAt = performance.now();   // the slide's clock starts here: the 3D slides count from it, like the CSS animations
	for (const svg of back.querySelectorAll("svg")) { svg.setCurrentTime?.(0); svg.unpauseAnimations?.(); }
	paceSvgs(back);
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

// A slide that times itself (the Instagram phone, instagram_3d.js): it stays for `seconds` in all, of which `left` from
// now, whatever the server planned for it (slide.seconds): its timeline is never cut off. Not a slide that was cut short
// for a takeover (bieruur starts on time), and not while the slideshow is standing still anyway (a pause, the menu).
function slideTakes(element, seconds, left = seconds) {
	if (element.closest(".layer") !== layers[front] || !current || current.cut_short) return;
	current.seconds = seconds;   // for when it goes on after a pause or the menu
	if (paused || interacting || !menu.hidden) return;
	clearTimeout(nextTimer);
	nextTimer = setTimeout(next, Math.max(left, 0.5) * 1000);
}

// The menu's Speed makes a slide shorter or longer (slide.seconds) and gives it a rate to match (2 = twice as fast), so
// that what happens on it still happens once and fills its time, instead of being cut off or done long before the end.
// Its CSS animations and transitions are played at that rate here, like a video's playback speed; what is timed in
// JavaScript asks slideRate() (widgets.js). Animations that start later (a class added by a widget, a redraw by the
// slide's own updates) are caught by looking again ten times a second, which costs next to nothing and only runs while
// the speed isn't 1. Left alone: slides on a real clock or the music (data-real-time), and the marquees, which scroll
// at reading speed. A tap ends it (keepPaused): what answers a tap always moves at its own pace. The Instagram slide
// isn't made shorter or longer at all (Slide.real_time): it plays at rate 1 and times itself (slideTakes()).
let rateTimer = null;
let applyRate = () => {};   // looks right now, for a widget that has just started animations (widgets.js)

function setRate(layer, rate) {
	clearInterval(rateTimer);
	layer.dataset.rate = rate;
	applyRate = () => {};
	if (rate === 1) return;
	const apply = () => {
		for (const animation of layer.getAnimations({ subtree: true })) {
			if (animation.playbackRate === rate) continue;
			if (animation.effect?.target === layer) continue;   // the fade between slides: the old slide fades out at normal speed too
			if (animation.effect?.target?.closest("[data-real-time], [data-marquee]")) continue;
			animation.playbackRate = rate;
		}
	};
	apply();
	applyRate = apply;
	rateTimer = setInterval(apply, 100);
}

// SVG (SMIL) animations have no playback rate (the MScie caps' cords): at another speed they stay paused and their clock
// is moved along by hand every frame instead, until the slide is gone or someone taps it.
function paceSvgs(layer) {
	const rate = Number(layer.dataset.rate) || 1;
	const svgs = [...layer.querySelectorAll("svg")].filter((svg) => svg.querySelector("animate, animateTransform, animateMotion, set") && !svg.closest("[data-real-time]"));
	if (rate === 1 || !svgs.length) return;
	for (const svg of svgs) svg.pauseAnimations?.();
	let started = null, time = 0;
	const frame = (now) => {
		if (!svgs.some((svg) => document.contains(svg))) return;
		if (Number(layer.dataset.rate) !== rate) {   // a tap: on at normal speed from where it is
			for (const svg of svgs) svg.unpauseAnimations?.();
			return;
		}
		started ??= now;
		time = (now - started) / 1000 * rate;
		for (const svg of svgs) svg.setCurrentTime?.(time);
		requestAnimationFrame(frame);
	};
	requestAnimationFrame(frame);
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
// stays on screen like after a click, so people can use it. Returns whether a slide was shown:
// null if there's no such shortcut or slide type (right now: membership out of season).
async function jumpTo(key) {
	try {
		const response = await fetch(`/api/shortcut/${key}`);
		if (response.status === 404) return null;   // not a shortcut
		if (!response.ok) throw new Error(`shortcut ${key}: ${response.status}`);
		const slide = await response.json();
		if (slide.message) {   // nothing to show for that key right now: say so, or the tap seems to do nothing
			showMessage(slide.message);
			return false;
		}
		history.splice(historyIndex + 1);   // jumping drops the slides ahead after going back
		history.push(slide);
		if (history.length > 30) history.shift();
		historyIndex = history.length - 1;
		await show(slide);
		const shown = interactiveSlide();
		if (shown) keepPaused(idleSeconds(shown));
		return true;
	} catch (error) {
		console.error(error);
		return false;
	}
}

// A short message over any slide ("Membership: nothing to show right now", "Restarting..."), like the puzzles'
// pop-ups: in at once with ease-out (it answers a tap), held, out with ease-in (#message in style.css). A new
// message replaces the old one and starts its animation again.
function showMessage(text) {
	const old = document.getElementById("message");
	const message = old.cloneNode(false);   // a fresh element, so the animation plays from the start
	message.textContent = text;
	message.hidden = false;
	old.replaceWith(message);
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
// The slide on screen drawn again (its clock, the song's progress...). It asks for this slide by its number, not for the
// server's current slide: another screen on the same server (a second browser, a phone) or a reply that came too late
// moves that on, and redrawing to it every second made a slide replay its first second over and over.
async function refresh() {
	try {
		const started = showCount;
		if (!current?.id) return;
		const response = await fetch(`/api/refresh/${current.id}`);
		if (response.status === 404) return clearInterval(refreshTimer);   // too long ago: the server forgot it
		if (!response.ok) throw new Error(`refresh: ${response.status}`);
		const slide = await response.json();
		if (started !== showCount) return;   // the slide changed meanwhile
		const layer = layers[front];
		const fresh = document.createElement("div");
		fresh.innerHTML = slide.html;
		const oldState = layer.querySelector("[data-state]")?.dataset.state;
		const newState = fresh.querySelector("[data-state]")?.dataset.state;
		if (oldState === undefined || oldState !== newState) {
			redraw(layer, slide.html);
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

// A timeline or volume bar (data-seek, e.g. Spotify's): pressed, it follows the finger or mouse (--drag and .dragging,
// see style.css); let go, it sends the spot, 0-1 along the bar, as the action's value. A plain click is a drag that didn't move.
let seekDrag = null;

function dragTo(seek, event) {
	const box = (seek.firstElementChild || seek).getBoundingClientRect();   // the bar itself, not the taller area around it
	const fraction = Math.max(0, Math.min(1, (event.clientX - box.left) / box.width));
	seek.style.setProperty("--drag", `${(fraction * 100).toFixed(2)}%`);
	const mute = seek.dataset.seek === "volume" && seek.parentElement.querySelector(".spotify-mute");   // the speaker's waves follow
	if (mute) mute.dataset.level = fraction < 0.005 ? 0 : fraction < 0.34 ? 1 : fraction < 0.67 ? 2 : 3;
	return fraction;
}

document.addEventListener("pointerdown", (event) => {
	const slide = interactiveSlide();
	const seek = event.target.closest?.("[data-seek]");
	if (!seek || !slide?.contains(seek) || event.button !== 0) return;
	event.preventDefault();   // no text selection while dragging
	keepPaused(idleSeconds(slide));
	seek.setPointerCapture(event.pointerId);   // keeps following outside the bar
	seek.classList.add("dragging");
	dragTo(seek, event);
	seekDrag = seek;
});

document.addEventListener("pointermove", (event) => {
	if (seekDrag) dragTo(seekDrag, event);
});

document.addEventListener("pointerup", (event) => {
	const seek = seekDrag;
	if (!seek) return;
	seekDrag = null;
	const slide = interactiveSlide();
	const fraction = dragTo(seek, event);
	// A value shown in place (data-live, Spotify's volume) stays where it was dropped instead of jumping back until the next refresh.
	seek.querySelector("[data-live]")?.style.setProperty("width", `${(fraction * 100).toFixed(2)}%`);
	if (!slide?.contains(seek)) return seek.classList.remove("dragging");   // the slide changed meanwhile
	seek.classList.add("busy");   // shows the tap was seen, until the answer is there (style.css)
	sendAction(slide, seek.dataset.seek, [fraction.toFixed(4)], seek.dataset.provider)
		.finally(() => seek.classList.remove("busy", "dragging"));
});

document.addEventListener("pointercancel", () => {
	seekDrag?.classList.remove("dragging");
	seekDrag = null;
});

document.addEventListener("click", async (event) => {
	const slide = interactiveSlide();
	if (!slide || !slide.contains(event.target)) return;
	// A mouse or finger click: so Space/Enter later don't press it again. Not when it was pressed with the keyboard
	// (event.detail 0): then it keeps its focus, so the arrows go on from there instead of changing slides.
	if (event.detail > 0) event.target.closest("button")?.blur();
	keepPaused(idleSeconds(slide));
	idleClick = !event.target.closest("button, input, a, [data-toggle], [data-action], [data-key], [data-input-text], [data-input-cell], [data-seek], [data-zoom], [tabindex], .leaflet-container");
	const toggle = event.target.closest("[data-toggle]");
	const action = event.target.closest("[data-action]");
	const key = event.target.closest("[data-key]");
	const input = event.target.closest("[data-input-text]");
	const seek = event.target.closest("[data-seek]");   // a song's timeline: the click position, 0-1, as the value
	const selected = () => [...slide.querySelectorAll("[data-toggle].selected")];
	if (input) {
		clickInput(input, event);
	} else if (seek) {
		// sent when the pointer is let go (pointerup below), whether it was a click or a drag
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

// The enabled, visible button in the slide closest to `from` in the direction of an arrow key (null if none).
function nearestButton(slide, from, key) {
	const [dx, dy] = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[key];
	const centre = (rect) => [rect.left + rect.width / 2, rect.top + rect.height / 2];
	const [fx, fy] = centre(from.getBoundingClientRect());
	let best = null, bestScore = Infinity;
	for (const button of slide.querySelectorAll("button:not([disabled]), [data-seek][tabindex]")) {   // a bar you can Tab to, too
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
		if (key === "ENTER") submit(slide, [value]);
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
		submit(slide, [cells.map((cell) => cell.textContent.trim()).join("")]);
	} else if (key === "BACK") {
		const last = cells.filter((cell) => cell.textContent.trim()).pop();
		if (last) { last.textContent = ""; last.classList.remove("filled"); }
	} else {
		const empty = cells.find((cell) => !cell.textContent.trim());
		if (empty) { empty.textContent = key; empty.classList.add("filled"); }
	}
}

// Enter: send what was typed. Its on-screen button shows .busy until the answer is there, like a
// tapped data-action button (also when Enter was typed on a real keyboard).
function submit(slide, values) {
	const button = slide.querySelector('[data-key="ENTER"]');
	button?.classList.add("busy");
	return sendAction(slide, slide.dataset.submitAction, values).finally(() => button?.classList.remove("busy"));
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

// The same slide drawn again (after a tap, or a refresh that changed its state). An element with
// data-steady (e.g. Spotify's cover) that has the same value as before doesn't play its entrance
// again: pausing shouldn't make the cover disappear and fade back in (.steady in style.css).
function redraw(layer, html, tapped = false) {
	const before = new Set([...layer.querySelectorAll("[data-steady]")].map((element) => element.dataset.steady));
	// Keyboard focus on a button survives the redraw: the same button (same action and value, or key) is focused in the new
	// slide, so someone without a mouse can go on with the arrows instead of falling back to changing slides.
	// A bar you can Tab to (Spotify's volume and timeline, data-seek) is kept the same way, by its data-seek value.
	const focused = layer.contains(document.activeElement) ? document.activeElement.closest("button, [data-seek]") : null;
	const same = focused && ["action", "value", "key", "provider"].map((name) => focused.dataset[name]);
	// An element with data-phase (the pet being chosen: a tap would restart its bob and snap it up to 1.5vh) carries on from where its
	// loop was: the new copy gets that time as a negative delay in --phase (style.css). data-steady can't do this, it stops the animation.
	const phases = new Map([...layer.querySelectorAll("[data-phase]")].map((element) => [element.dataset.phase, element.getAnimations()[0]?.currentTime]));
	layer.innerHTML = html;
	for (const element of layer.querySelectorAll("[data-steady]")) {
		if (before.has(element.dataset.steady)) element.classList.add("steady");
	}
	for (const element of layer.querySelectorAll("[data-phase]")) {
		const time = phases.get(element.dataset.phase);
		if (typeof time === "number") element.style.setProperty("--phase", `${-time}ms`);
	}
	if (same) {
		let match;
		if (focused.matches("button")) {
			const buttons = [...layer.querySelectorAll("button")];
			// A paging button whose value changes with the page has a steady data-focus-key ("prev", "next"): that comes first.
			match = (focused.dataset.focusKey && buttons.find((button) => button.dataset.focusKey === focused.dataset.focusKey))
				|| buttons.find((button) => ["action", "value", "key", "provider"].every((name, i) => button.dataset[name] === same[i]));
		} else {
			match = [...layer.querySelectorAll("[data-seek]")].find((bar) => bar.dataset.seek === focused.dataset.seek);
		}
		if (match && !match.disabled) match.focus({ preventScroll: true });
		else if (focused.matches("button")) {
			// The page changed (a puzzle opened, the next photo, the article) and that button is gone: focus the slide's main control,
			// so Enter goes on with the game. Never a stand-in like a back button: it would catch the next Enter and leave the slide.
			const main = layer.querySelector("[data-autofocus]:not([disabled]), button.primary:not([disabled])");
			// A paging arrow that went disabled (the first or last month): the other arrow, so the keyboard isn't left without focus.
			(main || (focused.dataset.focusKey && layer.querySelector("button[data-focus-key]:not([disabled])")))?.focus({ preventScroll: true });
		}
	}
	// After a tap, entrances that would wait for the show come in quickly instead (.redrawn in style.css).
	if (tapped) layer.firstElementChild?.classList.add("redrawn");
	setupWidgets(layer);
}

async function sendAction(slide, action, values, provider = slide.dataset.provider) {
	const result = await getJson("/api/action", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ provider, action, values }),
	});
	if (result.html) {
		if (result.id && current) current = { ...current, id: result.id };   // the redrawn slide is now the one to refresh
		const fresh = new DOMParser().parseFromString(result.html, "text/html");
		const effect = fresh.querySelector("[data-effect]");
		if (effect && effects[effect.dataset.effect]) await effects[effect.dataset.effect](slide);
		redraw(layers[front], result.html, true);
		const resumeAfter = layers[front].querySelector("[data-resume-after]");
		if (resumeAfter) keepPaused(parseFloat(resumeAfter.dataset.resumeAfter));   // e.g. game over
	} else if (current && current.refresh) {
		refresh();   // nothing redrawn (e.g. the volume): show the change now, not at the next check
	}
	// The provider's answer in words ("Spotify can't be reached right now", "Added X to the library"): a tap that fails or
	// changes nothing on the slide would seem to do nothing. A slide that already shows it itself (Spotify's queue) doesn't need it twice.
	if (result.message && !layers[front].textContent.includes(result.message)) showMessage(result.message);
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
		// From here on at normal speed: what is running stays as fast as it was (no jump), what starts now isn't changed.
		clearInterval(rateTimer);
		applyRate = () => {};
		layers[front].dataset.rate = 1;
		takeoverTimer = setInterval(checkTakeover, 5000);
	}
	clearTimeout(idleTimer);
	idleTimer = setTimeout(next, seconds * 1000);
}

function stopInteracting() {
	interacting = false;
	idleClick = false;
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

// Tabbing round an interactive slide is using it: the slideshow mustn't move on while someone is looking for a button.
document.addEventListener("focusin", (event) => {
	const slide = interactiveSlide();
	if (slide && !menuIsOpen() && slide.contains(event.target)) keepPaused(idleSeconds(slide));
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
	// Enter on a button reached with the keyboard (Tab, the arrows) presses that button, like any button: not the slide's own
	// Enter below (Catfishing's "Next article", submitting the word). A clicked button is blurred, so only keyboard focus gets here.
	const focused = event.target.closest?.("button");
	if (event.key === "Enter" && slide && focused && slide.contains(focused)) {
		keepPaused(idleSeconds(slide));
		return;   // the browser presses it (a click, handled above)
	}
	// Space on a focused button (or bar, map, photo) presses it, like Enter above, and does nothing else: the browser presses a
	// button when Space is let go, so pausing the slideshow or the music here too would be a second, unwanted action.
	// Space with nothing focused keeps its meaning (below). Not on a slide with free text (Catfishing, Spotify search, the pet's
	// name): there Space types a space, also while a button kept its focus (a guess like "new york" mustn't press Skip).
	if (event.key === " " && slide && !slide.querySelector("[data-input-text]") && !event.ctrlKey && !event.altKey && !event.metaKey) {
		const control = event.target.closest?.("button, [tabindex='0']");
		if (control && slide.contains(control)) {
			keepPaused(idleSeconds(slide));
			return;
		}
	}
	// A button marked data-enter (e.g. Catfishing's "Next article") is pressed by Enter.
	const enter = slide?.querySelector("[data-enter]");
	if (enter && event.key === "Enter" && !event.ctrlKey && !event.altKey && !event.metaKey) {
		event.preventDefault();
		keepPaused(idleSeconds(slide));
		enter.click();
		return;
	}
	if (slide && slide.querySelector("[data-input-text]") && !event.ctrlKey && !event.altKey && !event.metaKey
			&& !(idleClick && event.key.startsWith("Arrow"))) {   // after a click on nothing: the arrows change slides
		const names = { Enter: "ENTER", Backspace: "BACK", " ": "SPACE", Delete: "DELETE",
			ArrowLeft: "LEFT", ArrowRight: "RIGHT", Home: "HOME", End: "END" };
		const key = names[event.key] || event.key;
		// A button that has keyboard focus lets the arrows move between buttons (below) instead of the text cursor.
		const arrowOnButton = event.key.startsWith("Arrow") && event.target.closest?.("button");
		if (!arrowOnButton && (key.length === 1 || Object.values(names).includes(key))) {
			// Typing a character: a button that kept focus lets go, so the next Enter sends the text and doesn't press it.
			if (key.length === 1 || key === "SPACE") event.target.closest?.("button")?.blur();
			event.preventDefault();
			idleClick = false;
			keepPaused(idleSeconds(slide));
			typeKey(slide, key);
			return;
		}
		if (event.key.startsWith("Arrow") && !arrowOnButton) return;   // up and down don't change slides while typing either
	}
	if (slide && slide.querySelector("[data-input-cell]") && !event.ctrlKey && !event.altKey && !event.metaKey) {
		const key = event.key === "Enter" ? "ENTER" : event.key === "Backspace" ? "BACK" : event.key.toUpperCase();
		if (key === "ENTER" || key === "BACK" || /^[A-Z]$/.test(key)) {
			if (/^[A-Z]$/.test(key)) event.target.closest?.("button")?.blur();   // typing a letter: the next Enter submits the word, not the focused key
			event.preventDefault();
			keepPaused(idleSeconds(slide));
			typeKey(slide, key);
			return;
		}
	}
	// A bar with steps (data-step-down/up, Spotify's volume) that has focus: left and right step it.
	const bar = event.target.closest?.("[data-seek][data-step-up]");
	if (bar && slide?.contains(bar) && (event.key === "ArrowLeft" || event.key === "ArrowRight")
			&& !event.ctrlKey && !event.altKey && !event.metaKey) {
		event.preventDefault();
		keepPaused(idleSeconds(slide));
		bar.classList.add("busy");
		sendAction(slide, event.key === "ArrowRight" ? bar.dataset.stepUp : bar.dataset.stepDown, [], bar.dataset.provider)
			.finally(() => bar.classList.remove("busy"));
		return;
	}
	if (event.key.startsWith("Arrow") && event.target.closest?.("input, .leaflet-container")) {   // they move the slider or map
		if (slide?.contains(event.target)) keepPaused(idleSeconds(slide));   // that's using the slide: the slideshow mustn't move on
		return;
	}
	// Up and down scroll a text that's longer than the screen (data-scroll, e.g. a news article).
	const scroller = slide?.querySelector("[data-scroll]");
	if (scroller && (event.key === "ArrowDown" || event.key === "ArrowUp") && !(event.target.closest?.("button") && slide.dataset.arrowsNeedFocus !== undefined)) {   // Spotify lyrics: with a button focused the arrows move between the buttons (below); an article keeps scrolling
		event.preventDefault();
		keepPaused(idleSeconds(slide));
		scroller.scrollBy({ top: (event.key === "ArrowDown" ? 0.6 : -0.6) * scroller.clientHeight, behavior: "smooth" });
		return;
	}
	// On a slide someone is using (a button has focus, or they tapped or typed), the arrow keys move to the nearest button in
	// that direction and never change the slide: at the edge they stay put, and with nothing focused the first one gets focus.
	// Often there's no mouse, so the arrows are how you get around. A slide nobody is using yet: they change slides, as always.
	// A slide marked data-arrows-need-focus (Spotify) only does this once a button has focus: with nothing focused the
	// arrows change slides, even after someone paused the music with the space bar or tapped a button.
	const onButton = event.target.closest?.("button, [data-seek][tabindex]") && slide?.contains(event.target);
	const using = interacting && !idleClick && slide && !("arrowsNeedFocus" in slide.dataset);
	if (event.key.startsWith("Arrow") && slide && (using || onButton)
			&& !event.ctrlKey && !event.altKey && !event.metaKey) {
		event.preventDefault();
		keepPaused(idleSeconds(slide));
		// With nothing focused: the slide's main control, else the first button that isn't a way out (a back button would
		// catch the next Enter and leave the slide).
		const first = () => slide.querySelector("[data-autofocus]:not([disabled]), button.primary:not([disabled])")
			|| [...slide.querySelectorAll("button:not([disabled])")].find((button) =>
				!button.matches(".puzzle-back, .article-back, [data-action='back']"));
		const target = onButton ? nearestButton(slide, event.target, event.key) : first();
		target?.focus();
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
		flashPauseIcon(paused);
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

// Space: a big || (paused) or |> (going on) in the middle of the screen, fading out.
let pauseIcon = null;
function flashPauseIcon(isPaused) {
	pauseIcon?.remove();
	const icon = document.createElement("div");
	icon.className = "pause-icon";
	const label = !isPaused ? "" : permanentPause ? "Paused until you press space again" : `Paused for ${PAUSE_SECONDS / 60} minutes`;
	icon.innerHTML = (isPaused
		? '<svg viewBox="0 0 100 100"><rect x="26" y="20" width="18" height="60" rx="4"/><rect x="56" y="20" width="18" height="60" rx="4"/></svg>'
		: '<svg viewBox="0 0 100 100"><path d="M30 18 L82 50 L30 82 Z" stroke-linejoin="round"/></svg>')
		+ (label ? `<span>${label}</span>` : "");
	document.body.appendChild(icon);
	pauseIcon = icon;
	icon.addEventListener("animationend", () => { icon.remove(); if (pauseIcon === icon) pauseIcon = null; });
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
let menuReturnFocus = null;   // what had focus in the slide when the menu opened: it gets it back when the menu closes
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

let menuOpening = false;   // the menu's data is on its way: a second Esc must not open it twice

async function openMenu() {
	if (menuOpening) return;
	menuOpening = true;
	try {
		menuData = await getJson("/api/menu");
		setPermanentPause(menuData.settings.permanent_pause);
	} catch (error) {
		console.error(error);
		return;   // the menu isn't available right now
	} finally {
		menuOpening = false;
	}
	menuReturnFocus = document.activeElement;
	showCount += 1;   // a slide that is still loading doesn't appear (and close the menu)
	clearTimeout(nextTimer);
	clearTimeout(idleTimer);
	clearInterval(menuTakeoverTimer);
	menuTakeoverTimer = setInterval(checkTakeover, 5000);   // bieruur still starts on time
	menu.hidden = false;
	for (const layer of layers) layer.inert = true;   // Tab and Enter must not reach the slide behind the menu
	menuGroups = {};
	showMenuPage("overview");
	if (menuTab !== "quick") selectMenuTab(menuTab);   // opens on the group it was on
}

// resume = false when a slide was chosen in the menu: that slide sets its own timer.
function closeMenu(resume = true) {
	if (!menuIsOpen()) return;
	menu.hidden = true;
	for (const layer of layers) layer.inert = false;
	menu.innerHTML = "";   // also stops the previews
	clearTimeout(menuIdleTimer);
	clearInterval(menuTakeoverTimer);
	if (resume) {
		carryOn();
		// The menu's buttons are gone, so focus fell to the page: give it back to the slide's button, if that's still there.
		if (menuReturnFocus?.isConnected && layers[front].contains(menuReturnFocus)) menuReturnFocus.focus({ preventScroll: true });
	}
	menuReturnFocus = null;
}

// The slideshow goes on from the slide on screen (after the menu, which stopped its timers).
function carryOn() {
	const slide = interactiveSlide();
	clearTimeout(nextTimer);
	if (interacting && slide) keepPaused(idleSeconds(slide));
	else if (!paused && current) nextTimer = setTimeout(next, current.seconds * 1000);
}

function menuActivity() {
	clearTimeout(menuIdleTimer);
	menuIdleTimer = setTimeout(() => closeMenu(), MENU_IDLE_SECONDS * 1000);
}

// focus: the data-focus of the element to select, e.g. the button that was just pressed.
function showMenuPage(page, focus) {
	if (page === "rotation-item" && !rotationItem(menuData)) page = "rotation";   // its group was deleted (or the slide type is gone)
	const entering = page !== menuPage && !!menu.firstElementChild;   // a new page zooms in; a redraw after a change doesn't, and neither does the first page of a menu just opened (#menu fades in itself: both would double the fade)
	// The same page drawn again after a change (a slide picked for a group): it stays scrolled where it was, not back at the top.
	const scrolled = page === menuPage && focus ? menu.querySelector(".menu-settings, .menu-rotation")?.scrollTop : 0;
	menuPage = page;
	confirming = null;
	const body = menuPages[page](menuData);
	// Settings and Power: the panel carries the shadow, the card inside it has the continuous corners (see .menu-card-panel).
	menu.innerHTML = `<div class="menu-panel menu-page-${page}${entering ? " menu-enter" : ""}">${page === "overview" ? body : `<div class="menu-card-panel squircle">${body}</div>`}</div>`;
	const target = (focus && menu.querySelector(`[data-focus="${focus}"]:not([disabled])`))
		|| menu.querySelector(".menu-tab-content [data-focus]:not([disabled])")   // the overview: the first slide of the group
		|| menu.querySelector("[data-focus]:not([disabled]):not(.menu-back)");
	const scroller = menu.querySelector(".menu-settings, .menu-rotation");
	if (scroller && scrolled) scroller.scrollTop = scrolled;
	target?.focus({ preventScroll: !!scrolled });   // preventScroll: focusing mustn't jump it either (the arrows still scroll, moveMenuFocus)
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
		<button class="menu-card" data-focus="${escapeHtml(focus)}" data-menu="jump" data-value="${escapeHtml(jump)}"${available === false || available === null ? " disabled" : ""}>
			<span class="menu-preview"><span class="menu-preview-card squircle">${available
				? `<iframe src="/preview/${encodeURIComponent(preview)}" tabindex="-1" onload="this.classList.add('loaded')"></iframe>`
				: `<span>${escapeHtml(empty)}</span>`}</span></span>
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
				found ? found.available : status ? undefined : null, found ? found.empty : "…");   // null: still loading (disabled); undefined: no status (e.g. it failed), tappable
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
		const off = data.rotation.slides.filter((slide) => !slide.on).length;
		const toggle = (name, label, note = "") => `
			<button class="menu-row menu-toggle squircle" role="switch" aria-checked="${settings[name]}" data-focus="${name}"
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
					<h2>Slideshow</h2>
					<button class="menu-row menu-row-button squircle" data-focus="rotation" data-menu="page" data-value="rotation">
						<span>Rotation settings of slides<small>Which slides come round, how often and when${off ? ` &middot; ${off} off` : ""}</small></span>
						<span class="menu-row-arrow" aria-hidden="true">&rsaquo;</span>
					</button>
					<div class="menu-row squircle">
						<span>Speed<small>2&times; = every slide is shown half as long</small></span>
						<span class="menu-choices">${data.speeds.map((speed) => `
							<button data-focus="speed-${speed}" data-menu="speed" data-value="${speed}" aria-pressed="${speed === settings.speed}">${speed}&times;</button>`).join("")}
						</span>
					</div>
					${toggle("permanent_pause", "Pause until unpaused", "Space pauses the slideshow; when this is off it goes on by itself after 4 minutes")}
				</section>
				<section>
					<h2>Sound</h2>
					${toggle("muted", "Mute all sound", "Everything on the TV PC: Spotify, greetings, quotes and the bieruur song")}
					${toggle("quotes_aloud", "Read quotes aloud")}
					${toggle("greetings", "Greet people who walk in")}
					<div class="menu-row squircle">
						<span>Volume<small>Of everything, Spotify too</small></span>
						<span class="menu-stepper">
							<button data-focus="volume-down" data-menu="volume" data-value="-10" aria-label="Quieter"${settings.volume <= 0 ? " disabled" : ""}>&minus;</button>
							<output>${settings.volume}%</output>
							<button data-focus="volume-up" data-menu="volume" data-value="10" aria-label="Louder"${settings.volume >= 100 ? " disabled" : ""}>+</button>
						</span>
					</div>
				</section>
			</div>
			<div class="menu-column">
				<section>
					<h2>Today's puzzles</h2>
					${data.puzzles.map((puzzle) => `
					<div class="menu-row squircle">
						<span>${escapeHtml(puzzle.title)}<small>${escapeHtml(puzzle.status)}</small></span>
						<button class="menu-small-button" data-focus="reset-${puzzle.name}" data-menu="reset" data-value="${puzzle.name}"
							data-confirm="Sure?"${puzzle.state === "new" ? " disabled" : ""}>Start over</button>
					</div>`).join("") || '<p class="menu-note">No puzzles today (yet).</p>'}
					${data.puzzles.length > 1 ? `<button class="menu-small-button menu-wide" data-focus="reset-all" data-menu="reset" data-value=""
						data-confirm="Sure? All of them?"${data.puzzles.every((puzzle) => puzzle.state === "new") ? " disabled" : ""}>Start all puzzles over</button>` : ""}
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
			<button class="menu-power-button squircle" data-focus="shutdown" data-menu="power" data-value="shutdown" data-confirm="Press again to shut down">${ICONS.power}<span>Shut down</span></button>
			<button class="menu-power-button squircle" data-focus="restart" data-menu="power" data-value="restart" data-confirm="Press again to restart">${ICONS.restart}<span>Restart</span></button>
		</div>
		<p class="menu-hint">Shuts down or restarts the TV PC</p>`,

	// Settings → "Rotation settings of slides": the groups that take turns, then every slide type, each with a line saying
	// how often and when it comes round (francken_tv/rotation.py). A row opens its own page (below).
	rotation: (data) => {
		const rotation = data.rotation;
		// color: the group's (rotation.py, COLORS), a stripe down the left of its row and of the rows of its slides.
		const row = (focus, value, title, summary, on, color) => `
			<button class="menu-row menu-row-button menu-rotation-row squircle${on ? "" : " off"}${color ? " grouped" : ""}" data-focus="${escapeHtml(focus)}"
				data-menu="rotation_item" data-value="${escapeHtml(value)}"${color ? ` style="--group-color: ${escapeHtml(color)}"` : ""}><span>${escapeHtml(title)}<small>${escapeHtml(summary)}</small></span></button>`;
		return `
		<header class="menu-header">
			<button class="menu-back" data-focus="back" data-menu="back">&larr; Back</button>
			<h1>Rotation settings of slides</h1>
		</header>
		<div class="menu-rotation">
			${rotation.round ? `<p class="menu-note">One full rotation takes about ${escapeHtml(rotation.round)} right now. The times below are how often each slide of that type comes round.</p>` : ""}
			<section>
				<h2>Take turns</h2>
				<p class="menu-note">The slides in a group share one place in the round: the next of them each round.</p>
				<div class="menu-rotation-grid">
					${rotation.groups.map((group, number) => row(`item-group-${number}`, `group:${number}`, group.title, [group.summary, group.often].filter(Boolean).join(" · "), group.on, group.color)).join("")}
					<button class="menu-row menu-row-button menu-rotation-row menu-rotation-new squircle" data-focus="rotation-new-group"
						data-menu="rotation_new_group"><span>+ New group</span></button>
				</div>
			</section>
			<section>
				<h2>Slides</h2>
				<div class="menu-rotation-grid">
					${rotation.slides.map((slide) => row(`item-slide-${slide.name}`, `slide:${slide.name}`, slide.title,
						[slide.summary, slide.often, slide.on && slide.group !== null ? "takes turns" : "", slide.on && slide.note ? "only when needed" : ""].filter(Boolean).join(" · "), slide.on,
						slide.group === null ? "" : rotation.groups[slide.group].color)).join("")}
				</div>
			</section>
			${rotation.changed ? `<button class="menu-small-button menu-wide" data-focus="rotation-reset" data-menu="rotation_reset"
				data-confirm="Sure? All of it?">Reset to default</button>` : ""}
		</div>`;
	},

	// One slide type or group: on or off, how often, which months and days, what time of day. A group also picks its slides.
	"rotation-item": (data) => {
		const rotation = data.rotation;
		const item = rotationItem(data);
		const rule = item.rule;
		const pick = (focus, value, label, pressed) => `
			<button data-focus="${escapeHtml(focus)}" data-menu="rule" data-value="${escapeHtml(value)}" aria-pressed="${pressed}">${escapeHtml(label)}</button>`;
		const custom = Array.isArray(rule.hours);
		const hour = (h) => `${String(h).padStart(2, "0")}:00`;
		const stepper = (field, label) => `
			<div class="menu-row squircle">
				<span>${label}</span>
				<span class="menu-stepper">
					<button data-focus="${field}-down" data-menu="rule" data-value="${field}:-1" aria-label="Earlier">&minus;</button>
					<output>${hour(rule.hours[field === "from" ? 0 : 1])}</output>
					<button data-focus="${field}-up" data-menu="rule" data-value="${field}:1" aria-label="Later">+</button>
				</span>
			</div>`;
		const group = item.kind === "slide" && item.group !== null ? rotation.groups[item.group] : null;
		return `
		<header class="menu-header">
			<button class="menu-back" data-focus="back" data-menu="back">&larr; Back</button>
			<h1>${item.kind === "group" ? `<span class="menu-group-dot" style="--group-color: ${escapeHtml(item.color)}"></span>` : ""}${escapeHtml(item.kind === "group" ? (item.slides.length ? "Group" : "New group") : item.title)}</h1>
		</header>
		<div class="menu-settings">
			<div class="menu-column">
				<section>
					<button class="menu-row menu-toggle squircle" role="switch" aria-checked="${item.on}" data-focus="rule-on" data-menu="rule" data-value="on">
						<span>In the slideshow${item.kind === "group" ? "<small>Off: none of its slides come round</small>" : item.note ? `<small>${escapeHtml(item.note)}</small>` : ""}</span><span class="menu-switch"></span>
					</button>
				</section>
				<section>
					<h2>How often</h2>
					<span class="menu-choices menu-wrap">${rotation.frequencies.map((frequency) =>
						pick(`every-${frequency.value}`, `every:${frequency.value}`, frequency.label, rule.every === frequency.value)).join("")}</span>
					${item.often ? `<p class="menu-note">${item.kind === "group" ? "Its place in the round comes up" : "Each of its slides comes round"} ${escapeHtml(item.often.replace("~", "about "))}, going by the slides and their duration right now</p>` : ""}
					${item.kind === "group" ? '<p class="menu-note">How often the group\'s place comes round; each slide in it also keeps its own rule</p>' : ""}
				</section>
				${item.kind === "group" ? `
				<section>
					<h2>Slides in this group</h2>
					<span class="menu-choices menu-wrap">${rotation.slides.map((slide) =>
						`<button data-focus="member-${escapeHtml(slide.name)}" data-menu="group_member" data-value="${escapeHtml(slide.name)}"
							aria-pressed="${item.slides.includes(slide.name)}">${escapeHtml(slide.title)}</button>`).join("")}</span>
					<p class="menu-note">A slide can be in one group; choosing it here takes it out of another</p>
					<button class="menu-small-button menu-wide" data-focus="group-delete" data-menu="group_delete" data-confirm="Sure?">Delete this group</button>
				</section>` : group ? `
				<section>
					<h2>Takes turns</h2>
					<button class="menu-row menu-row-button squircle grouped" data-focus="open-group" data-menu="rotation_item" data-value="group:${item.group}"
						style="--group-color: ${escapeHtml(group.color)}">
						<span>${escapeHtml(group.title)}<small>One of these per round &middot; ${escapeHtml(group.summary)}</small></span>
						<span class="menu-row-arrow" aria-hidden="true">&rsaquo;</span>
					</button>
				</section>` : ""}
			</div>
			<div class="menu-column">
				<section>
					<h2>Months</h2>
					<span class="menu-choices menu-wrap menu-months">${rotation.months.map((month, index) =>
						pick(`month-${index + 1}`, `month:${index + 1}`, month, rule.months.includes(index + 1))).join("")}</span>
					<span class="menu-choices">${pick("months-all", "months:all", "All year", rule.months.length === 12)}</span>
				</section>
				<section>
					<h2>Days</h2>
					<span class="menu-choices menu-wrap">${rotation.days.map((day, index) => pick(`day-${index}`, `day:${index}`, day, rule.days.includes(index))).join("")}</span>
					<span class="menu-choices">
						${pick("days-weekdays", "days:weekdays", "Mon–Fri", rule.days.join() === "0,1,2,3,4")}
						${pick("days-all", "days:all", "Every day", rule.days.length === 7)}
					</span>
				</section>
				<section>
					<h2>Time of day</h2>
					<span class="menu-choices menu-wrap">
						${pick("hours-any", "hours:any", "All day", rule.hours === "any")}
						${pick("hours-daytime", "hours:daytime", rotation.daytime, rule.hours === "daytime")}
						${pick("hours-nighttime", "hours:nighttime", rotation.nighttime, rule.hours === "nighttime")}
						${pick("hours-custom", "hours:custom", "From… until…", custom)}
					</span>
					${custom ? stepper("from", "From") + stepper("until", "Until") : ""}
					${item.kind === "slide" && item.name === "weather" ? '<p class="menu-note">Outside these hours it still warns for rain</p>' : ""}
				</section>
			</div>
		</div>`;
	},
};

// The slide type or group on the "rotation-item" page: {kind, name or index, title, on, rule, ...}; null if it has gone.
let menuItem = null;   // {kind: "slide", key: name} or {kind: "group", key: number}
function rotationItem(data) {
	if (!menuItem) return null;
	if (menuItem.kind === "slide") {
		const slide = data.rotation.slides.find((candidate) => candidate.name === menuItem.key);
		return slide ? { kind: "slide", ...slide } : null;
	}
	const group = data.rotation.groups[menuItem.key];
	return group ? { kind: "group", index: menuItem.key, ...group } : null;
}

// A press on the rotation-item page -> what to send to the server (rotation.edit() in rotation.py), or null.
function ruleChange(value) {
	const item = rotationItem(menuData);
	if (!item) return null;
	const rule = item.rule;
	const [field, argument] = value.split(":");
	const range = (from, count) => Array.from({ length: count }, (_, i) => from + i);
	let set;
	if (field === "on") set = { on: !item.on };
	else if (field === "every") set = { every: argument };
	else if (field === "month" || field === "day") {
		const list = field === "month" ? rule.months : rule.days;
		const number = Number(argument);
		const chosen = list.includes(number) ? list.filter((n) => n !== number) : [...list, number];
		if (!chosen.length) {   // never at all: that's what the on/off switch is for
			showMessage(field === "month" ? "At least one month" : "At least one day");
			return null;
		}
		set = { [`${field}s`]: chosen };
	} else if (field === "months") set = { months: range(1, 12) };
	else if (field === "days") set = { days: argument === "weekdays" ? range(0, 5) : range(0, 7) };
	else if (field === "hours") set = { hours: argument !== "custom" ? argument : Array.isArray(rule.hours) ? rule.hours : menuData.rotation.daytime_hours };
	else if (field === "from" || field === "until") {
		const hours = [...rule.hours];
		const index = field === "from" ? 0 : 1;
		hours[index] = (hours[index] + Number(argument) + 24) % 24;   // round the clock: 23:00 + 1 is 00:00
		set = { hours };
	}
	return item.kind === "slide" ? { slide: item.name, set } : { group: item.index, set };
}

// Back one page (the Back buttons of the rotation pages, and Esc anywhere): to the button this page was opened with.
function menuBack() {
	if (menuPage === "rotation-item") showMenuPage("rotation", menuItem ? `item-${menuItem.kind}-${menuItem.key}` : null);
	else if (menuPage === "rotation") showMenuPage("settings", "rotation");
	else showMenuPage("overview", menuPage);
}

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
		clearTimeout(menuTabTimer);   // the focus that came with this tap would draw the same group again
		if (value !== menuTab) await selectMenuTab(value);
		menu.querySelector(".menu-tab-content [data-focus]:not([disabled])")?.focus();   // into its slides
		return;
	}
	if (action === "jump") {
		closeMenu(false);
		if (!(await jumpTo(value))) carryOn();   // nothing shown: the menu had stopped the timers, so start them again
	} else if (action === "page") {
		showMenuPage(value, menuPage);   // back to the overview: select the button of the page we came from
	} else if (action === "toggle") {
		sendMenu(button, "settings", { [value]: !settings[value] });
	} else if (action === "volume") {
		sendMenu(button, "settings", { volume: settings.volume + Number(value) });
	} else if (action === "speed") {
		sendMenu(button, "settings", { speed: Number(value) });
	} else if (action === "back") {
		menuBack();
	} else if (action === "rotation_item") {
		const [kind, key] = value.split(/:(.*)/);
		menuItem = { kind, key: kind === "group" ? Number(key) : key };
		showMenuPage("rotation-item");
	} else if (action === "rule") {
		const change = ruleChange(value);
		if (change) sendMenu(button, "rotation", change);
	} else if (action === "group_member") {
		sendMenu(button, "rotation", { group: menuItem.key, toggle: value });
	} else if (action === "rotation_new_group") {
		if (await sendMenu(button, "rotation", { new_group: true }, false)) {   // straight on to its page, to choose its slides
			menuItem = { kind: "group", key: menuData.rotation.groups.length - 1 };
			showMenuPage("rotation-item");
		}
	} else if (action === "group_delete") {
		const number = menuItem.key;
		if (await sendMenu(button, "rotation", { delete_group: number }, false)) {
			menuItem = null;
			showMenuPage("rotation", "rotation-new-group");
		}
	} else if (action === "rotation_reset") {
		sendMenu(button, "rotation", { reset: true });
	} else if (action === "reset") {
		sendMenu(button, "reset_puzzle", value || null);
	} else if (action === "power") {
		sendMenu(button, action, value ?? null);
	}
}

// redraw = false: the caller goes to another page itself. Returns whether it worked.
async function sendMenu(button, command, value, redraw = true) {
	button.classList.add("busy");
	try {
		const answer = await getJson("/api/menu", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ command, value }),
		});
		menuData = answer.menu;
		if (answer.message) showMessage(answer.message);   // "Restarting...", "Reloaded 3 devices": the menu's answer
		setPermanentPause(menuData.settings.permanent_pause);
		if (!redraw || !menuIsOpen()) return true;
		if (menuPage !== "overview") showMenuPage(menuPage, button.dataset.focus);
		else {   // the overview: only the sound controls, so the previews keep playing
			menu.querySelector(".menu-sound")?.replaceWith(...htmlElements(soundControls(menuData.settings)));
			menu.querySelector(`[data-focus="${button.dataset.focus}"]:not([disabled])`)?.focus();
		}
		return true;
	} catch (error) {
		console.error(error);
		showMessage("That didn't work, try again");   // or the tap seems to do nothing
		return false;
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
		else menuBack();   // one page up: Rotation → Settings → the overview
	} else if (event.key.startsWith("Arrow")) {
		event.preventDefault();
		moveMenuFocus(event.key);
	} else if (menuPage === "overview" && /^[0-9]$/.test(event.key)) {
		closeMenu(false);
		jumpTo(event.key).then((shown) => { if (!shown) carryOn(); });   // nothing shown: start the stopped timers again
	} else if (!["Enter", " ", "Tab"].includes(event.key) && !event.ctrlKey && !event.metaKey && !event.altKey && !/^F\d+$/.test(event.key)) {
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
		return;   // the group is still loading: stay on the tab
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
	if (button && !button.disabled && !button.classList.contains("busy")) menuChoose(button);   // a second tap while the answer is on the way would send stale settings
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

// ---- Voice commands ------------------------------------------------------------------------------
// "Hey Katinka, go to the weather" (francken_tv/voice.py, [voice] in config.toml): the server hears it and
// /api/voice hands it over, waiting until there is one. Each does what its key does. A capsule bottom centre
// shows it all: "listening" (the wake words were heard: a microphone until the command comes), then how it
// ended: what it did (a tick and "Pause the music", "Go to Weather"), "didn't catch that", or, when nothing more was
// said within the follow-up seconds, "didn't hear anything".
const listening = document.getElementById("listening");
const listeningText = listening.querySelector(".voice-text");
const VOICE_ANSWER_MS = 2500;   // how long the answer stays: long enough to read from across the room
let listeningTimer = null;

// state: "listening", "done", "unclear" or "nothing" (style.css picks the icon).
function showVoice(state, text, seconds = 8) {
	clearTimeout(listeningTimer);
	const answer = state !== "listening";
	if (answer && listening.classList.contains("on")) {   // it was on screen: a small pop as it changes
		listening.classList.remove("answered");
		void listening.offsetWidth;   // so the animation starts again
		listening.classList.add("answered");
	}
	listening.dataset.state = state;
	listeningText.textContent = text;
	listening.classList.add("on");
	listeningTimer = answer
		? setTimeout(() => listening.classList.remove("on"), VOICE_ANSWER_MS)
		: setTimeout(() => showVoice("nothing", "Didn't hear anything"), seconds * 1000);
}

// "Hey Katinka, help": examples of what to say. It listens without the name meanwhile (voice.py, HELP_SECONDS);
// a command, or that time running out, closes it.
const voiceHelp = document.getElementById("voice-help");
const MIC = '<svg viewBox="0 0 24 24"><rect x="8.5" y="2.5" width="7" height="12" rx="3.5"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3.5"/></svg>';
let voiceHelpTimer = null;

function showVoiceHelp(slides, seconds) {
	const said = (...phrases) => `<p>${phrases.map((phrase) => `“${escapeHtml(phrase)}”`).join(" <span>·</span> ")}</p>`;
	const go = slides.map((slide, at) => said(`${["go to", "show me"][at % 2]} ${slide}`)).join("");
	voiceHelp.innerHTML = `<div class="voice-help-card squircle">
		<h2>${MIC}<span>Say <em>“Kathinka”</em> and then…</span></h2>
		<div class="voice-help-groups">
			<section><h3>Music &amp; sound</h3>${said("pause", "play", "skip")}${said("previous song")}${said("mute", "sound on")}</section>
			<section class="voice-help-go"><h3>Go to a slide</h3>${go}</section>
			<section><h3>Slides</h3>${said("next", "back")}${said("pause the slideshow")}${said("menu", "close")}</section>
		</div>
		<div class="voice-help-foot">Listening: just say one <div class="voice-help-time"><i style="--seconds: ${seconds}s"></i></div></div>
	</div>`;
	voiceHelp.classList.add("on");
	clearTimeout(voiceHelpTimer);
	voiceHelpTimer = setTimeout(hideVoiceHelp, seconds * 1000);
}

function hideVoiceHelp() {
	clearTimeout(voiceHelpTimer);
	voiceHelp.classList.remove("on");
}

async function doVoiceCommand(command) {
	if (command.do === "listening") return showVoice("listening", "Listening", command.seconds);
	if (command.do === "help") {
		clearTimeout(listeningTimer);
		listening.classList.remove("on");   // the card says it's listening
		return showVoiceHelp(command.slides || [], command.seconds || 20);
	}
	const helpOpen = voiceHelp.classList.contains("on");
	hideVoiceHelp();
	if (command.do === "unclear") return showVoice("unclear", "Sorry, I didn't catch that");
	if (command.do === "failed") return showVoice("unclear", command.said);   // e.g. Spotify not reachable
	const menuOpen = menuIsOpen();
	if (command.do === "close") {
		if (menuOpen) closeMenu();
		return showVoice(menuOpen || helpOpen ? "done" : "unclear", menuOpen || helpOpen ? command.said : "Nothing to close");
	}
	if (command.do === "menu") {
		if (!menuOpen) openMenu();
		return showVoice("done", command.said);
	}
	const server = ["mute", "unmute", "pause", "resume", "skip", "previous_song"].includes(command.do);   // sound and the music: done by the server already
	if (menuOpen && !server) closeMenu(command.do !== "go");   // the others are about the slides
	if (command.do === "go") {
		showVoice("done", command.said);   // at once: the slide takes a moment
		if (await jumpTo(`go-${command.slide}`) === null) showVoice("unclear", `${command.said.replace(/^Go to /, "")}: not shown right now`);
		return;
	}
	if (command.do === "pause_slides" || command.do === "resume_slides") {
		const pause = command.do === "pause_slides";
		if (paused === pause) return showVoice("done", `The slideshow is already ${pause ? "paused" : "playing"}`);
		setPaused(pause);
		flashPauseIcon(paused);
		return showVoice("done", command.said);
	}
	showVoice("done", command.said);
	if (command.do === "next") next();
	else if (command.do === "previous") previous();
}

async function listenForVoice() {
	let last = -1;   // -1: from now on (not the commands heard before this page loaded)
	for (;;) {
		try {
			const answer = await getJson(`/api/voice?after=${last}`);
			if (!answer.enabled) return;   // no voice commands ([voice] enabled = false)
			last = answer.last;
			for (const command of answer.commands) await doVoiceCommand(command);
		} catch (error) {
			console.error(error);
			await new Promise((resolve) => setTimeout(resolve, 5000));   // the server restarting: try again
		}
	}
}
listenForVoice();

next();
