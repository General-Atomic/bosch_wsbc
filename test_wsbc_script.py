"""
wsbc_script.py

# -----------------------------------------------------------------------------
# Patch Notes Section
# 
# unique sensor delay
# OS checker - mock for windows / real for rpi
# graph for delay verification
# -----------------------------------------------------------------------------

Windows:
    - Uses a MOCK version of sm_4rel4in so you can test the GUI and logic
      without Raspberry Pi hardware or smbus2.

Raspberry Pi:
    - Uses the real sm_4rel4in library and talks to the 4-Relay/4-Input HAT
      as normal.
"""

import platform
import time
import tkinter as tk

# -----------------------------------------------------------------------------
# Hardware abstraction: real sm_4rel4in on Pi, mock on Windows / failure
# -----------------------------------------------------------------------------

USING_MOCK_IO = False

try:
    # On Raspberry Pi (or any environment that has sm_4rel4in + smbus2 installed)
    import sm_4rel4in
    USING_MOCK_IO = False
    print("✅ Using REAL sm_4rel4in hardware library.")
except Exception as e:
    # On Windows or when the library/smbus2 isn't available
    print("⚠ sm_4rel4in import failed, using MOCK hardware instead.")
    print(f"   Reason: {e}")
    USING_MOCK_IO = True

    class MockSm4Rel4In:
        """
        Minimal mock to match the interface used in this script:

            rel = sm_4rel4in.SM4rel4in(0)
            rel.get_in(channel)
        """

        def __init__(self, stack):
            print(f"[MOCK] Initialized MockSm4Rel4In(stack={stack})")

        def get_in(self, channel):
            # Always report LOW (0) by default; adjust for simulated behavior if needed.
            print(f"[MOCK] get_in(channel={channel}) -> 0")
            return 0

    # Expose a module-like object with SM4rel4in attribute
    sm_4rel4in = type("sm_4rel4in", (), {"SM4rel4in": MockSm4Rel4In})

# -----------------------------------------------------------------------------
# Hardware setup
# -----------------------------------------------------------------------------
rel = sm_4rel4in.SM4rel4in(0)  # Initialize 4rel4in HAT (real or mock)

CHANNEL_OHB_ADD = 1   # Overhead buffer add sensor
CHANNEL_OHB_SUB = 2   # Overhead buffer subtract sensor
CHANNEL_WS_ADD = 3    # Wet section add sensor
CHANNEL_WS_SUB = 4    # Wet section subtract sensor

# -----------------------------------------------------------------------------
# CONFIGURATION
# -----------------------------------------------------------------------------
# Thresholds for progress bar colors
OHB_THRESHOLDS = [
    (None, 75, "#e74c3c"),   # Red
    (76, 5, "#f1c40f"),      # Yellow
    (6, None, "#2ecc71")    # Green
]
WS_THRESHOLDS = [
    (None, 1, "#e9e9e9"),   # Red placeholder (#e74c3c originally)
    (2, 4, "#e9e9e9"),      # Yellow placeholder (#f1c40f originally)
    (5, None, "#e9e9e9")    # Green placeholder (#2ecc71 originally)
]

OHB_PROGRESS_MAX = 10  # Maximum value displayed on OHB progress bar
WS_PROGRESS_MAX = 10   # Maximum value displayed on WS progress bar

# -----------------------------------------------------------------------------
# Per-sensor independent delay times (ms)
# -----------------------------------------------------------------------------
# Cooldown times after a sensor turns OFF before it can be counted again.
OHB_ADD_DELAY_MS = 1000   # Channel 1: Overhead Buffer ADD
OHB_SUB_DELAY_MS = 1000   # Channel 2: Overhead Buffer SUB
WS_ADD_DELAY_MS = 1000    # Channel 3: Wet Section ADD
WS_SUB_DELAY_MS = 1000    # Channel 4: Wet Section SUB

