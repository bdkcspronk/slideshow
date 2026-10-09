import argparse
import json
import colorsys
import hashlib
from pathlib import Path as FilePath

from datetime import datetime, time, timedelta, timezone

import matplotlib

# Prevent a pop-up window so the script can run undisturbed in the background
matplotlib.use('Agg')

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.patches as patches
import numpy as np
from matplotlib.collections import LineCollection
from matplotlib.path import Path
from matplotlib.transforms import IdentityTransform
import pandas as pd


parser = argparse.ArgumentParser()
PROJECT_DIR = FilePath(__file__).resolve().parent.parent
parser.add_argument(
    'outputfolder',
    nargs='?',
    type=FilePath,
    default=PROJECT_DIR / 'slides',
)
args = parser.parse_args()


# Plot configuration
DEFAULT_COLOR = '#00E676'
GRID_COLOR = '#263238'
BACKGROUND_COLOR = "#151722"
TEXT_COLOR = '#ECEFF1'
FALLBACK_SATURATION_RANGE = (0.65, 0.9)
FALLBACK_BRIGHTNESS_RANGE = (0.85, 1.0)
FIGURE_SIZE = (19.2, 10.8)
FIGURE_DPI = 100
NYAN_CAT_PATH = FilePath(__file__).parent / 'resources' / 'nyancat.png'
CORNER_RADIUS = 8
CURVE_FACTOR = 0.5522848
VERTICAL_AXIS_PADDING = 1.0
SUBPLOT_MARGINS = {
    'left': 0.12,
    'right': 0.98,
    'bottom': 0.12,
    'top': 0.88,
}

# Load custom colors from filter.json.
mac_colors = {}
mac_gradients = {}
mac_styles = {}
mac_stripe_colors = {}
mac_stripe_thicknesses = {}
mac_nyan_cat_offsets = {}
mac_beer_foam_max_widths = {}
supported_styles = {
    'round corners',
    'square corners',
    'striped',
    'nyan cat',
    'beer',
    'glow',
    'board',
}
try:
    with open('filter.json', 'r') as f:
        filter_data = json.load(f)
        if isinstance(filter_data, dict):
            filter_data = [filter_data]
        for device in filter_data:
            if 'mac' not in device:
                continue

            mac = device['mac'].upper()
            color = device.get('color', device.get('gradient'))
            configured_styles = device.get('style', 'round corners')
            if isinstance(configured_styles, str):
                styles = [configured_styles]
            elif isinstance(configured_styles, list):
                styles = configured_styles
            else:
                styles = []
            styles = [style for style in styles if style in supported_styles]
            if not styles:
                styles = ['round corners']
            stripe_color = device.get('stripe_color')
            if (
                'striped' in styles
                and isinstance(color, list)
                and color
                and isinstance(color[0], list)
            ):
                stripe_color = color[1] if len(color) > 1 else None
                color = color[0]

            if isinstance(color, list):
                if len(color) >= 2:
                    mac_gradients[mac] = color
                elif color:
                    mac_colors[mac] = color[0]
            elif isinstance(color, str):
                mac_colors[mac] = color

            mac_styles[mac] = styles
            thickness = device.get('thickness')
            if isinstance(thickness, (int, float)) and thickness > 0:
                mac_stripe_thicknesses[mac] = thickness
            x_offset = device.get('x_offset', 0)
            if isinstance(x_offset, (int, float)):
                mac_nyan_cat_offsets[mac] = x_offset
            foam_max_width = device.get('foam_max_width')
            if isinstance(foam_max_width, (int, float)) and foam_max_width > 0:
                mac_beer_foam_max_widths[mac] = foam_max_width
            if isinstance(stripe_color, list):
                if len(stripe_color) >= 2:
                    mac_stripe_colors[mac] = stripe_color
                elif stripe_color:
                    mac_stripe_colors[mac] = stripe_color[0]
            elif isinstance(stripe_color, str):
                mac_stripe_colors[mac] = stripe_color
except Exception:
    pass

try:
    nyan_cat_image = plt.imread(NYAN_CAT_PATH)
except (FileNotFoundError, OSError):
    nyan_cat_image = None


