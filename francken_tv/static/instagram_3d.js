// The Instagram slide's phone in real 3D (templates/slides/instagram.html, providers/instagram.py), drawn with Three.js
// (static/vendor/three).
//
// The phone comes up from below the screen and stands turned a little towards the "Follow us" side, swaying slowly.
// Its screen shows the feed as on the HTML phone: the profile, then the latest posts. It starts at the bottom (the
// oldest post); one post at a time scrolls to the middle and lifts out of the screen towards the room, turning to face
// it, while the feed behind it dims; it hovers there for a while (a video keeps playing on it), then sinks back in and
// the feed scrolls on to the next. After the newest it scrolls up to the profile.
//
// WebGL can't show HTML, so the feed is drawn on canvases from the HTML phone's contents (one texture for the profile,
// one per post); a video is a plane with a VideoTexture over its post's picture. The feed is kept inside the screen by
// the stencil buffer (the screen marks its pixels, the feed only draws there); a lifted post leaves it. The <video>
// elements themselves move to a tiny holder behind the phone: Firefox stops decoding a video it can't see.
//
// Kept within what the TV PC can do (docs/07-3d-limits.md): about 12 draw calls, a few thousand triangles, no shadows,
// one canvas over the right part of the slide only. It does draw every frame (the feed scrolls, videos play), so a post
// out of view isn't drawn at all (its video isn't uploaded either), and if frames are over 20 ms in its first seconds it
// drops to 75% resolution. Without WebGL the slide keeps the HTML phone (style.css).
//
// One unit in the 3D world is 1vh: the camera is DISTANCE in front of the screen, so at z = 0 the world is the size of
// the page. The phone stands where the (hidden) HTML .ig-phone is, and is its size.

const INSTAGRAM_3D = {
	distance: 140,   // the camera, in front of the screen
	px: 16,   // texture pixels per vh
	enter: 1.6,   // s: the first post lifts out (the phone has landed)
	lift: 0.8, sink: 0.7, scroll: 1.0,   // s
	top: 1.2, rest: 1.4,   // s: the scroll up to the profile at the end, and the moment after it
	yaw: -16,   // degrees: turned towards the "Follow us" side
};

function setupInstagram3d(canvas) {
	const slide = canvas.closest(".instagram-slide");
	loadThree().then((THREE) => {
		if (document.contains(canvas)) drawInstagram3d(THREE, canvas, slide);
	}).catch((error) => console.warn("Instagram in 3D:", error));   // the HTML phone stays
}