POLL_INTERVAL_MS = 10     # How often to poll sensors (ms)

# -----------------------------------------------------------------------------
# Internal state
# -----------------------------------------------------------------------------
sum_ohb = 0
sum_ws = 0

# Previous values for UI change detection
prev_total = -1
prev_ohb = -1
prev_ws = -1

# Sensor detection flags (True when sensor currently considered "held/high")
sig_ohb_add_detected = False
sig_ohb_sub_detected = False
sig_ws_add_detected = False
sig_ws_sub_detected = False

# Sensor delay timers (store timestamp in ms when sensor went LOW)
timer_ohb_add = 0
timer_ohb_sub = 0
timer_ws_add = 0
timer_ws_sub = 0

# -----------------------------------------------------------------------------
# UI Helper functions
# -----------------------------------------------------------------------------
WINDOW_BG = "#ececec"     # Main window background
CARD_BG = "#ffffff"       # Card background
SHADOW_COLOR = "#bfbfbf"  # Shadow behind cards
TITLE_COLOR = "#0a66c2"   # Card title color
FONT_FAMILY = "Segoe UI"  # Font used in UI

def pick_color_from_thresholds(value, thresholds, default="#000000"):
    """
    Returns the color based on the thresholds list for progress bars.
    """
    if not thresholds:
        return default
    for mn, mx, col in thresholds:
        if (mn is None or value >= mn) and (mx is None or value <= mx):
            return col
    return default

def rounded_rect(canvas, x1, y1, x2, y2, r=20, **kwargs):
    """
    Draws a rounded rectangle on a canvas.
    """
    points = [
        x1 + r, y1,
        x2 - r, y1,
        x2, y1,
        x2, y1 + r,
        x2, y2 - r,
        x2, y2,
        x2 - r, y2,
        x1 + r, y2,
        x1, y2,
        x1, y2 - r,
        x1, y1 + r,
        x1, y1
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)

# -----------------------------------------------------------------------------
# Card Classes
# -----------------------------------------------------------------------------
class Card:
    """
    A basic card that shows a a title and a numeric value.
    """
    def __init__(self, parent, width, height, title="", title_font=(FONT_FAMILY, 18, "bold"),
                 value_font=(FONT_FAMILY, 48, "bold"), thresholds=None):
        self.width = width
        self.height = height
        self.thresholds = thresholds
        self.canvas = tk.Canvas(parent, width=width+8, height=height+8, bg=WINDOW_BG, highlightthickness=0)
        # Shadow
        rounded_rect(self.canvas, 4, 4, width+4, height+4, r=18, fill=SHADOW_COLOR, outline="")
        # Background
        rounded_rect(self.canvas, 0, 0, width, height, r=18, fill=CARD_BG, outline="")
        # Title text
        self.title_id = self.canvas.create_text(width/2, height*0.3, text=title, font=title_font, fill=TITLE_COLOR)
        # Numeric value
        self.value_id = self.canvas.create_text(width/2, height*0.65, text="0", font=value_font, fill="black")
        self.current_value = 0

    def set_value(self, new_value):
        """
        Updates the numeric value displayed.
        """
        self.canvas.itemconfigure(self.value_id, text=str(new_value))
        self.current_value = new_value

    def pack(self, **kwargs):
        self.canvas.pack(**kwargs)

    def grid(self, **kwargs):
        self.canvas.grid(**kwargs)

