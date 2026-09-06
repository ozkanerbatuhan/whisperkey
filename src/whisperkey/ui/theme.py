"""Visual language: a measuring instrument in an anodized body.

The colors come from device vernacular - graphite shell, amber phosphor
meter, signal red. Nothing decorative: every color encodes a state.
"""

# body
KEY = "#FF00FF"          # transparency key - never visible on screen
SHELL = "#171A1F"
RAIL = "#2A2F37"
WELL = "#20252C"         # meter well

# text
INK = "#C8CDD4"
INK_DIM = "#6E7681"

# state
LIVE = "#E8552B"         # recording
AMBER = "#FFB000"        # level / working
DONE = "#4FB477"
FAIL = "#E8552B"
IDLE_TICK = "#262B33"

FONT_UI = ("Segoe UI", 10)
FONT_UI_SEMI = ("Segoe UI Semibold", 10)
FONT_MONO = ("Cascadia Mono", 9)
FONT_MONO_FALLBACK = ("Consolas", 9)

WIDTH = 360
HEIGHT = 56
RADIUS = 10
TICKS = 34
CLIP_ZONE = 4            # this many trailing ticks warn about clipping
