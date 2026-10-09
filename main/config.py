from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SNIFFER_DIR = PROJECT_DIR / "Sniffer"
RUN_SYSTEM_SCRIPT = SNIFFER_DIR / "run_system.py"
TERMINAL_EMULATORS = (
	("x-terminal-emulator", "-e"),
	("gnome-terminal", "--"),
	("konsole", "-e"),
	("xfce4-terminal", "--command"),
	("xterm", "-e"),
)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".m4a"}
VRIJMIBO_FILENAME = "vrijmibo.gif"
SNIFFER_FILENAME = "sniffer_slide.png"
BEER_HOUR_SLIDE = Path("__beer_hour__")
BEER_HOUR_PREVIEW_SECONDS = 5.0
AUDIO_OFFSETS = {
	"gdn.sci.090701.sc.moon-countdown-launch.mp3": 0.0,
	"i-said-hey.mp3": 0.0,
	"live-is-life.mp3": 0.0,
	"toby.mp3": 0.0,
}