class ProgressCard(Card):
    """
    A card with a horizontal progress bar.
    """
    def __init__(self, parent, width, height, title="", bar_height=28,
                 title_font=(FONT_FAMILY, 14, "bold"), value_font=(FONT_FAMILY, 20, "bold"),
                 progress_max=10, thresholds=None):
        super().__init__(parent, width, height, title=title, title_font=title_font,
                         value_font=value_font, thresholds=None)
        self.progress_max = max(1, progress_max)
        self.thresholds = thresholds or []
        # Remove parent texts
        self.canvas.delete(self.title_id)
        self.canvas.delete(self.value_id)
        # Left-aligned title
        self.left_title = self.canvas.create_text(self.width*0.12, self.height*0.26, anchor="w",
                                                  text=title, font=title_font, fill="#333333")
        # Right-aligned numeric value
        self.num_text = self.canvas.create_text(self.width*0.88, self.height*0.26, anchor="e",
                                                text="0", font=value_font, fill="black")
        # Track coordinates for progress bar
        self.track_x1 = self.width*0.12
        self.track_x2 = self.width*0.88
        self.track_y = self.height*0.72
        self.track_r = bar_height//2
        self.fill_id = None
        # Draw progress track background
        self._draw_track()

    def _draw_track(self):
        """
        Draws the gray background track for the progress bar.
        """
        x1 = self.track_x1
        y1 = self.track_y - self.track_r
        x2 = self.track_x2
        y2 = self.track_y + self.track_r
        rounded_rect(self.canvas, x1, y1, x2, y2, r=self.track_r, fill="#e9e9e9", outline="")

    def set_value(self, new_value):
        """
        Sets progress bar value and updates numeric display. Stops at max value.
        """
        # Update numeric value
        self.canvas.itemconfigure(self.num_text, text=str(new_value))
        # Calculate fill proportion (capped at 1.0)
        proportion = min(max(new_value / float(self.progress_max), 0.0), 1.0)
        x1 = self.track_x1 + 2
        x2 = self.track_x1 + 2 + (self.track_x2 - self.track_x1 - 4) * proportion
        y1 = self.track_y - (self.track_r - 2)
        y2 = self.track_y + (self.track_r - 2)
        fill_color = pick_color_from_thresholds(new_value, self.thresholds, default="#2ecc71")
        # Remove previous fill
        if self.fill_id:
            try:
                self.canvas.delete(self.fill_id)
            except Exception:
                pass
            self.fill_id = None
        # Draw new fill if any
        if x2 > x1 + 1:
            self.fill_id = rounded_rect(self.canvas, x1, y1, x2, y2, r=self.track_r, fill=fill_color, outline="")

    def pack(self, **kwargs):
        self.canvas.pack(**kwargs)

    def grid(self, **kwargs):
        self.canvas.grid(**kwargs)

