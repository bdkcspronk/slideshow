import json
import grp
import os
import shlex
import time
import sys
import shutil

PIO_PYTHON = os.path.expanduser('~/.platformio/penv/bin/python')


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

import serial

# Check whether the user passed the '--all' argument
DISABLE_FILTER = '--all' in sys.argv

# Dictionary tracking when a MAC address was last logged
# Format: {"MAC_ADDRESS": timestamp_in_seconds}
last_logged_time = {}

# Repeat interval in seconds
# Log each device at most once per second
LOG_INTERVAL = 1
LOG_RETENTION_DAYS = 7
LOG_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
ENABLE_VOICE_ANNOUNCEMENTS = True
VOICE_QUEUE_FILENAME = 'voice_queue.jsonl'
FILTER_RELOAD_INTERVAL = 300


def load_filter_names():
    with open('filter.json', 'r') as f:
        allowed_devices = json.load(f)

    return {
        device['mac'].upper(): device['ssid']
        for device in allowed_devices
        if 'mac' in device and 'ssid' in device
    }

# 1. Load filter.json so known devices can always receive a name
try:
    mac_to_name = load_filter_names()

    if DISABLE_FILTER:
        print(
            f"🔓 Filter DISABLED: All devices are being logged "
            f"({len(mac_to_name)} known devices loaded)"
        )
    else:
        print(
            f"🔒 Filter ENABLED: {len(mac_to_name)} "
            f"devices loaded from filter.json"
        )

except Exception as e:
    if DISABLE_FILTER:
        # When --all is used, filter.json is not required.
        print(f"⚠️ Could not load filter.json: {e}")
        print("🔓 Filter DISABLED: All devices are being logged")
    else:
        print(f"❌ Error loading filter.json: {e}")
        sys.exit(1)


# 2. Open the serial port
try:
    ser = serial.Serial('/dev/ttyUSB0', 115200, timeout=1)
    print("👂 Listening on ttyUSB0... Press Ctrl+C to stop.\n")

except Exception as e:
    print(
        f"❌ Could not open ttyUSB0: {e}. "
        f"Is another monitor still open?"
    )
    sys.exit(1)


# Determine the filename based on the mode
if DISABLE_FILTER:
    output_filename = 'all_devices_output.jsonl'
else:
    output_filename = 'filtered_output.jsonl'


# Remove entries older than the retention period.
def cleanup_log_file(filename):
    cutoff_time = time.time() - (LOG_RETENTION_DAYS * 24 * 60 * 60)
    temporary_filename = f"{filename}.tmp"

    try:
        with open(filename, 'r') as source_file, open(
            temporary_filename,
            'w',
            encoding='utf-8'
        ) as temporary_file:
            for line in source_file:
                try:
                    entry = json.loads(line)
                    entry_time = time.mktime(
                        time.strptime(
                            entry['timestamp'],
                            LOG_TIMESTAMP_FORMAT
                        )
                    )
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    temporary_file.write(line)
                    continue

                if entry_time >= cutoff_time:
                    temporary_file.write(line)

        os.replace(temporary_filename, filename)
    except FileNotFoundError:
        pass
    finally:
        if os.path.exists(temporary_filename):
            os.remove(temporary_filename)


def load_announced_names(filename):
    today = time.strftime('%Y-%m-%d')
    announced_names = set()

    try:
        with open(filename, 'r', encoding='utf-8') as source_file:
            for line in source_file:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if (
                    entry.get('timestamp', '').startswith(today)
                    and entry.get('name')
                    and entry['name'] != 'Unknown Device'
                ):
                    announced_names.add(entry['name'])
    except FileNotFoundError:
        pass

    return announced_names


def queue_name_for_announcement(name):
    if not ENABLE_VOICE_ANNOUNCEMENTS:
        return

    with open(VOICE_QUEUE_FILENAME, 'a', encoding='utf-8') as queue_file:
        queue_file.write(name + '\n')
        queue_file.flush()


cleanup_log_file(output_filename)
last_cleanup_date = time.strftime('%Y-%m-%d')
announced_names = load_announced_names(output_filename)
log_file = open(output_filename, 'a')
last_filter_reload = time.monotonic()

# 3. Listen to the ESP32 live and process the data
try:
    while True:
        try:
            if time.monotonic() - last_filter_reload >= FILTER_RELOAD_INTERVAL:
                last_filter_reload = time.monotonic()
                try:
                    mac_to_name = load_filter_names()
                    print(
                        f"🔄 Reloaded filter.json: {len(mac_to_name)} devices loaded"
                    )
                except Exception as error:
                    print(f"⚠️ Could not reload filter.json: {error}")

            current_date = time.strftime('%Y-%m-%d')
            if current_date != last_cleanup_date:
                log_file.close()
                cleanup_log_file(output_filename)
                log_file = open(output_filename, 'a')
                last_cleanup_date = current_date
                announced_names = load_announced_names(output_filename)

            if ser.in_waiting > 0:
                line = ser.readline().decode(
                    'utf-8',
                    errors='ignore'
                ).strip()

                # Check whether the line has the expected format
                if ',' not in line:
                    continue

                # The firmware emits MAC,RSSI,channel.
                fields = [field.strip() for field in line.split(',')]
                if len(fields) != 3:
                    continue

                mac, rssi, channel = fields

                mac = mac.strip().upper()
                rssi = rssi.strip()

                # Check whether RSSI is a valid number
                try:
                    rssi_value = int(rssi)
                    channel_value = int(channel)
                except ValueError:
                    continue

                current_time = time.time()

                # Check rate limiting:
                # has the wait time passed for this device?
                if (
                    mac in last_logged_time
                    and (current_time - last_logged_time[mac]) < LOG_INTERVAL
                ):
                    continue

                # 4. Check filter mode
                if DISABLE_FILTER:
                    # Filter off:
                    # log ALL devices.
                    #
                    # If the MAC address is known in filter.json,
                    # use the known name.
                    # Otherwise use "Unknown Device".
                    device_name = mac_to_name.get(
                        mac,
                        "Unknown Device"
                    )

                else:
                    # Filter on:
                    # log ONLY devices listed in filter.json.
                    if mac in mac_to_name:
                        device_name = mac_to_name[mac]
                    else:
                        continue

                # Update the last logged time for this device
                last_logged_time[mac] = current_time

                # Build the JSON object
                timestamp_str = time.strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

                log_entry = {
                    "timestamp": timestamp_str,
                    "name": device_name,
                    "mac": mac,
                    "rssi": rssi_value,
                    "channel": channel_value
                }

                if (
                    device_name not in announced_names
                    and device_name != 'Unknown Device'
                ):
                    queue_name_for_announcement(device_name)
                    announced_names.add(device_name)

                # Convert the object to JSON
                json_string = json.dumps(log_entry)

                # Display the result
                print(
                    f"[{log_entry['timestamp']}] "
                    f"Spotted: {log_entry['name']} "
                    f"({log_entry['mac']}) | "
                    f"RSSI: {log_entry['rssi']}"
                )

                # Write to the JSONL file
                log_file.write(json_string + '\n')
                log_file.flush()

        except KeyboardInterrupt:
            print("\n🛑 Logger stopped. Goodbye!")
            ser.close()
            break

        except Exception:
            # Catch any corrupted serial lines
            # without allowing the logger to crash.
            pass
finally:
    log_file.close()
