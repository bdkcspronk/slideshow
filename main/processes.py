import os
import shutil
import subprocess
import sys

from .config import RUN_SYSTEM_SCRIPT, SNIFFER_DIR, TERMINAL_EMULATORS


def start_system_terminal() -> subprocess.Popen[bytes]:
	environment = os.environ.copy()
	environment["LIBGL_ALWAYS_SOFTWARE"] = "1"
	for terminal_name, option in TERMINAL_EMULATORS:
		terminal = shutil.which(terminal_name)
		if terminal is not None:
			return subprocess.Popen(
				[
					terminal,
					option,
					sys.executable,
					str(RUN_SYSTEM_SCRIPT),
				],
				cwd=SNIFFER_DIR,
				env=environment,
				start_new_session=True,
			)

	raise OSError("No supported terminal emulator was found")