# -----------------------------------------------------------------------------
# Trend Graph (OHB / WS over time, x = time, y = value)
# -----------------------------------------------------------------------------
class TrendGraph:
    """
    Simple line graph drawn using Tkinter Canvas only.

    - Plots OHB and WS counts over time (no Total line for now).
    - X-axis: time, labeled hour by hour (HH:MM).
    - Y-axis: value, with ticks at 0, mid, max.
    """
    def __init__(self, parent, width=780, height=260, title="Counts Over Time (OHB / WS)"):
        self.width = width
        self.height = height
        self.max_points = 240  # history length (you can adjust)

        self.history_times = []  # timestamps (seconds since epoch)
        self.history_ohb = []
        self.history_ws = []

        self.canvas = tk.Canvas(parent, width=width+8, height=height+8,
                                bg=WINDOW_BG, highlightthickness=0)

        # Card-style background
        rounded_rect(self.canvas, 4, 4, width+4, height+4, r=18, fill=SHADOW_COLOR, outline="")
        rounded_rect(self.canvas, 0, 0, width, height, r=18, fill=CARD_BG, outline="")

        # Title
        self.canvas.create_text(width/2, 22, text=title,
                                font=(FONT_FAMILY, 14, "bold"),
                                fill="#333333")

        # Legend (only OHB and WS)
        legend_y = 40
        legend_items = [
            ("OHB", "#e67e22"),
            ("WS",  "#27ae60"),
        ]
        legend_x = 40
        for label, color in legend_items:
            self.canvas.create_rectangle(legend_x, legend_y-7, legend_x+14, legend_y+7,
                                         outline=color, fill=color)
            self.canvas.create_text(legend_x+26, legend_y, text=label,
                                    anchor="w", font=(FONT_FAMILY, 10), fill="#333333")
            legend_x += 90

        # Plot area
        self.plot_left = 60
        self.plot_right = width - 20
        self.plot_top = 60
        self.plot_bottom = height - 40

        # Axes (static lines)
        self.canvas.create_line(self.plot_left, self.plot_bottom,
                                self.plot_right, self.plot_bottom,
                                fill="#bbbbbb")
        self.canvas.create_line(self.plot_left, self.plot_top,
                                self.plot_left, self.plot_bottom,
                                fill="#bbbbbb")

        # Y-axis label
        self.canvas.create_text(self.plot_left - 40,
                                (self.plot_top + self.plot_bottom) / 2,
                                text="Value",
                                angle=90,
                                font=(FONT_FAMILY, 10),
                                fill="#555555")

        # X-axis label
        self.canvas.create_text((self.plot_left + self.plot_right) / 2,
                                self.plot_bottom + 22,
                                text="Time (hour by hour)",
                                font=(FONT_FAMILY, 10),
                                fill="#555555")

        # For dynamic max indicator
        self.y_label_id = self.canvas.create_text(self.plot_right,
                                                  self.plot_top,
                                                  anchor="ne",
                                                  font=(FONT_FAMILY, 9),
                                                  fill="#555555",
                                                  text="")

    def pack(self, **kwargs):
        self.canvas.pack(**kwargs)

    def _limit_history(self):
        while len(self.history_times) > self.max_points:
            self.history_times.pop(0)
            self.history_ohb.pop(0)
            self.history_ws.pop(0)

    def update_series(self, ohb, ws, timestamp=None):
        """
        Append new sample and redraw the graph.
        timestamp: seconds since epoch (float). If None, time.time() is used.
        """
        if timestamp is None:
            timestamp = time.time()

        self.history_times.append(timestamp)
        self.history_ohb.append(ohb)
        self.history_ws.append(ws)
        self._limit_history()
        self._redraw()

    def _redraw(self):
        """
        Redraws the line graph using stored history.
        """
        # Clear previous plotted lines and tick labels
        self.canvas.delete("graph_line")
        self.canvas.delete("graph_axis")

        if len(self.history_times) < 2:
            return

        # Determine Y scale
        max_val = max(
            max(self.history_ohb),
            max(self.history_ws),
            1  # avoid division by zero
        )
        self.canvas.itemconfigure(self.y_label_id, text=f"Max: {max_val}")

        # Y ticks at 0, mid, max
        y_span = self.plot_bottom - self.plot_top
        if y_span <= 0:
            return

        for val in (0, max_val / 2.0, max_val):
            y = self.plot_bottom - (val / max_val) * y_span
            self.canvas.create_line(self.plot_left - 5, y,
                                    self.plot_left, y,
                                    fill="#bbbbbb",
                                    tags="graph_axis")
            self.canvas.create_text(self.plot_left - 10, y,
                                    text=f"{val:.0f}",
                                    anchor="e",
                                    font=(FONT_FAMILY, 8),
                                    fill="#555555",
                                    tags="graph_axis")

        # Time (X) scale
        t_min = self.history_times[0]
        t_max = self.history_times[-1]
        if t_max <= t_min:
            t_max = t_min + 1  # avoid div-zero / same time

        x_span = self.plot_right - self.plot_left
        if x_span <= 0:
            return

        n = len(self.history_times)

        def build_points(series):
            pts = []
            for t, v in zip(self.history_times, series):
                x = self.plot_left + ( (t - t_min) / (t_max - t_min) ) * x_span
                y = self.plot_bottom - (v / max_val) * y_span
                pts.extend((x, y))
            return pts

        # X-axis hour ticks (HH:MM)
        # Find first full hour >= t_min and step by 1 hour
        import math
        first_hour = math.floor(t_min / 3600.0) * 3600.0
        tick_t = first_hour
        while tick_t <= t_max + 1:
            if tick_t >= t_min:
                x = self.plot_left + ( (tick_t - t_min) / (t_max - t_min) ) * x_span
                # Tick line
                self.canvas.create_line(x, self.plot_bottom,
                                        x, self.plot_bottom + 5,
                                        fill="#bbbbbb",
                                        tags="graph_axis")
                # Time label
                label = time.strftime("%H:%M", time.localtime(tick_t))
                self.canvas.create_text(x, self.plot_bottom + 16,
                                        text=label,
                                        anchor="n",
                                        font=(FONT_FAMILY, 8),
                                        fill="#555555",
                                        tags="graph_axis")
            tick_t += 3600.0  # step 1 hour

        # Lines: OHB (orange), WS (green)
        ohb_pts = build_points(self.history_ohb)
        ws_pts = build_points(self.history_ws)

        if len(ohb_pts) >= 4:
            self.canvas.create_line(*ohb_pts, fill="#e67e22", width=1, tags="graph_line")
        if len(ws_pts) >= 4:
            self.canvas.create_line(*ws_pts, fill="#27ae60", width=1, tags="graph_line")

