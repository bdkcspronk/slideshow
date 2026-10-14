// Plays the slides the server sends, one after another.
// What is shown, and for how long, is decided in Python (francken_tv/scheduler.py);
// this file only loads each slide, fades it in, and waits.
//
// Keys: right/down = next, left/up = previous, space = pause, m = read quotes aloud on/off.
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

async function getJson(url, options) {
	const response = await fetch(url, options);
	if (!response.ok) throw new Error(`${url}: ${response.status}`);
	return response.json();
}

async function show(slide, { canRefresh = true } = {}) {
	clearTimeout(nextTimer);
	clearInterval(refreshTimer);
	const back = layers[1 - front];
	back.innerHTML = slide.html;
	// Wait until the images are decoded, so slides never appear half-loaded.
	await Promise.all([...back.querySelectorAll("img")].map((img) => img.decode().catch(() => {})));
	const old = layers[front];
	back.classList.add("visible");
	old.classList.remove("visible");
	front = 1 - front;
	setTimeout(() => { if (!old.classList.contains("visible")) old.innerHTML = ""; }, 1000);

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
		const slide = await getJson("/api/current");
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
