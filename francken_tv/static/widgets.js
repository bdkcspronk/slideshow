// Widgets inside slides, set up by setupWidgets() after a slide is drawn (player.js) or in a
// preview (preview.html):
// - data-map: a Leaflet map (static/vendor/leaflet) with tiles from data-tiles. Tapping it puts a
//   pin there and makes "lat,lng" its value. With data-pins ({"guess": [lat, lng], "answer": [...]})
//   it shows both pins and a line between them instead (e.g. TimeGuessr's answer).
// - data-field: a value that an action button with data-send-fields sends along, in page order: a
//   map's pin, or an <input type="range">. [data-field-output="name"] shows a field's value,
//   data-nudge="name" buttons change a range by data-by, and data-needs-fields buttons stay
//   disabled until every field has a value.

const maps = new Set();

function setupWidgets(root) {
	for (const map of maps) {   // maps of slides that are gone
		if (!document.contains(map.getContainer())) {
			map.remove();
			maps.delete(map);
		}
	}
	root.querySelectorAll("[data-map]").forEach(setupMap);
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