# -----------------------------------------------------------------------------
# Build UI
# -----------------------------------------------------------------------------
main = tk.Tk()
main.title("Wet Section Buffer Counter")
main.configure(bg=WINDOW_BG)
main.attributes("-fullscreen", True)

# Exit fullscreen on ESC
main.bind("<Escape>", lambda e: main.destroy())

# Header
header = tk.Label(main, text="Wet Section Buffer Counter", font=(FONT_FAMILY, 34, "bold"),
                  fg=TITLE_COLOR, bg=WINDOW_BG)
header.pack(pady=(30, 20))

# Frame to center bottom cards + graph
bottom_frame = tk.Frame(main, bg=WINDOW_BG)
bottom_frame.pack(expand=True)

# Total trays card (wide)
total_card = Card(bottom_frame, width=780, height=220, title="Total Trays",
                  title_font=(FONT_FAMILY, 18, "normal"), value_font=(FONT_FAMILY, 88, "bold"))
total_card.pack(pady=(0, 40))

# Container frame for OHB and WS cards side-by-side
cards_container = tk.Frame(bottom_frame, bg=WINDOW_BG)
cards_container.pack()

# Overhead Buffer card
ohb_card = ProgressCard(cards_container, width=380, height=150, title="Overhead Buffer",
                        title_font=(FONT_FAMILY, 14, "bold"), value_font=(FONT_FAMILY, 20, "bold"),
                        progress_max=OHB_PROGRESS_MAX, thresholds=OHB_THRESHOLDS)
ohb_card.pack(side="left", padx=20)

# Wet Section card
ws_card = ProgressCard(cards_container, width=380, height=150, title="Wet Section",
                       title_font=(FONT_FAMILY, 14, "bold"), value_font=(FONT_FAMILY, 20, "bold"),
                       progress_max=WS_PROGRESS_MAX, thresholds=WS_THRESHOLDS)
ws_card.pack(side="left", padx=20)

# Graph panel (under cards)
graph_panel = TrendGraph(bottom_frame, width=780, height=260,
                         title="Counts Over Time (OHB / WS)")
graph_panel.pack(pady=(40, 10))

# Instruction label
instr = tk.Label(main, text="Press ESC to exit", font=(FONT_FAMILY, 14), bg=WINDOW_BG, fg="#333333")
instr.pack(pady=(10, 40))