async function drawInstagram3d(THREE, canvas, slide) {
	let renderer;
	try {
		renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true, stencil: true, powerPreference: "high-performance" });
	} catch (error) {
		return console.warn("Instagram in 3D: no WebGL", error);
	}
	// From here on the 3D phone takes over: the HTML phone stays in place, invisible, to say where the 3D one goes.
	// Hidden at once, not after the loading below: player.js doesn't wait for the fonts or the videos' covers, and the
	// slide mustn't appear with the HTML phone and then jump to 3D.
	slide.classList.add("ig-3d-on");
	const phoneHtml = slide.querySelector(".ig-phone");
	const font = getComputedStyle(slide).fontFamily;
	await document.fonts.ready;
	// What's on the HTML phone, for the textures (pictures decoded first: this runs before player.js waits for them).
	const loadImage = async (src) => {
		if (!src) return null;
		const img = new Image();
		img.src = src;
		return img.decode().then(() => img, () => null);
	};
	const text = (root, selector) => root.querySelector(selector)?.textContent.trim() ?? "";
	const avatar = await loadImage(slide.querySelector(".ig-avatar.big")?.getAttribute("src"));
	const profile = {
		username: text(slide, ".ig-topbar b"),
		name: text(slide, ".ig-name"),
		counts: [...slide.querySelectorAll(".ig-counts span")].map((span) => [text(span, "b"), span.lastChild.textContent.trim()]),
		avatar,
	};
	const posts = await Promise.all([...slide.querySelectorAll(".ig-post")].map(async (article) => {
		const video = article.querySelector("video");
		return {
			...article.dataset,   // ago, likes, comments, caption, kind
			username: profile.username,
			avatar,
			picture: await loadImage(video ? video.getAttribute("poster") : article.querySelector(".ig-picture img")?.getAttribute("src")),
			video,
			album: (await Promise.all(JSON.parse(article.dataset.album || "[]").map(loadImage))).filter(Boolean),   // an album's pictures
		};
	}));
	// The newest story (if there's one live): played at the end, after a tap on the profile picture.
	const storyHtml = slide.querySelector(".ig-story");
	let story = storyHtml && { picture: await loadImage(storyHtml.dataset.picture), video: storyHtml.querySelector("video"),
		ago: storyHtml.dataset.ago ?? "", username: profile.username, avatar };
	if (!story?.picture) story = null;
	profile.story = Boolean(story);
	if (!document.contains(canvas) || !posts.length) {
		slide.classList.remove("ig-3d-on");
		return renderer.dispose();
	}

	const vh = innerHeight / 100;
	const box = canvas.getBoundingClientRect();
	const phoneBox = phoneHtml.getBoundingClientRect();
	const width = box.width / vh, height = box.height / vh;
	const { distance, px } = INSTAGRAM_3D;
	const onPage = (x, y) => ({ x: (x - box.left) / vh - width / 2, y: height / 2 - (y - box.top) / vh });
	// The videos, kept decoding in a holder behind the middle of the phone (the canvas covers it).
	const holder = document.createElement("div");
	holder.className = "ig-video-holder";
	holder.style.left = `${phoneBox.left + phoneBox.width / 2 - slide.getBoundingClientRect().left}px`;
	holder.style.top = `${phoneBox.top + phoneBox.height / 2 - slide.getBoundingClientRect().top}px`;
	slide.append(holder);
	posts.forEach((post) => post.video && holder.append(post.video));
	if (story?.video) holder.append(story.video);

	let quality = 1;
	const resize = () => {
		renderer.setPixelRatio(devicePixelRatio * quality);
		renderer.setSize(canvas.clientWidth, canvas.clientHeight, false);
	};
	resize();
	const camera = new THREE.PerspectiveCamera(2 * Math.atan(height / 2 / distance) * 180 / Math.PI, width / height, 10, 1000);
	camera.position.set(0, 0, distance);
	const scene = new THREE.Scene();
	const textures = [];
	const texture = (t) => {
		t.colorSpace = THREE.SRGBColorSpace;
		t.anisotropy = 4;
		textures.push(t);
		return t;
	};
	const deg = Math.PI / 180;

	// Light for the phone's body: white from the front left, Instagram pink and orange from the sides (the glows).
	scene.add(new THREE.HemisphereLight(0xffffff, 0x302040, 1.6));
	const key = new THREE.DirectionalLight(0xfff4ea, 2.4);
	key.position.set(-6, 5, 8);
	const pink = new THREE.DirectionalLight(0xe1306c, 3);
	pink.position.set(8, -2, -3);
	const orange = new THREE.DirectionalLight(0xfcaf45, 2);
	orange.position.set(-8, 6, -4);
	scene.add(key, pink, orange);

	// The phone: a body with continuous corners and rounded edges, its front at z = 0; the screen in it, the HTML
	// phone's padding (1.4vh) from the edge.
	const W = phoneBox.width / vh, H = phoneBox.height / vh;
	const bezel = 1.4, sw = W - 2 * bezel, sh = H - 2 * bezel;
	const bevel = 0.9, depth = 3;
	const bodyGeometry = new THREE.ExtrudeGeometry(squircleShape(THREE, W - 2 * bevel, H - 2 * bevel, 9.6 - bevel), {
		depth, bevelEnabled: true, bevelThickness: bevel, bevelSize: bevel, bevelSegments: 5, curveSegments: 6,
	});
	bodyGeometry.translate(0, 0, -depth - bevel);
	smoothNormals(bodyGeometry, 60);
	const phone = new THREE.Group();
	phone.add(new THREE.Mesh(bodyGeometry, new THREE.MeshStandardMaterial({ color: 0x2a2a33, roughness: 0.3, metalness: 0.6 })));
	scene.add(phone);

	// Stencil: the screen marks its pixels with 1; the feed is drawn only there (clipped to the screen's corners too).
	// Everything on the screen is drawn in renderOrder, without depth: "transparent" puts it all in one list (Three.js
	// draws the see-through dimming after every solid thing otherwise, over the lifted post too).
	const inScreen = { stencilWrite: true, stencilRef: 1, stencilFunc: THREE.EqualStencilFunc, depthTest: false, depthWrite: false, transparent: true };
	const flat = (geometry, material, order, z) => {
		const mesh = new THREE.Mesh(geometry, material);
		mesh.renderOrder = order;
		mesh.position.z = z;
		phone.add(mesh);
		return mesh;
	};
	flat(new THREE.ShapeGeometry(squircleShape(THREE, sw, sh, 7.7), 12), new THREE.MeshBasicMaterial({
		color: 0xffffff, stencilWrite: true, stencilRef: 1, stencilFunc: THREE.AlwaysStencilFunc, stencilZPass: THREE.ReplaceStencilOp,
	}), 1, 0.02);

	// The feed: the profile, then the posts, newest first; `top` is each one's distance from the top of the feed (vh).
	const items = [];
	let feedHeight = 0;
	const addItem = (drawing, post = null) => {
		const h = drawing.height / px;
		const material = new THREE.MeshBasicMaterial({ map: texture(new THREE.CanvasTexture(drawing)), ...inScreen });
		const mesh = flat(cardGeometry(THREE, sw, h, post ? 3.8 : 0.01), material, 2, 0.05);
		const item = { mesh, h, top: feedHeight, post, lift: 0 };
		if (post?.video) {   // over the picture, from when the video has a frame
			const video = new THREE.Mesh(new THREE.PlaneGeometry(sw, sw * 1.25), new THREE.MeshBasicMaterial({
				map: texture(new THREE.VideoTexture(post.video)), ...inScreen,
			}));
			video.position.set(0, h / 2 - POST_HEADER - sw * 0.625, 0.01);
			video.renderOrder = 3;
			mesh.add(video);
			item.video = video;
		}
		if (post?.album.length > 1) {   // an album: a carousel over the picture, and its dots, both moving only while lifted out
			const pictures = post.album.map((image) => {
				const { canvas: drawing, ctx } = feedCanvas(sw, sw * 1.25, px);
				drawCover(ctx, image, 0, 0, sw, sw * 1.25);
				return texture(new THREE.CanvasTexture(drawing));
			});
			const picture = new THREE.Mesh(new THREE.PlaneGeometry(sw, sw * 1.25), new THREE.ShaderMaterial({
				uniforms: { a: { value: pictures[0] }, b: { value: pictures[1] }, slide: { value: 0 } },
				vertexShader: PLANE_VERTEX, fragmentShader: CAROUSEL_FRAGMENT, ...inScreen,
			}));
			picture.position.set(0, h / 2 - POST_HEADER - sw * 0.625, 0.01);
			const n = pictures.length;
			const dots = new THREE.Mesh(new THREE.PlaneGeometry(n * ALBUM_DOT_STEP, ALBUM_DOT_STEP), new THREE.ShaderMaterial({
				uniforms: { count: { value: n }, at: { value: 0 }, on: { value: new THREE.Color("#0095f6") }, off: { value: new THREE.Color("#a8a8a8") } },
				vertexShader: PLANE_VERTEX, fragmentShader: DOTS_FRAGMENT, ...inScreen,
			}));
			dots.position.set(0, h / 2 - POST_HEADER - sw * 1.25 - ALBUM_DOTS_Y, 0.01);
			mesh.add(picture, dots);
			item.album = { picture, dots, pictures };
		}
		items.push(item);
		feedHeight += h;
	};
	addItem(profileCanvas(profile, sw, px, font));
	posts.forEach((post) => addItem(postCanvas(post, sw, px, font), post));

	// While a post is lifted out: the feed behind it dims, and the post's soft shadow falls on it.
	const dim = flat(new THREE.PlaneGeometry(sw, sh), new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0, ...inScreen }), 5, 0.1);
	const shadow = flat(new THREE.PlaneGeometry(sw + 8, 80 + 8), new THREE.MeshBasicMaterial({
		map: texture(shadowTexture(THREE, sw, 80, 4)), transparent: true, opacity: 0, ...inScreen,
	}), 6, 0.12);
	// The camera notch, over the feed.
	const notch = new THREE.Shape();
	notch.absarc(3.3, 0, 1.2, -Math.PI / 2, Math.PI / 2, false);
	notch.absarc(-3.3, 0, 1.2, Math.PI / 2, Math.PI * 1.5, false);
	flat(new THREE.ShapeGeometry(notch, 8), new THREE.MeshBasicMaterial({ color: 0x000000, ...inScreen }), 7, 0.15).position.y = sh / 2 - 2.4;

	// The story: the profile picture is tapped (a shade over it, a moment), the story grows out of it to the whole
	// screen (picture or video, with the bar, the name and how long ago on top), the bar fills while it plays, and it
	// shrinks back into the picture, whose ring is grey from then on (seen), as on Instagram. Under the notch.
	let stories = null;
	if (story) {
		const group = new THREE.Group();
		group.position.z = 0.13;
		phone.add(group);
		const layer = (geometry, map, order, options = {}) => {
			const mesh = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({ map, ...inScreen, ...options }));
			mesh.renderOrder = order;
			group.add(mesh);
			return mesh;
		};
		const pictureCanvas = feedCanvas(sw, sh, px);
		pictureCanvas.ctx.fillStyle = "#000000";
		pictureCanvas.ctx.fillRect(0, 0, sw, sh);
		drawCover(pictureCanvas.ctx, story.picture, 0, 0, sw, sh);
		const parts = [layer(cardGeometry(THREE, sw, sh, 7.7), texture(new THREE.CanvasTexture(pictureCanvas.canvas)), 6.2)];
		const video = story.video && layer(new THREE.PlaneGeometry(sw, sh), texture(new THREE.VideoTexture(story.video)), 6.3);
		if (video) parts.push(video);
		parts.push(layer(cardGeometry(THREE, sw, sh, 7.7), texture(new THREE.CanvasTexture(storyOverlayCanvas(story, sw, sh, px, font))), 6.4));
		const bar = layer(new THREE.PlaneGeometry(1, STORY_BAR.h), null, 6.5, { color: 0xffffff });
		bar.position.y = sh / 2 - STORY_BAR.y - STORY_BAR.h / 2;
		parts.push(bar);
		// On the profile picture (its middle, on the profile's card): the shade of the tap, and the grey ring of a seen story.
		const shade = flat(new THREE.CircleGeometry(AVATAR.d / 2, 40), new THREE.MeshBasicMaterial({ color: 0x000000, opacity: 0, ...inScreen }), 5.5, 0.11);
		const seen = flat(new THREE.RingGeometry(AVATAR.d / 2 - 0.4, AVATAR.d / 2, 64), new THREE.MeshBasicMaterial({ color: 0xc7c7c7, ...inScreen }), 5.6, 0.11);
		stories = { group, parts, video, bar, shade, seen, cropped: false, started: false };
	}

	// The timeline. The feed's scroll (how far it is moved up, vh): at first the bottom of the feed at the bottom of
	// the screen; for each post (oldest first) the post in the middle of the screen as far as the feed allows; at the
	// end the top. Each post: scroll to it, lift it out, hold, sink back.
	const seconds = Number(canvas.dataset.seconds) || 20;
	const { enter, lift, sink, scroll, top, rest } = INSTAGRAM_3D;
	const lowest = Math.max(feedHeight - sh, 0);
	const scrollTo = (item) => Math.min(Math.max(item.top + item.h / 2 - sh / 2, 0), lowest);
	const order = items.slice(1).reverse();   // the posts, oldest first
	// An album hovers album-seconds longer for each picture after the first (the server made the slide that much longer
	// too); the rest of the time is shared out equally over the posts' holds.
	const storySeconds = story ? Number(canvas.dataset.storySeconds) || 7 : 0;   // the server made the slide that much longer
	const fixed = order.length * (lift + sink) + (order.length - 1) * scroll + top + storySeconds + rest;
	const extra = (item) => (Number(canvas.dataset.albumSeconds) || 3) * ((item.album?.pictures.length ?? 1) - 1);
	const shared = (seconds - enter - fixed - order.reduce((sum, item) => sum + extra(item), 0)) / order.length;
	let next = enter;
	const steps = order.map((item, k) => {
		const start = next;   // its lift; the scroll to it is just before
		const end = start + lift + Math.max(shared, 1) + extra(item) + sink;
		next = end + scroll;
		return (item.step = { item, from: k ? scrollTo(order[k - 1]) : lowest, to: scrollTo(item), start, end });
	});
	// Which album picture is shown (fractions: between two, swiping), while it hovers: each for as long, swiped on
	// like Instagram does (ALBUM.swipe), and at the end swiped back to the first, so it sinks back as it came.
	const ALBUM = { swipe: 0.45, back: 0.6, margin: 0.15 };
	const albumAt = (step, n, t) => {
		const from = step.start + lift, to = step.end - sink - ALBUM.margin;
		const each = (to - ALBUM.back - from) / n;
		let at = 0;
		for (let k = 1; k < n; k++) at += scrollEase(clamp((t - (from + k * each - ALBUM.swipe)) / ALBUM.swipe));
		return at - (n - 1) * scrollEase(clamp((t - (to - ALBUM.back)) / ALBUM.back));
	};
	const scrollEase = cubicBezier(0.42, 0, 0.58, 1), liftEase = cubicBezier(0.2, 0.9, 0.3, 1.2), enterEase = cubicBezier(0.2, 0.9, 0.3, 1.1);
	const clamp = (x) => Math.min(Math.max(x, 0), 1);
	const scrollAt = (t) => {
		let s = lowest;
		for (const { from, to, start } of steps) if (t > start - scroll) s = from + (to - from) * scrollEase(clamp((t - start + scroll) / scroll));
		const last = steps.at(-1);
		if (last && t > last.end) s = last.to * (1 - scrollEase(clamp((t - last.end) / top)));
		return s;
	};

	// The story, after the scroll up to the profile: the tap (0.15 to 0.45 s in), opening (0.35 to 0.75 s), playing, and
	// closing in the last STORY_CLOSE s.
	const storyAt = (steps.at(-1)?.end ?? enter) + top;
	const openEase = cubicBezier(0.2, 0.8, 0.3, 1), closeEase = cubicBezier(0.4, 0, 1, 1);
	const poseStory = (t, s) => {
		const { group, parts, video, bar, shade, seen } = stories;
		const x = t - storyAt;
		const avatarX = -sw / 2 + AVATAR.x + AVATAR.d / 2, avatarY = sh / 2 + s - AVATAR.y - AVATAR.d / 2;
		shade.position.set(avatarX, avatarY, 0.11);
		seen.position.set(avatarX, avatarY, 0.11);
		shade.material.opacity = 0.3 * Math.sin(Math.PI * clamp((x - 0.15) / 0.3));
		seen.visible = x > storySeconds - 0.1;
		const open = openEase(clamp((x - 0.35) / 0.4)) * (1 - closeEase(clamp((x - storySeconds + STORY_CLOSE) / STORY_CLOSE)));
		group.visible = open > 0.001;
		const small = AVATAR.d / sw;
		group.scale.setScalar(small + (1 - small) * open);
		group.position.set(avatarX * (1 - open), avatarY * (1 - open), 0.13);
		parts.forEach((part) => { part.material.opacity = clamp(open * 3); });
		const played = clamp((x - 0.75) / (storySeconds - 0.75 - STORY_CLOSE));
		const barWidth = sw - 2 * STORY_BAR.x;
		bar.scale.x = Math.max(played * barWidth, 0.001);
		bar.position.x = -sw / 2 + STORY_BAR.x + bar.scale.x / 2;
		if (video) {
			const element = video.material.map.image;
			if (x > 0.35 && !stories.started) {   // from its start as it opens
				stories.started = true;
				element.currentTime = 0;
				element.play().catch(() => {});
			}
			if (!stories.cropped && element.videoWidth) {   // filling the screen, as object-fit: cover
				stories.cropped = true;
				const map = video.material.map, wide = (element.videoWidth / element.videoHeight) / (sw / sh);
				if (wide > 1) map.repeat.set(1 / wide, 1); else map.repeat.set(1, wide);
				map.offset.set((1 - map.repeat.x) / 2, (1 - map.repeat.y) / 2);
			}
			video.visible = open > 0.999 && element.readyState >= 2;   // a rectangle: only once the story fills the screen
		}
	};

	const anchor = onPage(phoneBox.left + phoneBox.width / 2, phoneBox.top + phoneBox.height / 2);
	const pose = (t) => {
		// The phone comes up from below (a little turned and tilted on its way), then sways and bobs slowly.
		const e = enterEase(clamp((t - 0.2) / 1.0));
		const yaw = (INSTAGRAM_3D.yaw + swing(t / 6) * 5 - (1 - e) * 25) * deg;
		const pitch = (-3 + swing((t + 2) / 5) * 2) * deg;
		phone.position.set(anchor.x, anchor.y + (1 - e) * -(height + H) / 2 + swing(t / 4) * 1.2, 0);
		phone.rotation.set(pitch, yaw, (1 - e) * 8 * deg);

		const s = scrollAt(t);
		let lifted = 0, liftedItem = null;
		for (const step of steps) {
			const up = liftEase(clamp((t - step.start) / lift)), down = scrollEase(clamp((t - step.end + sink) / sink));
			step.item.lift = up * (1 - down);
			if (step.item.lift > lifted) [lifted, liftedItem] = [step.item.lift, step.item];
		}
		for (const item of items) {
			const y = sh / 2 + s - item.top - item.h / 2;   // its middle, on the phone
			const out = item.lift > 0.01 && Math.abs(y) + item.h / 2 <= sh / 2 + 0.5;   // only a post wholly on the screen leaves it
			const { mesh } = item;
			// Lifted: towards the room (along the screen's normal), a little bigger, turned to face the room, gently rocking.
			mesh.position.set(0, y, 0.05 + item.lift * 22);
			mesh.rotation.set(-pitch * item.lift, -yaw * item.lift, Math.sin(t * 1.3) * 1.2 * deg * item.lift);
			mesh.scale.setScalar(1 + item.lift * 0.06);
			mesh.renderOrder = out ? 10 : 2;
			mesh.visible = out || Math.abs(y) - item.h / 2 < sh / 2;   // not drawn (or its video uploaded) off the screen
			for (const part of [mesh, item.video, item.album?.picture, item.album?.dots].filter(Boolean)) {
				part.material.stencilWrite = !out;
				if (part !== mesh) part.renderOrder = out ? 11 : 3;
			}
			if (item.video) item.video.visible = item.post.video.readyState >= 2;   // the picture under it until it has a frame
			if (item.album) {   // in the feed the card shows the first picture and its dots itself
				const { picture, dots, pictures } = item.album;
				picture.visible = dots.visible = item.lift > 0.001;
				const at = Math.min(Math.max(albumAt(item.step, pictures.length, t), 0), pictures.length - 1);
				const first = Math.min(Math.floor(at), pictures.length - 2);
				picture.material.uniforms.a.value = pictures[first];
				picture.material.uniforms.b.value = pictures[first + 1];
				picture.material.uniforms.slide.value = at - first;
				dots.material.uniforms.at.value = Math.round(at);
			}
		}
		if (stories) poseStory(t, s);
		dim.material.opacity = 0.35 * clamp(lifted);
		shadow.material.opacity = 0.9 * clamp(lifted);
		if (liftedItem) {
			shadow.position.set(1.5 * lifted, liftedItem.mesh.position.y - 2.5 * lifted, 0.12);
			shadow.scale.y = (liftedItem.h + 8) / 88;
		}
	};
	// The shaders and the feed's pictures go to the graphics card now, while the slide is still loading, not in its first
	// frame (that would stutter at the start of the phone's entrance). Before the first pose: compile() skips what is
	// hidden, and that hides the albums' carousels. The videos' textures have no frame yet: they go when drawn.
	renderer.compile(scene, camera);
	textures.filter((t) => !t.isVideoTexture).forEach((t) => renderer.initTexture(t));
	pose(0);

	// One frame at a time while the slide is on the page; freed when it's gone (the browser has only a few WebGL contexts).
	const layer = canvas.closest(".layer");
	let started = null, measured = false;
	const times = [];
	const frame = (now) => {
		if (!document.contains(canvas)) {
			textures.forEach((t) => t.dispose());
			scene.traverse((o) => { o.geometry?.dispose(); o.material?.dispose(); });
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
		// Too slow for this PC? Measure from 0.5 to 3 s (the phone coming in, the first post lifting) and drop to 75% once.
		if (!measured && t > 0.5) {
			times.push(now);
			if (t > 3) {
				measured = true;
				const gaps = times.slice(1).map((time, n) => time - times[n]).sort((p, q) => p - q);
				if (gaps[Math.floor(gaps.length / 2)] > 20) {
					quality = 0.75;
					resize();
					console.info("Instagram in 3D: slow frames, drawing at 75% resolution");
				}
			}
		}
	};
	requestAnimationFrame(frame);
}

