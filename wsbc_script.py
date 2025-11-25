import tkinter as tk
import sm_4rel4in
import time

# -------------------------
# Hardware setup (leave as-is unless your board address changes)
# -------------------------
rel = sm_4rel4in.SM4rel4in(0)  # Initialize 4rel4in HAT
CHANNEL_OHB_ADD = 1   # Overhead buffer add sensor
CHANNEL_OHB_SUB = 2   # Overhead buffer subtract sensor
CHANNEL_WS_ADD = 3    # Wet section add sensor
CHANNEL_WS_SUB = 4    # Wet section subtract sensor

# -------------------------
# CONFIGURATION
# -------------------------
# Thresholds for progress bar colors
# Format: (min_value, max_value, color_hex)
OHB_THRESHOLDS = [
    (None, 2, "#e74c3c"),   # Red
    (3, 5, "#f1c40f"),      # Yellow
    (6, None, "#2ecc71")    # Green
]
WS_THRESHOLDS = [
    (None, 1, "#e9e9e9"),   # Red #e74c3c
    (2, 4, "#e9e9e9"),      # Yellow #f1c40f
    (5, None, "#e9e9e9")    # Green #2ecc71
]

OHB_PROGRESS_MAX = 10  # Maximum value displayed on OHB progress bar
WS_PROGRESS_MAX = 10   # Maximum value displayed on WS progress bar

SENSOR_DELAY = 1000    # Delay in ms after sensor turns off before counting again (1000 = 1s) # Have seen issues with delay affecting all sensors
POLL_INTERVAL_MS = 10  # How often to poll sensors (ms)

# -------------------------
# Internal state (can set values here too)
# -------------------------
count_ohb = 0
count_ws = 0
sum_ohb = 0
sum_ws = 0

# Previous values for comparison to update UI only when needed
prev_total = -1
prev_ohb = -1
prev_ws = -1

# Sensor detection flags (true when sensor currently considered "held/high")
sig_ohb_add_detected = False
sig_ohb_sub_detected = False
sig_ws_add_detected = False
sig_ws_sub_detected = False

# Sensor delay timers (store timestamp in ms when sensor went LOW)
# A new rising edge is only accepted if now - timer_X >= SENSOR_DELAY
timer_ohb_add = 0
timer_ohb_sub = 0
timer_ws_add = 0
timer_ws_sub = 0

# -------------------------
# UI Helper functions
# -------------------------
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

# -------------------------
# Card Classes
# -------------------------
class Card:
    """
    A basic card that shows a title and a numeric value.
    """
    def __init__(self, parent, width, height, title="", title_font=(FONT_FAMILY, 18, "bold"),
                 value_font=(FONT_FAMILY, 48, "bold"), thresholds=None):
        self.width = width
        self.height = height
        self.thresholds = thresholds
        self.canvas = tk.Canvas(parent, width=width+8, height=height+8, bg=WINDOW_BG, highlightthickness=0)
        # Shadow
        rounded_rect(self.canvas, 4, 4, width+4, height+4, r=18, fill=SHADOW_COLOR, outline="")
        # Background gradient
        rounded_rect(self.canvas, 0, 0, width, height, r=18, fill=CARD_BG, outline="")
        # Title text
        self.title_id = self.canvas.create_text(width/2, height*0.3, text=title, font=title_font, fill=TITLE_COLOR)
        # Numeric value
        self.value_id = self.canvas.create_text(width/2, height*0.65, text="0", font=value_font, fill="black")
        self.current_value = 0

    def set_value(self, new_value):
        """
        Updates the numeric value displayed. Color does not change for flashing.
        """
        self.canvas.itemconfigure(self.value_id, text=str(new_value))
        self.current_value = new_value

    # Allow Card object to be packed or gridded directly
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
        self.left_title = self.canvas.create_text(width*0.12, height*0.26, anchor="w",
                                                  text=title, font=title_font, fill="#333333")
        # Right-aligned numeric value
        self.num_text = self.canvas.create_text(width*0.88, height*0.26, anchor="e",
                                                text="0", font=value_font, fill="black")
        # Track coordinates for progress bar
        self.track_x1 = width*0.12
        self.track_x2 = width*0.88
        self.track_y = height*0.72
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

    # Allow ProgressCard to be packed/gridded
    def pack(self, **kwargs):
        self.canvas.pack(**kwargs)
    def grid(self, **kwargs):
        self.canvas.grid(**kwargs)

