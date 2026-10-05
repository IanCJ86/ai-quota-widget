"""Shared UI tokens; importing this module creates no windows or services."""

TRANSP_KEY = "#010102"  # glass colorkey: root pixels of this color go transparent
def _palette(label, bg, card, text, muted, border, accent, brands,
             warning, danger, relief="flat", border_width=0):
    return dict(LABEL=label, BG=bg, BG_CARD=card, FG_TEXT=text, FG_DIM=muted,
                BORDER=border, ACCENT=accent,
                BRANDS=dict.fromkeys(("Kimi", "GLM", "Codex", "DeepSeek"), brands[3]),
                KIMI_SOFT=brands[0], GLM_SOFT=brands[1], CODEX_SOFT=brands[2], DEEPSEEK_SOFT=brands[3],
                WARNING=warning, DANGER=danger, RELIEF=relief, BORDER_WIDTH=border_width)


# Stable config IDs: old dark/light preferences become the two lunar skins.
THEMES = {
    "dark": _palette("月之暗面", "#11151c", "#1b222c", "#f1f4f8", "#b1bccb", "#303b49", "#c6ddff",
                     ("#9cc6ff", "#d0b5ff", "#d8dfea", "#a7b8ff"), "#f4ba66", "#ff9191"),
    "light": _palette("月之亮面", "#eff3f8", "#ffffff", "#152438", "#536277", "#d6dee9", "#234f86",
                      ("#285785", "#6c4586", "#34435a", "#354e98"), "#875100", "#ac2634"),
    "steam": _palette("蒸汽算力机", "#211b16", "#322920", "#ffe8b6", "#cfb894", "#a8844f", "#e5b768",
                      ("#f3d595", "#f3d595", "#f3d595", "#f3d595"), "#ffc16b", "#ff9c8e", "ridge", 2),
    "fuel": _palette("Token 加油站", "#101f28", "#1a303b", "#f5f8e9", "#b7c9d1", "#38515c", "#e1f278",
                     ("#c6e8fb", "#c6e8fb", "#f0d6a2", "#c6e8fb"), "#ffd178", "#ffa398", border_width=1),
    "ink": _palette("电子墨水账本", "#e9e4d9", "#f6f2e8", "#272a26", "#55594f", "#b7b6aa", "#353e32",
                    ("#353e32", "#353e32", "#373b44", "#353e32"), "#79520c", "#9a3030"),
    "glass": _palette("毛玻璃", "#2b2b3d", "#2b2b3d", "#f2f2f8", "#b8b8cc", "#55556e", "#b4cfff",
                      ("#9cc6ff", "#d0b5ff", "#d8dfea", "#a7b8ff"), "#f4ba66", "#ff9191", border_width=1),
}
THEME_CHOICES = tuple((palette["LABEL"], key) for key, palette in THEMES.items())
# Soft red/green on dark cards; darker equivalents retain contrast on light cards.
for key, palette in THEMES.items():
    palette['RADAR_UP'] = '#b54d58' if key in ('light', 'ink') else '#ffaaaa'
    palette['RADAR_DOWN'] = '#387d5c' if key in ('light', 'ink') else '#a1d9b4'
BG = "#1e1e2e"
BG_CARD = "#262638"
FG_DIM = "#7a7a90"
FG_TEXT = "#e8e8f4"
KIMI_BLUE = "#5b9dff"
CODEX_NEUTRAL = "#d8dfea"
KIMI_BLUE_SOFT = "#8db4e8"
CODEX_NEUTRAL_SOFT = "#d8dfea"
GLM_PURPLE = "#b48cff"
GLM_PURPLE_SOFT = "#c9b3f2"
DEEPSEEK_BLUE = "#4d6bfe"
DEEPSEEK_SOFT = "#8fa2ff"
# One type scale for the whole widget: card titles 9, every body row (labels,
# values, notes) and the refresh line 8.  Same-role text uses the same size;
# values are told apart by weight only.
FONT_FAMILY = "Microsoft YaHei UI"
FONT_TITLE = (FONT_FAMILY, 9, "bold")
FONT_TEXT = (FONT_FAMILY, 8)
FONT_VALUE = (FONT_FAMILY, 8, "bold")
FONT_STATUS = (FONT_FAMILY, 8)
FONT_HINT = (FONT_FAMILY, 8)
# Money is padded to a shared integer width so its currency symbol and decimal
# point line up.  An ordinary space cannot do that (it is 3px where a digit is
# 7px) and a monospaced font makes the amounts look spaced out next to the
# percentages; U+2002 happens to be exactly one digit wide in this font.
MONEY_PAD = "\u2002"
# A card title shares its row with the renewal date. They are placed left and
# right so they can never overlap; this cap only stops an absurd plan name from
# taking the whole row.
TITLE_MAX_PX = 220
# How much width the widest title may add to the value column so that it can sit
# left of the renewal date, and the breathing room kept between the two.
TITLE_RESERVE_MAX = 40
TITLE_GAP = 8        # minimum space between a title and the renewal date
TITLE_SLACK = 6      # font metrics can differ a little between processes
PLAN_PRESETS = {
    "kimi": ["Andante", "Moderato", "Allegretto", "Allegro"],
    "codex": ["Go", "Plus", "Pro 5x", "Pro 20x"],
    "glm": ["Lite", "Pro", "Max"],
}
PLAN_CFG_KEY = {"kimi": "kimi_plan_name", "codex": "codex_plan_name",
                "glm": "glm_plan_name"}
