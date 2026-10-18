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
	root.querySelectorAll("[data-marquee]").forEach(setupMarquee);
	root.querySelectorAll("[data-marquee-up]").forEach(setupMarqueeUp);
	root.querySelectorAll("input[type=range][data-field]").forEach((input) => {
		input.addEventListener("input", () => fieldChanged(input));
		fieldChanged(input);
	});
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
