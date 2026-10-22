"""Start the slideshow server: python -m francken_tv

Then open http://127.0.0.1:8080 in a browser (deploy/kiosk.sh does this full-screen).
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path

from . import keyboard
from .app import build_app
from .clock import Clock
from .config import DEFAULT_CONFIG, load_config
from .server import Server
from .updater import Updater

log = logging.getLogger("francken_tv")


def main() -> None:
	parser = argparse.ArgumentParser(description="Francken TV slideshow server")
	parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
	parser.add_argument("--fake-time", type=datetime.fromisoformat, metavar='"YYYY-MM-DD HH:MM"',
		help="pretend it is this moment (try a Friday just before bieruur)")
	parser.add_argument("--port", type=int, help="override server.port from the config")
	parser.add_argument("--debug", action="store_true", help="more logging")
	args = parser.parse_args()
	logging.basicConfig(
		level=logging.DEBUG if args.debug else logging.INFO,
		format="%(asctime)s %(levelname)s %(name)s: %(message)s",
	)

	config = load_config(args.config)
	app = build_app(config, Clock(args.fake_time))
	server_settings = config.get("server", {})
	host, port = server_settings.get("host", "127.0.0.1"), args.port or server_settings.get("port", 8080)
	server = Server(app, host, port)
	app.runner.start()
	signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))   # systemd stop: shut down cleanly below
	log.info("Slideshow running on http://%s:%d (status: /status)", host, port)
	restarting = threading.Event()

	def restart() -> None:   # Ctrl+R: stop serving; below, everything is shut down and started again
		log.info("Restarting the slideshow")
		restarting.set()
		threading.Thread(target=server.shutdown, daemon=True).start()

	def busy(now: datetime) -> bool:
		"""Bieruur (or vrijmibo) is on or starts within 15 minutes, or its song plays: don't restart now."""
		for takeover in app.takeovers.values():
			start = takeover.next_start(now)
			if takeover.due(now) or (start is not None and start - now < timedelta(minutes=15)):
				return True
		music = app.announcer.music_process
		return music is not None and music.poll() is None

	updater = Updater(config.get("update", {}), app.clock.now, busy, restart)
	updater.start()   # push to GitHub, and the TV runs it within minutes ([update] in config.toml)
	restore_terminal = keyboard.listen(app, restart)
	try:
		server.serve_forever()
	except KeyboardInterrupt:
		pass
	finally:
		restore_terminal()
		updater.stopped.set()
		app.runner.stop()
		app.announcer.stop_music()
		server.server_close()
	if restarting.is_set():
		# The same command again (same options), as a fresh program: new code and config are read.
		# The browser keeps trying until the server is back. Same process, so start.sh still stops it.
		sys.stdout.flush()
		os.execv(sys.executable, [sys.executable, *sys.orig_argv[1:]])


if __name__ == "__main__":
	main()
