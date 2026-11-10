"""DinoWrite look: colors and window shape shared by all windows"""

COLORS = {
    "white": "#dedede",
    "grey-bright": "#373737",
    "grey": "#2d2d2d",
    "grey-dark": "#131313",
    "red": "#ec3c48",
    "crimson": "#ff6570",
    "orange": "#fa7960",
    "yellow": "#f1d018",
    "green": "#04e762",
    "blue": "#00b6f8",
    "accent": "#b78620",
}

# One meaning per color in both windows (stylesheets.json uses the same values):
STATES = {
    "hover": "#7a7a7a",      # lighter neutral border/background under the mouse
    "focus": "#3d9be9",      # the field being typed into
    "selected": "#b78620",   # active tab, primary button (Save), open menu item
    "changed": "#b78620",    # dot + bold: a setting differs from the default
    "warning": "#f0b429",    # works, but check it (stretched aspect, overwrite, folder will be created)
    "error": "#ec3c48",      # can't work like this (bad name, unknown placeholder, tool not found)
    "danger": "#ec3c48",     # a destructive option is ON
}

WINDOW_RADIUS = 15
TITLE_BUTTON_SIZE = 20

# Primary action of a window (WRITE, Save): the accent color; secondary buttons stay neutral
PRIMARY_STYLE = f"""
QPushButton {{ background-color: {STATES['selected']}; color: #141414; border: 1px solid #d6a234; font-weight: bold; }}
QPushButton:hover {{ background-color: #cf9a2a; border: 1px solid #f0c060; }}
QPushButton:pressed {{ background-color: #94701e; }}
QPushButton:disabled {{ background-color: #3a3a3a; color: #777; border: 1px solid #444; }}
"""