// A w x h outline (centred on 0, 0) with continuous corners reaching r along each edge: the same construction as
// .squircle in style.css (a circle arc of radius r / 1.6 between gentle curves, Apple's and Figma's 60% smoothing).
function squircleShape(THREE, w, h, r) {
	const shape = new THREE.Shape();
	const hw = w / 2, hh = h / 2;
	r = Math.min(r, hw, hh);
	// Each corner: its point k, u back along the edge coming in, v along the edge going out.
	const corners = [
		{ k: [hw, -hh], u: [-1, 0], v: [0, 1] },
		{ k: [hw, hh], u: [0, -1], v: [-1, 0] },
		{ k: [-hw, hh], u: [1, 0], v: [0, -1] },
		{ k: [-hw, -hh], u: [0, 1], v: [1, 0] },
	];
	const at = ({ k, u, v }, a, b) => [k[0] + a * r * u[0] + b * r * v[0], k[1] + a * r * u[1] + b * r * v[1]];
	shape.moveTo(...at(corners[0], 1, 0));
	for (const c of corners) {
		if (c !== corners[0]) shape.lineTo(...at(c, 1, 0));
		shape.bezierCurveTo(...at(c, 0.65, 0), ...at(c, 0.475, 0), ...at(c, 0.3413, 0.0681));
		const [cx, cy] = at(c, 0.625, 0.625), [sx, sy] = at(c, 0.3413, 0.0681), [ex, ey] = at(c, 0.0681, 0.3413);
		const a0 = Math.atan2(sy - cy, sx - cx);
		let turn = Math.atan2(ey - cy, ex - cx) - a0;
		turn = Math.atan2(Math.sin(turn), Math.cos(turn));   // the short way round
		for (let n = 1; n <= 4; n++) shape.lineTo(cx + 0.625 * r * Math.cos(a0 + turn * n / 4), cy + 0.625 * r * Math.sin(a0 + turn * n / 4));
		shape.bezierCurveTo(...at(c, 0, 0.475), ...at(c, 0, 0.65), ...at(c, 0, 1));
	}
	return shape;
}