def generate_bright_color(identifier):
    """Generate a stable, bright color for an unconfigured device."""
    digest = hashlib.sha256(identifier.encode('utf-8')).digest()
    hue = int.from_bytes(digest[0:2], 'big') / 65535
    saturation_min, saturation_max = FALLBACK_SATURATION_RANGE
    brightness_min, brightness_max = FALLBACK_BRIGHTNESS_RANGE
    saturation = saturation_min + (
        digest[2] / 255 * (saturation_max - saturation_min)
    )
    brightness = brightness_min + (
        digest[3] / 255 * (brightness_max - brightness_min)
    )
    red, green, blue = colorsys.hsv_to_rgb(hue, saturation, brightness)
    return '#{:02X}{:02X}{:02X}'.format(
        round(red * 255),
        round(green * 255),
        round(blue * 255),
    )

# Load activity data.
data = []
try:
    with open('filtered_output.jsonl', 'r') as f:
        for line in f:
            if line.strip():
                data.append(json.loads(line.strip()))
except FileNotFoundError:
    print('No filtered_output.jsonl found; no plot was created.')
    exit()

if not data:
    print('filtered_output.jsonl is empty; no plot was created.')
    exit()

# Prepare the activity data.
df = pd.DataFrame(data)
df['timestamp'] = pd.to_datetime(df['timestamp'])

# Keep only today's activity.
today = datetime.now().date()
df = df[df['timestamp'].dt.date == today]

if df.empty:
    print('No activity was recorded today; no plot was created.')
    exit()

# Group activity into five-minute buckets.
df['time_bucket'] = df['timestamp'].dt.floor('5min')
unieke_namen = (
    df.groupby('name')['timestamp']
    .min()
    .sort_values()
    .index
    .tolist()
)

# Create the plot.
plt.style.use('dark_background')
fig, ax = plt.subplots(
    figsize=FIGURE_SIZE,
    dpi=FIGURE_DPI,
    facecolor=BACKGROUND_COLOR,
)
ax.set_facecolor(BACKGROUND_COLOR)

# Keep grid lines behind the markers.
ax.set_axisbelow(True)
marker_specs = []
generated_colors = {}
random_generator = np.random.default_rng()

# Build marker specifications for each person.
for y_index, naam in enumerate(unieke_namen):
    persoon_df = df[df['name'] == naam]

    sample_mac = persoon_df['mac'].iloc[0].upper() if not persoon_df.empty else ""
    user_color = mac_gradients.get(sample_mac) or mac_colors.get(sample_mac)
    configured_styles = mac_styles.get(sample_mac, ['round corners'])
    user_style = next(
        (
            style
            for style in configured_styles
            if style != 'glow'
        ),
        'round corners',
    )
    glow_enabled = 'glow' in configured_styles
    stripe_color = mac_stripe_colors.get(sample_mac, TEXT_COLOR)
    stripe_thickness = mac_stripe_thicknesses.get(sample_mac)
    nyan_cat_x_offset = mac_nyan_cat_offsets.get(sample_mac, 0)
    beer_foam_max_width = mac_beer_foam_max_widths.get(sample_mac)
    if user_color is None:
        user_color = generated_colors.setdefault(
            sample_mac or naam,
            generate_bright_color(sample_mac or naam),
        )

    spotted_times = sorted(persoon_df['time_bucket'].unique())

    if not spotted_times:
        continue

    blocks = []
    start_time = spotted_times[0]
    previous_time = spotted_times[0]

    for current_time in spotted_times[1:]:
        if current_time - previous_time <= pd.Timedelta(minutes=10):
            previous_time = current_time
        else:
            end_time = previous_time + pd.Timedelta(minutes=5)
            blocks.append((start_time, end_time))
            start_time = current_time
            previous_time = current_time

    end_time = previous_time + pd.Timedelta(minutes=5)
    blocks.append((start_time, end_time))

    for block_index, (start, end) in enumerate(blocks):
        start_num = mdates.date2num(start)
        end_num = mdates.date2num(end)
        width = end_num - start_num

        height = 0.8
        y_pos = y_index - (height / 2)

        marker_specs.append(
            (
                start_num,
                end_num,
                y_pos,
                height,
                user_color,
                user_style,
                glow_enabled,
                stripe_color,
                stripe_thickness,
                nyan_cat_x_offset,
                beer_foam_max_width,
                block_index == len(blocks) - 1,
            )
        )

