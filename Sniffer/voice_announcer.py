import json
import hashlib
import os
import shutil
import subprocess
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
QUEUE_FILENAME = os.path.join(BASE_DIR, 'voice_queue.jsonl')
QUOTE_QUEUE_FILENAME = os.path.abspath(
    os.path.join(BASE_DIR, '..', 'quotes', 'quote_queue.jsonl')
)
AUDIO_DIR = os.path.join(BASE_DIR, 'audiofiles/')
VOICES_DIR = os.path.join(BASE_DIR, 'voicefiles/')
VOLUME = 100
POLL_INTERVAL_SECONDS = 0.5
VOICE_NAME = "en_US-ryan-high"


def quote_audio_name(text):
    return 'quote-' + hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]


def speak_name(name):
    greeting = f'Welcome, {name}'

    speech_engine = shutil.which('espeak')
    command = [speech_engine, greeting]
    run_options = {}

    subprocess.run(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        **run_options,
    )

def audio_exists(name):
    path = f"{AUDIO_DIR}{name}.wav"

    return os.path.isfile(path)

def generate_audio(name, text):
    print("generating audio file")
    audiofile_dir = f"{AUDIO_DIR}{name}.wav"
    tempfile_dir = f"{AUDIO_DIR}temp.wav"
    voicefile = VOICE_NAME
    generate_command = ["python", 
               "-m",  "piper", 
               "-m", voicefile, 
               "--output_file", tempfile_dir, 
               "--data-dir", f"{VOICES_DIR}", 
               f"{text}"]

    run_options = {}
    subprocess.run(
        generate_command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        **run_options,
    )

    pad_command = ["ffmpeg",
                   "-y",
                   "-i", tempfile_dir,
                   "-af", "adelay=300:all=1,apad=pad_dur=0.3",
                   audiofile_dir]

    subprocess.run(
        pad_command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        **run_options,
    )
    try:
        os.remove(tempfile_dir)
    except FileNotFoundError:
        pass

def play_audio(name):
    audiofile_dir = f"{AUDIO_DIR}{name}.wav"
    print("playing " + audiofile_dir)

    command = ["ffplay", 
               "-nodisp", 
               "-autoexit", 
               f"-volume", f"{VOLUME}", 
               f"{audiofile_dir}"]

    run_options = {}
    subprocess.run(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        **run_options,
    )


def main():
    print("Voice Announcer Running")
    print(QUEUE_FILENAME)
    last_quote_name = None
    with open(QUEUE_FILENAME, 'a+', encoding='utf-8') as queue_file, open(
        QUOTE_QUEUE_FILENAME, 'a+', encoding='utf-8'
    ) as quote_queue_file:
        queue_file.seek(0, os.SEEK_END)
        quote_queue_file.seek(0, os.SEEK_END)

        while True:
            line = quote_queue_file.readline()
            if not line:
                line = queue_file.readline()
            
            if line:
                queue_entry = line.strip()
                name = queue_entry
                greeting = None
                try:
                    queue_entry = json.loads(queue_entry)
                except json.JSONDecodeError:
                    pass
                else:
                    if isinstance(queue_entry, dict):
                        name = queue_entry.get('name', '').strip()
                        greeting = queue_entry.get('greeting')

                queue_type = queue_entry.get('type') if isinstance(queue_entry, dict) else None
                is_quote = queue_type == 'quote'
                if is_quote:
                    quote_text = queue_entry.get('text', '').strip()
                    name = quote_audio_name(quote_text) if quote_text else ''
                    spoken_text = quote_text
                else:
                    spoken_text = f"{greeting or 'Welcome'} {name}!"

                if is_quote and name == last_quote_name:
                    continue
                if name and not audio_exists(name):
                    generate_audio(name, spoken_text)

                if name:
                    play_audio(name)
                    if is_quote:
                        last_quote_name = name
                        try:
                            os.remove(f"{AUDIO_DIR}{name}.wav")
                        except FileNotFoundError:
                            pass
                    else:
                        last_quote_name = None
                    #speak_name(name)
            else:
                time.sleep(POLL_INTERVAL_SECONDS)


if len(sys.argv) == 3 and sys.argv[1] == '--prepare-quote':
    quote_text = sys.argv[2].strip()
    if quote_text:
        quote_name = quote_audio_name(quote_text)
        if not audio_exists(quote_name):
            generate_audio(quote_name, quote_text)
    raise SystemExit(0)


if __name__ == '__main__':
    main()