# -----------------------------------------------------------------------------
# Sensor reading & UI update loop
# (EDGE DETECTION + PER-SENSOR COOLDOWN AFTER RELEASE)
# -----------------------------------------------------------------------------
def read_inputs_and_update():
    """
    Poll sensors and update counts.

    Logic summary (per-channel, independent):
    - On rising edge (sensor: LOW -> HIGH):
        - Mark sensor as "held".
        - If (now - that sensor's last release time) >= its configured delay,
          apply the corresponding +/- count.
    - On falling edge (sensor: HIGH -> LOW):
        - Record the release time for that sensor.
        - Clear the held flag.
    """
    global sum_ohb, sum_ws
    global prev_total, prev_ohb, prev_ws
    global sig_ohb_add_detected, sig_ohb_sub_detected, sig_ws_add_detected, sig_ws_sub_detected
    global timer_ohb_add, timer_ohb_sub, timer_ws_add, timer_ws_sub

    try:
        s1 = rel.get_in(CHANNEL_OHB_ADD)
        s2 = rel.get_in(CHANNEL_OHB_SUB)
        s3 = rel.get_in(CHANNEL_WS_ADD)
        s4 = rel.get_in(CHANNEL_WS_SUB)
    except Exception:
        # hardware read failed; retry after a short delay
        main.after(max(200, POLL_INTERVAL_MS), read_inputs_and_update)
        return

    # Use millisecond timestamps to match *_DELAY_MS units
    now_ms = int(time.time() * 1000)

    # -------------------------
    # Overhead Buffer add (channel 1)
    # -------------------------
    if s1 == 1 and not sig_ohb_add_detected:
        sig_ohb_add_detected = True
        if (now_ms - timer_ohb_add) >= OHB_ADD_DELAY_MS:
            sum_ohb += 1
    elif s1 != 1 and sig_ohb_add_detected:
        timer_ohb_add = now_ms
        sig_ohb_add_detected = False

    # -------------------------
    # Overhead Buffer subtract (channel 2)
    # -------------------------
    if s2 == 1 and not sig_ohb_sub_detected:
        sig_ohb_sub_detected = True
        if (now_ms - timer_ohb_sub) >= OHB_SUB_DELAY_MS:
            if sum_ohb > 0:
                sum_ohb -= 1
    elif s2 != 1 and sig_ohb_sub_detected:
        timer_ohb_sub = now_ms
        sig_ohb_sub_detected = False

    # -------------------------
    # Wet Section add (channel 3)
    # -------------------------
    if s3 == 1 and not sig_ws_add_detected:
        sig_ws_add_detected = True
        if (now_ms - timer_ws_add) >= WS_ADD_DELAY_MS:
            sum_ws += 1
    elif s3 != 1 and sig_ws_add_detected:
        timer_ws_add = now_ms
        sig_ws_add_detected = False

    # -------------------------
    # Wet Section subtract (channel 4)
    # -------------------------
    if s4 == 1 and not sig_ws_sub_detected:
        sig_ws_sub_detected = True
        if (now_ms - timer_ws_sub) >= WS_SUB_DELAY_MS:
            if sum_ws > 0:
                sum_ws -= 1
    elif s4 != 1 and sig_ws_sub_detected:
        timer_ws_sub = now_ms
        sig_ws_sub_detected = False

    # -------------------------
    # Update UI (only when values changed)
    # -------------------------
    total = sum_ohb + sum_ws
    counts_changed = False

    if total != prev_total:
        total_card.set_value(total)
        prev_total = total
        counts_changed = True

    if sum_ohb != prev_ohb:
        ohb_card.set_value(sum_ohb)
        prev_ohb = sum_ohb
        counts_changed = True

    if sum_ws != prev_ws:
        ws_card.set_value(sum_ws)
        prev_ws = sum_ws
        counts_changed = True

    # Update graph only when something changed (OHB/WS only)
    if counts_changed:
        now_ts = time.time()
        graph_panel.update_series(sum_ohb, sum_ws, timestamp=now_ts)

    # Schedule next poll
    main.after(POLL_INTERVAL_MS, read_inputs_and_update)

# Start the loop
main.after(200, read_inputs_and_update)
main.mainloop()