// Shade smooth: ExtrudeGeometry's triangles share no vertices, so each has its own flat normal and the rounded sides
// and bevel show as facets (on a shiny body, in coloured light, very much so). Each vertex gets the average normal of
// the faces at the same point that bend less than `crease` degrees from its own. The flat front and back (normal along
// z) keep theirs: their triangles all run to the outline, so a tilted normal there would shade the whole face.
function smoothNormals(geometry, crease) {
	const position = geometry.attributes.position, normal = geometry.attributes.normal;
	const limit = Math.cos(crease * Math.PI / 180);
	const key = (i) => `${Math.round(position.getX(i) * 1000)},${Math.round(position.getY(i) * 1000)},${Math.round(position.getZ(i) * 1000)}`;
	const flat = (i) => Math.abs(normal.getZ(i)) > 0.999;
	const at = new Map();
	for (let i = 0; i < position.count; i++) {
		const k = key(i);
		if (!at.has(k)) at.set(k, []);
		at.get(k).push(i);
	}
	const smooth = new Float32Array(position.count * 3);
	for (let i = 0; i < position.count; i++) {
		const [nx, ny, nz] = [normal.getX(i), normal.getY(i), normal.getZ(i)];
		let sx = nx, sy = ny, sz = nz;
		if (!flat(i)) {
			sx = sy = sz = 0;
			for (const j of at.get(key(i))) {
				const [mx, my, mz] = [normal.getX(j), normal.getY(j), normal.getZ(j)];
				if (flat(j) || mx * nx + my * ny + mz * nz < limit) continue;
				sx += mx;
				sy += my;
				sz += mz;
			}
			const length = Math.hypot(sx, sy, sz) || 1;
			[sx, sy, sz] = [sx / length, sy / length, sz / length];
		}
		smooth.set([sx, sy, sz], i * 3);
	}
	normal.array.set(smooth);   // only now: the loop above still read the flat normals
	normal.needsUpdate = true;
}