# Configure axis limits.
current_datetime = datetime.now()
latest_activity = df['timestamp'].max().to_pydatetime()
ax.set_xlim(
    mdates.date2num(datetime.combine(today, time(8, 0))),
    mdates.date2num(max(current_datetime, latest_activity) + timedelta(minutes=30))
)
ax.set_ylim(
    -VERTICAL_AXIS_PADDING,
    len(unieke_namen) - 1 + VERTICAL_AXIS_PADDING,
)

# Configure Y-axis labels.
ax.set_yticks(range(len(unieke_namen)))
ax.set_yticklabels(
    unieke_namen,
    fontsize=20,
    fontweight='normal',
    color=TEXT_COLOR,
)
ax.invert_yaxis()

# Configure X-axis labels.
ax.xaxis.set_major_locator(mdates.HourLocator(interval=1))
ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
ax.tick_params(axis='x', colors=TEXT_COLOR, labelsize=20, pad=8)
ax.tick_params(axis='y', colors=TEXT_COLOR, pad=12)

# Remove plot borders.
for spine in ['top', 'right', 'left', 'bottom']:
    ax.spines[spine].set_visible(False)

# Add X-axis grid lines every 15 minutes, with stronger half-hour and hourly lines.
grid_start = pd.Timestamp(datetime.combine(today, time(8, 0)))
grid_end = pd.Timestamp(current_datetime + timedelta(minutes=5))
for grid_time in pd.date_range(grid_start, grid_end, freq='15min'):
    if grid_time.minute == 0:
        line_width = 2.0
        line_alpha = 0.9
    elif grid_time.minute == 30:
        line_width = 1.3
        line_alpha = 0.75
    else:
        line_width = 0.7
        line_alpha = 0.5

    ax.axvline(
        grid_time,
        linestyle='-',
        linewidth=line_width,
        color=GRID_COLOR,
        alpha=line_alpha,
        zorder=1
    )

# Add subtle horizontal grid lines.
ax.yaxis.grid(True, linestyle='-', color=GRID_COLOR, alpha=0.3, zorder=1)

# Add the title.
ax.set_title(
    'FRANCKEN ACTIVITY TRACKER',
    fontsize=25,
    fontweight='bold',
    color=TEXT_COLOR,
    loc='left',
    pad=25,
)

# Finalize layout before converting marker coordinates to screen space.
fig.autofmt_xdate()
fig.subplots_adjust(**SUBPLOT_MARGINS)

fig.canvas.draw()
data_transform = ax.transData
display_transform = IdentityTransform()
gradient_groups = {}

