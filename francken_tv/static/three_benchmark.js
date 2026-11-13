// The 3D benchmark (providers/three.py, ThreeBenchmarkProvider): loaded by widgets.js when "Start" is tapped on its slide.
// It runs a series of tests, each a ramp of steps that get heavier until a step no longer keeps 60 frames per second, then
// sends the results to the server (POST /api/benchmark), which saves them in benchmarks/.
//
// Every step is drawn for a while after a short warm-up (shaders compile and textures upload then). Per frame we measure the
// *work*: render() followed by a 1-pixel readPixels, which waits for the graphics chip to finish. That makes the time independent
// of vsync (the frame rate stops at the screen's 60 Hz, the work time doesn't). A step "holds 60 fps" when it
// reaches 55 fps and 95% of its frames took 15 ms of work or less.

(() => {
	const WARMUP_MS = 700, MEASURE_MS = 2500;
	const HOLDS_FPS = 55, HOLDS_P95_MS = 15;

	const median = (values) => [...values].sort((a, b) => a - b)[Math.floor(values.length / 2)];
	const percentile95 = (values) => [...values].sort((a, b) => a - b)[Math.min(values.length - 1, Math.floor(values.length * 0.95))];
	const round = (value, digits = 1) => Math.round(value * 10 ** digits) / 10 ** digits;
	const nextFrame = () => new Promise((resolve) => requestAnimationFrame(resolve));
	const number = (n) => n.toLocaleString("en");

	window.threeBenchmark = async function (root, THREE) {
		const canvas = root.querySelector("canvas");
		const status = root.querySelector("[data-tb-status]");
		const bar = root.querySelector("[data-tb-bar]");
		const live = root.querySelector("[data-tb-live]");
		const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: "high-performance" });
		renderer.setPixelRatio(1);
		renderer.setSize(canvas.clientWidth, canvas.clientHeight, false);
		const gl = renderer.getContext();
		const pixel = new Uint8Array(4);
		const sync = () => gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, pixel);   // waits until the chip is done drawing
		const debug = gl.getExtension("WEBGL_debug_renderer_info");

		const info = {
			gpu: debug ? gl.getParameter(debug.UNMASKED_RENDERER_WEBGL) : "unknown",
			webgl2: renderer.capabilities.isWebGL2,
			max_texture_size: renderer.capabilities.maxTextureSize,
			screen: `${screen.width}x${screen.height}`,
			canvas: `${canvas.width}x${canvas.height}`,
			pixel_ratio: devicePixelRatio,
			three: THREE.REVISION,
			browser: navigator.userAgent,
		};

		const alive = () => { if (!document.contains(canvas)) throw new Error("the slide is gone"); };

		function free(rig) {
			rig.scene.traverse((o) => {
				o.geometry?.dispose();
				if (o.isInstancedMesh) o.dispose();
				for (const material of [o.material].flat()) { material?.map?.dispose(); material?.dispose(); }
			});
			rig.scene.clear();
			rig.dispose?.();
			renderer.renderLists.dispose();
		}

		// Draws a rig for WARMUP_MS + MEASURE_MS and returns what it took.
		async function measure(rig) {
			renderer.render(rig.scene, rig.camera);   // the first frame: shaders compile and textures upload
			sync();
			const first = performance.now();
			renderer.render(rig.scene, rig.camera);
			sync();
			const firstMs = performance.now() - first;
			const works = [];
			const started = await nextFrame();
			let measuring = null, frames = 0, end = started;
			for (;;) {
				const now = await nextFrame();
				alive();
				rig.update?.((now - started) / 1000);
				const before = performance.now();
				renderer.render(rig.scene, rig.camera);
				sync();
				const work = performance.now() - before;
				if (now - started < WARMUP_MS) continue;
				measuring ??= now;
				works.push(work);
				frames++;
				end = now;
				live.textContent = `${Math.round(frames * 1000 / Math.max(1, now - measuring))} fps, ${round(median(works))} ms of work per frame`;
				if (now - measuring >= MEASURE_MS) break;
			}
			const fps = frames * 1000 / (end - measuring);
			const p95 = percentile95(works);
			return {
				fps: round(fps, 0), work_ms: round(median(works)), p95_ms: round(p95), first_ms: round(firstMs, 0),
				triangles: renderer.info.render.triangles, calls: renderer.info.render.calls,
				holds: fps >= HOLDS_FPS && p95 <= HOLDS_P95_MS,
			};
		}

		// ---- The rigs: each makes a scene for one step. -------------------------------------------------------------------
		const cubeGrid = (count, spacing) => {   // positions in a cube of cells, and how far the camera must be to see it all
			const side = Math.ceil(Math.cbrt(count));
			return { side, at: (i) => [(i % side - side / 2) * spacing, (Math.floor(i / side) % side - side / 2) * spacing, (Math.floor(i / side / side) - side / 2) * spacing], far: side * spacing * 1.7 + 4 };
		};
		const lights = (scene) => {
			scene.add(new THREE.HemisphereLight(0x88aaff, 0x221133, 1));
			const sun = new THREE.DirectionalLight(0xffffff, 2.5);
			sun.position.set(10, 20, 15);
			scene.add(sun);
			return sun;
		};
		const camera = (far = 30) => {
			const cam = new THREE.PerspectiveCamera(50, canvas.clientWidth / canvas.clientHeight, 0.1, far * 4);
			cam.position.set(0, far * 0.3, far);
			cam.lookAt(0, 0, 0);
			return cam;
		};
		const SPHERE = [16, 12], SPHERE_TRIANGLES = 16 * 12 * 2 - 2 * 16;   // 352

		// Triangles: instanced spheres, standing still (only the whole cube turns). Unlit or lit.
		function trianglesRig(triangles, lit) {
			const count = Math.ceil(triangles / SPHERE_TRIANGLES);
			const scene = new THREE.Scene();
			scene.background = new THREE.Color(0x02060f);
			if (lit) lights(scene);
			const mesh = new THREE.InstancedMesh(new THREE.SphereGeometry(0.4, ...SPHERE), lit ? new THREE.MeshStandardMaterial({ roughness: 0.4, metalness: 0.2 }) : new THREE.MeshBasicMaterial(), count);
			const grid = cubeGrid(count, 1);
			const matrix = new THREE.Matrix4(), colour = new THREE.Color();
			for (let i = 0; i < count; i++) {
				matrix.makeTranslation(...grid.at(i));
				mesh.setMatrixAt(i, matrix);
				mesh.setColorAt(i, colour.setHSL(i / count, 0.8, 0.55));
			}
			scene.add(mesh);
			return { scene, camera: camera(grid.far), update: (t) => { mesh.rotation.y = t * 0.3; } };
		}

		// Draw calls: many small separate meshes sharing one material.
		function drawCallsRig(count) {
			const scene = new THREE.Scene();
			scene.background = new THREE.Color(0x02060f);
			lights(scene);
			const geometry = new THREE.IcosahedronGeometry(0.4, 0), material = new THREE.MeshStandardMaterial({ roughness: 0.4, metalness: 0.2 });
			const grid = cubeGrid(count, 1.1), group = new THREE.Group();
			for (let i = 0; i < count; i++) {
				const mesh = new THREE.Mesh(geometry, material);
				mesh.position.set(...grid.at(i));
				mesh.matrixAutoUpdate = false;
				mesh.updateMatrix();
				group.add(mesh);
			}
			scene.add(group);
			return { scene, camera: camera(grid.far), update: (t) => { group.rotation.y = t * 0.3; } };
		}

		// Shadows: the same lit scene of about 100,000 triangles with a shadow map of a size (0: no shadows).
		function shadowsRig(size) {
			const scene = new THREE.Scene();
			scene.background = new THREE.Color(0x0a1020);
			const sun = lights(scene);
			renderer.shadowMap.enabled = size > 0;
			renderer.shadowMap.type = THREE.PCFSoftShadowMap;
			if (size > 0) {
				sun.castShadow = true;
				sun.shadow.mapSize.set(size, size);
				Object.assign(sun.shadow.camera, { left: -16, right: 16, top: 16, bottom: -16, near: 1, far: 70 });
			}
			const count = Math.ceil(100000 / SPHERE_TRIANGLES);
			const mesh = new THREE.InstancedMesh(new THREE.SphereGeometry(0.5, ...SPHERE), new THREE.MeshStandardMaterial({ roughness: 0.4 }), count);
			const matrix = new THREE.Matrix4();
			for (let i = 0; i < count; i++) mesh.setMatrixAt(i, matrix.makeTranslation((i % 20 - 10) * 1.4, Math.floor(i / 20) % 3 * 1.4, (Math.floor(i / 60) - 2.5) * 1.4));
			mesh.castShadow = mesh.receiveShadow = true;
			const floor = new THREE.Mesh(new THREE.PlaneGeometry(60, 60), new THREE.MeshStandardMaterial({ color: 0x223355, roughness: 0.8 }));
			floor.rotation.x = -Math.PI / 2;
			floor.position.y = -2;
			floor.receiveShadow = true;
			scene.add(mesh, floor);
			return { scene, camera: camera(26), update: (t) => { mesh.rotation.y = t * 0.2; }, dispose: () => { renderer.shadowMap.enabled = false; } };
		}

		// Overdraw: see-through additive layers, each as big as the screen, on top of each other.
		function overdrawRig(layers) {
			const scene = new THREE.Scene();
			const cam = camera(14);
			cam.position.set(0, 0, 14);
			cam.lookAt(0, 0, 0);
			const planes = [], geometry = new THREE.PlaneGeometry(40, 24);
			for (let i = 0; i < layers; i++) {
				const plane = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({ color: new THREE.Color().setHSL(i / layers, 0.8, 0.5), transparent: true, opacity: 0.08, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide }));
				plane.position.z = -i * 0.1;
				planes.push(plane);
				scene.add(plane);
			}
			return { scene, camera: cam, update: (t) => planes.forEach((p, i) => { p.rotation.z = Math.sin(t * 0.3 + i * 0.1) * 0.3; }) };
		}

		// Textures: that many different 512x512 pictures (like book covers) on quads. The first frame is when they upload.
		function texturesRig(count, size = 512) {
			const scene = new THREE.Scene();
			scene.background = new THREE.Color(0x101010);
			const cols = Math.ceil(Math.sqrt(count * 16 / 9)), rows = Math.ceil(count / cols);
			const geometry = new THREE.PlaneGeometry(0.9, 0.9);
			for (let i = 0; i < count; i++) {
				const picture = document.createElement("canvas");
				picture.width = picture.height = size;
				const c = picture.getContext("2d");
				c.fillStyle = `hsl(${i * 37 % 360} 70% 50%)`;
				c.fillRect(0, 0, size, size);
				for (let k = 0; k < 40; k++) {   // so no two pictures (or mipmaps) are alike or trivially small
					c.fillStyle = `hsl(${(i * 37 + k * 9) % 360} 60% ${20 + k % 5 * 12}%)`;
					c.fillRect(Math.random() * size, Math.random() * size, size / 4, size / 8);
				}
				c.fillStyle = "#fff";
				c.font = `${size / 3}px sans-serif`;
				c.fillText(String(i), size / 8, size / 1.6);
				const mesh = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(picture) }));
				mesh.position.set(i % cols - cols / 2 + 0.5, rows / 2 - Math.floor(i / cols) - 0.5, 0);
				scene.add(mesh);
			}
			const cam = new THREE.PerspectiveCamera(50, canvas.clientWidth / canvas.clientHeight, 0.1, 500);
			cam.position.z = Math.max(rows, cols / (canvas.clientWidth / canvas.clientHeight)) / 2 / Math.tan(25 * Math.PI / 180) + 1;
			return { scene, camera: cam };
		}

		// ---- The tests. --------------------------------------------------------------------------------------------------
		const results = [];
		const plan = [];   // [title, steps, make(step) -> rig, label(step), options]
		const tris = (n) => `${number(n)} triangles`;
		plan.push(["Triangles, unlit", [250e3, 500e3, 1e6, 2e6, 4e6, 8e6], (n) => trianglesRig(n, false), tris, "ramp"]);
		plan.push(["Triangles, lit (2 lights)", [250e3, 500e3, 1e6, 2e6, 4e6], (n) => trianglesRig(n, true), tris, "ramp"]);
		plan.push(["Separate meshes (draw calls)", [250, 500, 1000, 2000, 4000], drawCallsRig, (n) => `${number(n)} meshes`, "ramp"]);
		plan.push(["Shadows (100,000 triangles)", [0, 512, 1024, 2048, 4096], shadowsRig, (n) => n ? `shadow map ${n}x${n}` : "no shadows", "all"]);
		plan.push(["Overdraw (see-through layers)", [10, 20, 40, 80], overdrawRig, (n) => `${n} full-screen layers`, "ramp"]);
		plan.push(["Textures (512x512 pictures)", [10, 40, 100, 200], texturesRig, (n) => `${n} textures`, "ramp"]);
		plan.push(["One big texture", [2048, 4096, 8192], (n) => texturesRig(1, n), (n) => `${n}x${n} texture`, "all"]);

		const steps = plan.reduce((sum, p) => sum + p[1].length, 0) + 3;   // + the instance updates
		let done = 0;
		const progress = (text) => { status.textContent = text; bar.style.width = `${Math.min(100, Math.round(done / steps * 100))}%`; };

		for (const [title, values, make, label, kind] of plan) {
			const test = { title, kind, steps: [] };
			for (const value of values) {
				alive();
				progress(`${title}: ${label(value)}`);
				live.textContent = "";
				let rig;
				try {
					rig = make(value);
					test.steps.push({ label: label(value), ...await measure(rig) });
				} catch (error) {
					if (!document.contains(canvas)) throw error;
					test.steps.push({ label: label(value), error: String(error.message || error), holds: false });   // e.g. out of memory
				} finally {
					if (rig) free(rig);
					done++;
				}
				const last = test.steps.at(-1);
				if (kind === "ramp" && !last.holds) {
					done += values.length - 1 - values.indexOf(value);   // the heavier steps are skipped
					break;
				}
			}
			if (title.startsWith("Overdraw")) {   // does a lower resolution help? Run the first step that failed again at half the pixels.
				const failed = test.steps.find((s) => !s.holds);
				if (failed) {
					progress(`${title}: ${failed.label} at 50% resolution`);
					renderer.setPixelRatio(0.5);
					renderer.setSize(canvas.clientWidth, canvas.clientHeight, false);
					const rig = overdrawRig(Number(failed.label.split(" ")[0]));
					test.steps.push({ label: `${failed.label}, drawn at 50% resolution`, ...await measure(rig) });
					free(rig);
					renderer.setPixelRatio(1);
					renderer.setSize(canvas.clientWidth, canvas.clientHeight, false);
				}
			}
			const held = test.steps.filter((s) => s.holds);
			test.best = kind === "ramp" ? (held.length ? held.at(-1).label : "none held 60 fps, even the first step") : undefined;
			results.push(test);
		}

		// The CPU: moving thousands of instances in JavaScript every frame, as the wave scenes do (no drawing).
		const cpu = { title: "Moving instances from JavaScript (CPU, every frame)", kind: "all", steps: [] };
		for (const count of [6000, 20000, 60000]) {
			alive();
			progress(`${cpu.title}: ${number(count)} instances`);
			await nextFrame();
			const mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(), new THREE.MeshBasicMaterial(), count);
			const matrix = new THREE.Matrix4(), times = [];
			for (let run = 0; run < 15; run++) {
				const begin = performance.now();
				for (let i = 0; i < count; i++) mesh.setMatrixAt(i, matrix.makeTranslation(i % 100, Math.sin(i * 0.1 + run) * 2, i / 100));
				mesh.instanceMatrix.needsUpdate = true;
				times.push(performance.now() - begin);
			}
			mesh.dispose();
			const ms = median(times.slice(3));
			cpu.steps.push({ label: `${number(count)} instances`, work_ms: round(ms, 2), holds: ms <= 4 });
			done++;
		}
		cpu.best = "";
		results.push(cpu);

		renderer.dispose();
		return { when: new Date().toISOString(), ...info, tests: results };
	};
})();