// A flat card with continuous corners, its texture over the whole card.
function cardGeometry(THREE, w, h, r) {
	const geometry = new THREE.ShapeGeometry(squircleShape(THREE, w, h, r), 8);
	const position = geometry.attributes.position, uv = geometry.attributes.uv;
	for (let n = 0; n < position.count; n++) uv.setXY(n, position.getX(n) / w + 0.5, position.getY(n) / h + 0.5);
	return geometry;
}

// The posts as on the HTML phone (style.css, "Instagram"), in vh: a header, the picture (4:5), the likes and comments,
// and the caption (at most 3 lines).
const POST_HEADER = 7.2;
const AVATAR = { x: 2, y: 11.1, d: 11 };   // vh: the profile picture on the profile's card (top left corner, size)
const STORY_BAR = { x: 1.2, y: 4.2, h: 0.35 };   // vh: the story's bar, from the top of the screen (under the notch)
const STORY_CLOSE = 0.4;   // s

// What's on top of a story (see-through elsewhere): a shade at the top, the bar's track, the avatar, the name, how long ago.
function storyOverlayCanvas({ avatar, username, ago }, w, h, px, font) {
	const canvas = document.createElement("canvas");
	canvas.width = Math.round(w * px);
	canvas.height = Math.round(h * px);
	const ctx = canvas.getContext("2d");
	ctx.scale(px, px);
	const shade = ctx.createLinearGradient(0, 0, 0, 14);
	shade.addColorStop(0, "rgba(0, 0, 0, 0.45)");
	shade.addColorStop(1, "rgba(0, 0, 0, 0)");
	ctx.fillStyle = shade;
	ctx.fillRect(0, 0, w, 14);
	ctx.fillStyle = "rgba(255, 255, 255, 0.35)";
	ctx.fillRect(STORY_BAR.x, STORY_BAR.y, w - 2 * STORY_BAR.x, STORY_BAR.h);
	drawAvatar(ctx, avatar, 1.6, 5.6, 4.2);
	ctx.textBaseline = "middle";
	ctx.fillStyle = "#ffffff";
	ctx.font = `bold 2.1px ${font}`;
	ctx.fillText(username, 6.6, 7.7);
	const nameWidth = ctx.measureText(username).width;
	ctx.fillStyle = "rgba(255, 255, 255, 0.75)";
	ctx.font = `1.8px ${font}`;
	ctx.fillText(ago, 6.6 + nameWidth + 1.2, 7.7);
	return canvas;
}
const ALBUM_DOTS_Y = 2.85, ALBUM_DOT_STEP = 1.2;   // vh: the album's dots, below the picture, from the middle
// A plane with its texture coordinates, for the shaders below.
const PLANE_VERTEX = `
	varying vec2 vUv;
	void main() {
		vUv = uv;
		gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
	}`;
