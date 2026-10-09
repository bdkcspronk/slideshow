import grp
import subprocess
import time
import sys
import os
import shlex
import shutil

UPDATE_INTERVAL_SECONDS = 300
PIO_PYTHON = os.path.expanduser("~/.platformio/penv/bin/python")


def ensure_platformio_python():
    if (
        os.path.abspath(sys.executable) == os.path.abspath(PIO_PYTHON)
        or not os.path.isfile(PIO_PYTHON)
    ):
        return

    os.execv(PIO_PYTHON, [PIO_PYTHON, os.path.abspath(__file__), *sys.argv[1:]])


def ensure_dialout_access():
    dialout_gid = grp.getgrnam('dialout').gr_gid
    if dialout_gid in os.getgroups() or os.environ.get(
        'SNIFFER_DIALOUT_REEXEC'
    ):
        return

    sg_executable = shutil.which('sg')
    if sg_executable is None:
        return

    environment = os.environ.copy()
    environment['SNIFFER_DIALOUT_REEXEC'] = '1'
    command = ' '.join(
        shlex.quote(argument)
        for argument in [sys.executable, os.path.abspath(__file__), *sys.argv[1:]]
    )
    os.execvpe(sg_executable, ['sg', 'dialout', '-c', command], environment)


ensure_platformio_python()
ensure_dialout_access()

import os
from pathlib import Path
import subprocess
import time
import sys


def has_required_modules(python_executable, required_modules):
    check_command = [
        python_executable,
        '-c',
        'import ' + ','.join(required_modules),
    ]
    result = subprocess.run(
        check_command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def find_python_executable(required_modules):
    candidates = [
        sys.executable,
        str(Path(__file__).parent / '.venv' / 'Scripts' / 'python.exe'),
        os.path.expanduser(
            r'~\.platformio\penv\Scripts\python.exe'
        ),
    ]

    checked_candidates = set()
    for candidate in candidates:
        if candidate in checked_candidates:
            continue
        checked_candidates.add(candidate)

        if (
            Path(candidate).is_file()
            and has_required_modules(candidate, required_modules)
        ):
            return candidate

    raise RuntimeError(
        'No Python environment with the required project dependencies was found.'
    )


LOGGER_PYTHON = find_python_executable(('serial',))
PLOTTER_PYTHON = find_python_executable(('pandas', 'matplotlib'))

# Check whether the user passed '--all' to this main script
arguments = sys.argv[1:]

print("=" * 60)
print("  ESP32 SNIFFER & LIVE PLOTTER SCRIPT")
print("=" * 60)

# 1. Start the logging script in the background
log_command = [LOGGER_PYTHON, "filter_logs.py"] + arguments
voice_command = [LOGGER_PYTHON, "voice_announcer.py"]

voice_process = subprocess.Popen(voice_command)
log_process = subprocess.Popen(log_command)

print("   Port ttyUSB0 opened and logging live data.")
print("-" * 60)

# 2. Start the infinite loop to generate the graph
try:
    # Generate an initial graph immediately at startup
    print(f"[{time.strftime('%H:%M:%S')}] Generating initial graph...")
    subprocess.run([PLOTTER_PYTHON, "plot_activity.py"])
    
    while True:
        time.sleep(UPDATE_INTERVAL_SECONDS) 
        
        print(f"\n[{time.strftime('%H:%M:%S')}] 5 minutes elapsed. Updating graph live...")
        
        # Call plot_activity.py with the default Anaconda Python
        subprocess.run([PLOTTER_PYTHON, "plot_activity.py"])

except KeyboardInterrupt:
    print("\n\n🛑 Ctrl+C detected! Shutting down the system...")
    
    # Close the background logging process cleanly so ttyUSB0 becomes available again
    log_process.terminate()
    log_process.wait()
    voice_process.terminate()
    voice_process.wait()
    
    print("🔒 ttyUSB0 closed successfully. Logger stopped. Goodbye!")
