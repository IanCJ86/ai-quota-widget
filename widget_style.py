"""Shared UI tokens; importing this module creates no windows or services."""

TRANSP_KEY = "#010102"  # glass colorkey: root pixels of this color go transparent


def _palette(label, bg, card, text, muted, border, accent, brands,
             warning, danger, track, relief="flat", border_width=0):
    kimi, glm, codex, antigravity, deepseek = brands
    return dict(
        LABEL=label, BG=bg, BG_CARD=card, FG_TEXT=text, FG_DIM=muted,
        BORDER=border, ACCENT=accent, TRACK=track,
        BRANDS=dict.fromkeys(("Kimi", "GLM", "Codex", "Antigravity", "DeepSeek"), deepseek),
        CARD_ACCENTS={
            "Kimi": kimi,
            "GLM": glm,
            "Codex": codex,
            "Antigravity": antigravity,
            "DeepSeek": deepseek,
        },
        KIMI_SOFT=kimi, GLM_SOFT=glm, CODEX_SOFT=codex,
        ANTIGRAVITY_SOFT=antigravity, DEEPSEEK_SOFT=deepseek,
        WARNING=warning, DANGER=danger,
        RELIEF=relief, BORDER_WIDTH=border_width,
    )


# Stable config IDs: old dark/light preferences become the two lunar skins.
# Every foreground/brand token is calibrated for WCAG AA (>= 4.5:1) against BG_CARD.
THEMES = {
    "dark": _palette(
        "月之暗面", "#0c1017", "#151b26", "#f1f5f9", "#97a6bd", "#253145", "#9ec5ff",
        ("#82bcff", "#c7a8ff", "#74e5ba", "#6ee7f9", "#99b8ff"),
        "#f6be58", "#ff8787", "#232e40",
    ),
    "light": _palette(
        "月之亮面", "#edf2f8", "#ffffff", "#122033", "#516075", "#d3dfec", "#1f57a4",
        ("#1d57a8", "#6b3fa0", "#0e7054", "#0b6b84", "#2f4fb0"),
        "#945300", "#be2436", "#e4ecf5",
    ),
    "steam": _palette(
        "蒸汽算力机", "#1a140f", "#282018", "#ffedc2", "#cfb791", "#9e7b45", "#f0be67",
        ("#f4d18b", "#e9be8c", "#d4dd8c", "#98e0d0", "#f3d595"),
        "#ffc16b", "#ff9482", "#3d3023", "ridge", 2,
    ),
    "fuel": _palette(
        "Token 加油站", "#0c1921", "#142630", "#f4f8e8", "#a9c1cb", "#2c4957", "#dff26d",
        ("#9edcff", "#d0beff", "#dff26d", "#78f0e4", "#a8d4ff"),
        "#ffd178", "#ff988c", "#203a47", border_width=1,
    ),
    "ink": _palette(
        "电子墨水账本", "#eae4d8", "#f7f3ea", "#1f2421", "#52574d", "#c2bcb0", "#2f3b31",
        ("#27496d", "#573b6e", "#255240", "#1d5563", "#2f4169"),
        "#7d4e08", "#a12b2b", "#ded8cb",
    ),
    "glass": _palette(
        "毛玻璃", "#121622", "#1b2133", "#f3f6fc", "#9aa8c2", "#2d3752", "#7cc4ff",
        ("#7cb8ff", "#c4a5ff", "#6ee7b7", "#67e8f9", "#93b4ff"),
        "#fbbf24", "#fb7185", "#28324a", border_width=1,
    ),
}
THEME_CHOICES = tuple((palette["LABEL"], key) for key, palette in THEMES.items())
# Soft red/green on dark cards; darker equivalents retain contrast on light cards.
for key, palette in THEMES.items():
    palette["RADAR_UP"] = "#b54d58" if key in ("light", "ink") else "#ff9fa8"
    palette["RADAR_DOWN"] = "#2f7a58" if key in ("light", "ink") else "#7ee2b8"

BG = "#121622"
BG_CARD = "#1b2133"
FG_DIM = "#9aa8c2"
FG_TEXT = "#f3f6fc"
KIMI_BLUE = "#7cb8ff"
CODEX_NEUTRAL = "#6ee7b7"
KIMI_BLUE_SOFT = "#7cb8ff"
CODEX_NEUTRAL_SOFT = "#6ee7b7"
GLM_PURPLE = "#c4a5ff"
GLM_PURPLE_SOFT = "#c4a5ff"
ANTIGRAVITY_CYAN = "#67e8f9"
ANTIGRAVITY_SOFT = "#67e8f9"
DEEPSEEK_BLUE = "#93b4ff"
DEEPSEEK_SOFT = "#93b4ff"

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
    "antigravity": ["Free", "Plus", "Pro", "Ultra"],
}
PLAN_CFG_KEY = {
    "kimi": "kimi_plan_name",
    "codex": "codex_plan_name",
    "glm": "glm_plan_name",
    "antigravity": "antigravity_plan_name",
}