// An album's carousel: picture a slid `slide` (0 to 1) of its width to the left, picture b coming in after it, as on
// Instagram (one plane, so the pictures are cut off at its edges by themselves).
const CAROUSEL_FRAGMENT = `
	uniform sampler2D a;
	uniform sampler2D b;
	uniform float slide;
	varying vec2 vUv;
	void main() {
		float x = vUv.x + slide;
		gl_FragColor = mix(texture2D(a, vec2(x, vUv.y)), texture2D(b, vec2(x - 1.0, vUv.y)), step(1.0, x));
		#include <colorspace_fragment>
	}`;
// An album's dots on white (over the ones drawn on the card): `count` in a row, dot `at` lit.
const DOTS_FRAGMENT = `
	uniform float count;
	uniform float at;
	uniform vec3 on;
	uniform vec3 off;
	varying vec2 vUv;
	void main() {
		float x = vUv.x * count;
		float d = length(vec2(fract(x) - 0.5, vUv.y - 0.5));   // in steps between the dots (the plane is one step high)
		vec3 colour = abs(floor(x) - at) < 0.5 ? on : off;
		gl_FragColor = vec4(mix(colour, vec3(1.0), smoothstep(0.22, 0.27, d)), 1.0);
		#include <colorspace_fragment>
	}`;