for (
    start_num,
    end_num,
    y_pos,
    height,
    user_color,
    user_style,
    glow_enabled,
    stripe_color,
    stripe_thickness,
    nyan_cat_x_offset,
    beer_foam_max_width,
    is_latest_block,
) in marker_specs:
    x0, y0 = data_transform.transform((start_num, y_pos))
    x1, y1 = data_transform.transform((end_num, y_pos + height))
    radius = min(CORNER_RADIUS, abs(x1 - x0) / 2, abs(y1 - y0) / 2)
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    curve = radius * CURVE_FACTOR

    rounded_path = Path([
        (x0 + radius, y0),
        (x1 - radius, y0),
        (x1 - radius + curve, y0),
        (x1, y0 + radius - curve),
        (x1, y0 + radius),
        (x1, y1 - radius),
        (x1, y1 - radius + curve),
        (x1 - radius + curve, y1),
        (x1 - radius, y1),
        (x0 + radius, y1),
        (x0 + radius - curve, y1),
        (x0, y1 - radius + curve),
        (x0, y1 - radius),
        (x0, y0 + radius),
        (x0, y0 + radius - curve),
        (x0 + radius - curve, y0),
        (x0 + radius, y0),
    ], [
        Path.MOVETO,
        Path.LINETO,
        Path.CURVE4,
        Path.CURVE4,
        Path.CURVE4,
        Path.LINETO,
        Path.CURVE4,
        Path.CURVE4,
        Path.CURVE4,
        Path.LINETO,
        Path.CURVE4,
        Path.CURVE4,
        Path.CURVE4,
        Path.LINETO,
        Path.CURVE4,
        Path.CURVE4,
        Path.CURVE4,
    ])
    if user_style == 'square corners':
        marker_shape = patches.Rectangle(
            (x0, y0),
            x1 - x0,
            y1 - y0,
            transform=display_transform,
            facecolor='none',
            edgecolor='none',
            zorder=3,
        )
    else:
        marker_shape = patches.PathPatch(
            rounded_path,
            transform=display_transform,
            facecolor='none',
            edgecolor='none',
            zorder=3,
        )

    if glow_enabled:
        glow_color = (
            user_color[len(user_color) // 2]
            if isinstance(user_color, list)
            else user_color
        )
        glow_width = max(4.0, min(18.0, (y1 - y0) * 0.22))
        for width, alpha in (
            (glow_width, 0.08),
            (glow_width * 0.65, 0.14),
            (glow_width * 0.35, 0.24),
        ):
            glow_shape = patches.PathPatch(
                marker_shape.get_path(),
                transform=marker_shape.get_transform(),
                facecolor='none',
                edgecolor=glow_color,
                linewidth=width,
                alpha=alpha,
                joinstyle='round',
                zorder=2,
            )
            ax.add_patch(glow_shape)

    if user_style == 'board':
        marker_shape.set_facecolor('#D62828')
        ax.add_patch(marker_shape)
    elif user_style == 'beer':
        beer_map = matplotlib.colors.LinearSegmentedColormap.from_list(
            'beer_gradient',
            ["#F3B01F", '#F5C340'],
        )
        horizontal_beer_gradient = beer_map(np.linspace(0, 1, 256))
        beer_gradient = np.tile(
            horizontal_beer_gradient[None, :, :],
            (256, 1, 1),
        )
        ax.add_patch(marker_shape)
        ax.imshow(
            beer_gradient,
            extent=(x0, x1, y0, y1),
            origin='lower',
            aspect='auto',
            interpolation='bilinear',
            transform=display_transform,
            clip_path=marker_shape,
            zorder=3,
        )

        foam_width = (x1 - x0) * 0.28
        if beer_foam_max_width is not None:
            foam_width = min(foam_width, beer_foam_max_width)
        foam = patches.Rectangle(
            (x1 - foam_width, y0),
            foam_width,
            y1 - y0,
            transform=display_transform,
            facecolor="#FCEFCA",
            edgecolor='none',
            zorder=4,
        )
        foam.set_clip_path(marker_shape)
        ax.add_patch(foam)

        bubble_radius = max(1.2, min(4.0, (y1 - y0) * 0.1))
        bubble_start = x0 + bubble_radius * 2
        bubble_end = x1 - foam_width - bubble_radius * 2
        beer_width = max(0, bubble_end - bubble_start)
        bubble_count = max(1, min(12, round(beer_width / 12)))
        exponential_scale = 120
        truncation = -np.expm1(-beer_width / exponential_scale)
        bubble_distances = -exponential_scale * np.log(
            1 - random_generator.random(bubble_count) * truncation
        )
        bubble_positions = np.sort(bubble_start + bubble_distances)
        for bubble_index, bubble_x in enumerate(bubble_positions):
            bubble_y = random_generator.uniform(
                y0 + bubble_radius,
                y1 - bubble_radius,
            )
            bubble = patches.Circle(
                (bubble_x, bubble_y),
                bubble_radius * (0.7 + (bubble_index % 2) * 0.3),
                transform=display_transform,
                facecolor="#FFEEC1",
                edgecolor='none',
                zorder=4,
            )
            bubble.set_clip_path(marker_shape)
            ax.add_patch(bubble)
    elif user_style == 'nyan cat':
        rainbow_colors = [
            '#E40303',
            '#FF8C00',
            '#FFED00',
            '#008026',
            '#004DFF',
            '#750787',
        ]
        rainbow_map = matplotlib.colors.LinearSegmentedColormap.from_list(
            'nyan_cat_rainbow',
            rainbow_colors,
        )
        gradient_array = rainbow_map(np.linspace(0, 1, 256))[:, None, :]
        ax.add_patch(marker_shape)
        ax.imshow(
            gradient_array,
            extent=(x0, x1, y0, y1),
            origin='lower',
            aspect='auto',
            transform=display_transform,
            clip_path=marker_shape,
            zorder=3,
        )
    elif isinstance(user_color, list):
        gradient_key = tuple(user_color)
        gradient_group = gradient_groups.setdefault(
            gradient_key,
            {'paths': [], 'bounds': []},
        )
        gradient_group['paths'].append(
            marker_shape.get_path().transformed(marker_shape.get_transform())
        )
        gradient_group['bounds'].append((x0, x1, y0, y1))

    else:
        marker_shape.set_facecolor(user_color)
        ax.add_patch(marker_shape)

    if (
        user_style == 'nyan cat'
        and is_latest_block
        and nyan_cat_image is not None
    ):
        image_height = (y1 - y0) * 1.3
        source_height, source_width = nyan_cat_image.shape[:2]
        image_width = image_height * source_width / source_height
        image_y0 = y0 + ((y1 - y0) - image_height) / 2
        image_x_offset = image_width * nyan_cat_x_offset / 100
        ax.imshow(
            nyan_cat_image,
            extent=(
                x1 + image_x_offset,
                x1 + image_x_offset + image_width,
                image_y0,
                image_y0 + image_height,
            ),
            origin='upper',
            aspect='auto',
            transform=display_transform,
            zorder=5,
        )

    if user_style in {'striped', 'board'}:
        stripe_thickness = (
            stripe_thickness
            if stripe_thickness is not None
            else (y1 - y0) / 2.0
        )
        stripe_width = max(4.0, stripe_thickness * 1.5)
        stripe_spacing = stripe_width * 2 * np.sqrt(2)
        stripe_offsets = np.arange(
            -y1 + y0,
            x1 - x0 + y1 - y0,
            stripe_spacing,
        )
        stripe_segments = [
            [
                (x0 + offset - (y1 - y0), y0 - (y1 - y0)),
                (x0 + offset + 2 * (y1 - y0), y1 + (y1 - y0)),
            ]
            for offset in stripe_offsets
        ]
        if user_style == 'board':
            stripe_colors = ['#0057B8'] * len(stripe_segments)
        elif isinstance(stripe_color, list):
            stripe_map = matplotlib.colors.LinearSegmentedColormap.from_list(
                'stripe_gradient',
                stripe_color,
            )
            stripe_positions = [
                np.clip(
                    (x0 + offset + (y1 - y0) / 2 - x0) / (x1 - x0),
                    0,
                    1,
                )
                for offset in stripe_offsets
            ]
            stripe_colors = stripe_map(stripe_positions)
        else:
            stripe_colors = [stripe_color] * len(stripe_segments)

        stripes = LineCollection(
            stripe_segments,
            colors=stripe_colors,
            linewidths=stripe_width,
            transform=display_transform,
            zorder=6,
        )
        stripes.set_clip_path(
            marker_shape.get_path(),
            marker_shape.get_transform(),
        )
        ax.add_collection(stripes)

for user_color, gradient_group in gradient_groups.items():
    compound_path = Path.make_compound_path(*gradient_group['paths'])
    gradient_shape = patches.PathPatch(
        compound_path,
        transform=display_transform,
        facecolor='none',
        edgecolor='none',
        zorder=3,
    )
    gradient_map = matplotlib.colors.LinearSegmentedColormap.from_list(
        'activity_gradient',
        user_color,
    )
    gradient_array = np.linspace(0, 1, 256)[None, :]
    bounds = gradient_group['bounds']
    gradient_x0 = min(bound[0] for bound in bounds)
    gradient_x1 = max(bound[1] for bound in bounds)
    gradient_y0 = min(bound[2] for bound in bounds)
    gradient_y1 = max(bound[3] for bound in bounds)
    ax.add_patch(gradient_shape)
    ax.imshow(
        gradient_array,
        extent=(gradient_x0, gradient_x1, gradient_y0, gradient_y1),
        origin='lower',
        aspect='auto',
        interpolation='nearest',
        cmap=gradient_map,
        vmin=0,
        vmax=1,
        transform=display_transform,
        clip_path=gradient_shape,
        zorder=3,
    )

# Save the graph with a unique UTC timestamped filename.
poster_directory = args.outputfolder
poster_directory.mkdir(parents=True, exist_ok=True)
for old_poster in poster_directory.glob('slide-*.png'):
    if old_poster.is_file():
        old_poster.unlink()

poster_path = poster_directory / (
    f"sniffer_slide.png"  #-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')}.png"
)

plt.savefig(
    poster_path,
    dpi=FIGURE_DPI,
    facecolor=fig.get_facecolor(),
    edgecolor='none',
)
plt.close(fig)