# -------------------------
# Build UI
# -------------------------
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

# Frame to center bottom cards
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

# Instruction label
instr = tk.Label(main, text="Press ESC to exit", font=(FONT_FAMILY, 14), bg=WINDOW_BG, fg="#333333")
instr.pack(pady=(30, 40))

# -------------------------
# Sensor reading & UI update loop
# (EDGE DETECTION + COOLDOWN AFTER RELEASE)
# -------------------------
def read_inputs_and_update():
    """
    Poll sensors and update counts.

    Logic summary:
    - On rising edge (sensor goes LOW -> HIGH) we always set the "detected" flag
      to True (marks the sensor as held). If the previous release timer has aged
      past SENSOR_DELAY, we count immediately. If not, we do not count but still
      mark the sensor as held so holding won't cause a later auto-count.
    - On falling edge (sensor goes HIGH -> LOW), we set the timer to now. The
      next rising edge will only be accepted for counting if now - timer >= SENSOR_DELAY.
    """
    global count_ohb, count_ws, sum_ohb, sum_ws
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

    # Use millisecond timestamps to match SENSOR_DELAY unit
    now_ms = int(time.time() * 1000)

    # -------------------------
    # Overhead Buffer add (channel 1)
    # -------------------------
    # Rising edge: sensor is HIGH now and was previously not detected (i.e. rising moment)
    if s1 == 1 and not sig_ohb_add_detected:
        # Mark the sensor as held immediately (prevents auto-count later while held)
        sig_ohb_add_detected = True
        # If cooldown since last release has passed, count immediately
        if (now_ms - timer_ohb_add) >= SENSOR_DELAY:
            # We count instantly on the rising edge
            sum_ohb += 1

    # Falling edge: sensor went LOW while previously detected HIGH -> set the cooldown timer
    elif s1 != 1 and sig_ohb_add_detected:
        timer_ohb_add = now_ms
        sig_ohb_add_detected = False

    # -------------------------
    # Overhead Buffer subtract (channel 2)
    # -------------------------
    if s2 == 1 and not sig_ohb_sub_detected:
        sig_ohb_sub_detected = True
        if (now_ms - timer_ohb_sub) >= SENSOR_DELAY:
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
        if (now_ms - timer_ws_add) >= SENSOR_DELAY:
            sum_ws += 1
    elif s3 != 1 and sig_ws_add_detected:
        timer_ws_add = now_ms
        sig_ws_add_detected = False

    # -------------------------
    # Wet Section subtract (channel 4)
    # -------------------------
    if s4 == 1 and not sig_ws_sub_detected:
        sig_ws_sub_detected = True
        if (now_ms - timer_ws_sub) >= SENSOR_DELAY:
            if sum_ws > 0:
                sum_ws -= 1
    elif s4 != 1 and sig_ws_sub_detected:
        timer_ws_sub = now_ms
        sig_ws_sub_detected = False

    # -------------------------
    # Update UI (only when values changed)
    # -------------------------
    total = sum_ohb + sum_ws

    if total != prev_total:
        total_card.set_value(total)
        prev_total = total

    if sum_ohb != prev_ohb:
        ohb_card.set_value(sum_ohb)
        prev_ohb = sum_ohb

    if sum_ws != prev_ws:
        ws_card.set_value(sum_ws)
        prev_ws = sum_ws

    # Schedule next poll
    main.after(POLL_INTERVAL_MS, read_inputs_and_update)

# Start the loop
main.after(200, read_inputs_and_update)
main.mainloop()