// The album's dots: for each, where it is from the middle (vh), and whether it's lit when picture `at` is shown.
function albumDots(n) {
	return Array.from({ length: n }, (_, i) => [(i - (n - 1) / 2) * ALBUM_DOT_STEP, (at) => Math.round(at) === i]);
}
const HEART = "M12 21s-7.5-4.6-9.6-9.2C.9 8.5 2.9 4.5 6.7 4.5c2.2 0 3.6 1.2 5.3 3.1 1.7-1.9 3.1-3.1 5.3-3.1 3.8 0 5.8 4 4.3 7.3C19.5 16.4 12 21 12 21Z";
const BUBBLE = "M21 11.5a8.5 8.5 0 0 1-12.6 7.4L3 20.5l1.6-5.2A8.5 8.5 0 1 1 21 11.5Z";

function feedCanvas(w, h, px) {
	const canvas = document.createElement("canvas");
	canvas.width = Math.round(w * px);
	canvas.height = Math.round(h * px);
	const ctx = canvas.getContext("2d");
	ctx.scale(px, px);   // drawn in vh from here on
	ctx.fillStyle = "#ffffff";
	ctx.fillRect(0, 0, w, h);
	ctx.textBaseline = "middle";
	return { canvas, ctx };
}

// An image filling a w x h box as object-fit: cover does; grey without one.
function drawCover(ctx, image, x, y, w, h) {
	if (!image) {
		ctx.fillStyle = "#eeeeee";
		return ctx.fillRect(x, y, w, h);
	}
	const scale = Math.max(w / image.naturalWidth, h / image.naturalHeight);
	const iw = w / scale, ih = h / scale;
	ctx.drawImage(image, (image.naturalWidth - iw) / 2, (image.naturalHeight - ih) / 2, iw, ih, x, y, w, h);
}

function drawAvatar(ctx, image, x, y, d) {
	ctx.save();
	ctx.beginPath();
	ctx.arc(x + d / 2, y + d / 2, d / 2, 0, 2 * Math.PI);
	ctx.clip();
	drawCover(ctx, image, x, y, d, d);
	if (!image) {
		ctx.fillStyle = "#dddddd";
		ctx.fillRect(x, y, d, d);
	}
	ctx.restore();
}

function profileCanvas({ username, name, counts, avatar, story }, w, px, font) {
	const h = 27.9;
	const { canvas, ctx } = feedCanvas(w, h, px);
	ctx.fillStyle = "#111111";
	ctx.font = `bold 2.9px ${font}`;
	ctx.fillText(username, 2, 6 + 1.75);
	// The big avatar, in Instagram's gradient ring when there's a story.
	const ay = AVATAR.y, d = AVATAR.d;
	if (!story) drawAvatar(ctx, avatar, AVATAR.x, ay, d);
	else {
		const ring = ctx.createLinearGradient(2, ay + d, 2 + d, ay);
		[["#fcaf45", 0], ["#f77737", 0.25], ["#e1306c", 0.55], ["#c13584", 0.75], ["#833ab4", 1]].forEach(([c, at]) => ring.addColorStop(at, c));
		ctx.fillStyle = ring;
		ctx.beginPath();
		ctx.arc(2 + d / 2, ay + d / 2, d / 2, 0, 2 * Math.PI);
		ctx.fill();
		ctx.fillStyle = "#ffffff";
		ctx.beginPath();
		ctx.arc(2 + d / 2, ay + d / 2, d / 2 - 0.4, 0, 2 * Math.PI);
		ctx.fill();
		drawAvatar(ctx, avatar, 2.8, ay + 0.8, d - 1.6);
	}
	// The counts, each a number over a word, side by side.
	ctx.textAlign = "center";
	let x = 2 + d + 2.4;
	for (const [number, word] of counts) {
		ctx.font = `bold 2.7px ${font}`;
		const nw = ctx.measureText(number).width;
		ctx.font = `2px ${font}`;
		const cw = Math.max(nw, ctx.measureText(word).width);
		ctx.fillStyle = "#111111";
		ctx.font = `bold 2.7px ${font}`;
		ctx.fillText(number, x + cw / 2, ay + d / 2 - 1.3);
		ctx.fillStyle = "#444444";
		ctx.font = `2px ${font}`;
		ctx.fillText(word, x + cw / 2, ay + d / 2 + 1.4);
		x += cw + 3.6;
	}
	if (!counts.length) {   // no counts (not shown by Instagram): a Follow button in their place
		ctx.fillStyle = "#0095f6";
		ctx.beginPath();
		ctx.roundRect(x, ay + d / 2 - 2.4, w - 2 - x, 4.8, 1.2);
		ctx.fill();
		ctx.fillStyle = "#ffffff";
		ctx.font = `bold 2.2px ${font}`;
		ctx.textAlign = "center";
		ctx.fillText("Follow", x + (w - 2 - x) / 2, ay + d / 2);
		ctx.textAlign = "left";
	}
	ctx.textAlign = "left";
	ctx.fillStyle = "#111111";
	ctx.font = `bold 2.2px ${font}`;
	ctx.fillText(name, 2, ay + d + 1.4 + 1.3);
	ctx.fillStyle = "#e5e5e5";
	ctx.fillRect(0, h - 0.1, w, 0.1);
	return canvas;
}

function postCanvas(post, w, px, font) {
	// The caption's lines first, for the height: "username" in bold, then the caption, the first line after the name.
	const measure = document.createElement("canvas").getContext("2d");
	measure.font = `bold 2px ${font}`;
	const lead = measure.measureText(`${post.username} `).width;
	measure.font = `2px ${font}`;
	const lines = captionLines(measure, post.caption ?? "", w - 4, lead, 3);
	const pictureH = w * 1.25;
	const actionsY = POST_HEADER + pictureH;
	const h = actionsY + 4.9 + (lines.length ? 0.5 + lines.length * 2.7 : 0) + 1.6;
	const { canvas, ctx } = feedCanvas(w, h, px);

	// The header: the avatar, the name, how long ago.
	drawAvatar(ctx, post.avatar ?? null, 2, 1.4, 4.4);
	ctx.fillStyle = "#111111";
	ctx.font = `bold 2.1px ${font}`;
	ctx.fillText(post.username, 7.6, 3.6);
	ctx.fillStyle = "#8e8e8e";
	ctx.font = `1.8px ${font}`;
	ctx.textAlign = "right";
	ctx.fillText(post.ago ?? "", w - 2, 3.6);
	ctx.textAlign = "left";

	// The picture (a video's cover; the video plays over it), with a mark for a video or an album.
	drawCover(ctx, post.picture, 0, POST_HEADER, w, pictureH);
	const mark = { VIDEO: "▶", CAROUSEL_ALBUM: "❐" }[post.kind];
	if (mark) {
		ctx.font = `2.7px ${font}`;
		ctx.textAlign = "right";
		ctx.shadowColor = "rgba(0, 0, 0, 0.6)";
		ctx.shadowBlur = 0.6 * px;
		ctx.fillStyle = "#ffffff";
		ctx.fillText(mark, w - 1.4, POST_HEADER + 2.8);
		ctx.shadowColor = "transparent";
		ctx.textAlign = "left";
	}

	// The likes (a red heart) and the comments (a bubble).
	let x = 2;
	const icon = (path, filled, number) => {
		ctx.save();
		ctx.translate(x, actionsY + 1.3);
		ctx.scale(3.1 / 24, 3.1 / 24);
		ctx.lineWidth = 2;
		ctx.lineJoin = "round";
		const p = new Path2D(path);
		if (filled) {
			ctx.fillStyle = ctx.strokeStyle = "#ff3040";
			ctx.fill(p);
		} else ctx.strokeStyle = "#111111";
		ctx.stroke(p);
		ctx.restore();
		ctx.fillStyle = "#111111";
		ctx.font = `bold 2.1px ${font}`;
		ctx.fillText(number, x + 3.7, actionsY + 1.3 + 1.55);
		x += 3.7 + ctx.measureText(number).width + 2.4;
	};
	if (post.likes) icon(HEART, true, post.likes);
	icon(BUBBLE, false, post.comments ?? "0");
	// An album: a dot per picture in the middle of the row, the first one blue (the 3D carousel moves them).
	if (post.album.length > 1) albumDots(post.album.length).forEach(([x, on]) => {
		ctx.fillStyle = on(0) ? "#0095f6" : "#a8a8a8";
		ctx.beginPath();
		ctx.arc(w / 2 + x, actionsY + ALBUM_DOTS_Y, 0.3, 0, 2 * Math.PI);
		ctx.fill();
	});

	// The caption, with the name in bold in front of its first line.
	ctx.fillStyle = "#111111";
	lines.forEach((line, n) => {
		const y = actionsY + 4.9 + 0.5 + (n + 0.5) * 2.7;
		ctx.font = `2px ${font}`;
		ctx.fillText(line, n ? 2 : 2 + lead, y);
		if (n === 0) {
			ctx.font = `bold 2px ${font}`;
			ctx.fillText(post.username, 2, y);
		}
	});
	return canvas;
}

// The words of `text` in lines no wider than `width` (the first `indent` less), at most `most` lines (the last one cut
// off with an ellipsis).
function captionLines(ctx, text, width, indent, most) {
	const lines = [];
	let line = "";
	for (const word of text.split(/\s+/).filter(Boolean)) {
		const longer = line ? `${line} ${word}` : word;
		if (ctx.measureText(longer).width <= width - (lines.length ? 0 : indent) || !line) line = longer;
		else {
			lines.push(line);
			line = word;
		}
	}
	if (line) lines.push(line);
	if (lines.length > most) {
		let last = lines.slice(most - 1).join(" ");
		while (last && ctx.measureText(`${last}\u2026`).width > width) last = last.slice(0, -1);
		lines.splice(most - 1, Infinity, `${last.trimEnd()}\u2026`);
	}
	return lines;
}
