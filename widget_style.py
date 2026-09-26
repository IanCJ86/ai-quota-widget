"""Shared UI tokens; importing this module creates no windows or services."""

TRANSP_KEY = "#010102"  # glass colorkey: root pixels of this color go transparent
THEMES = {
    "dark": dict(BG="#1e1e2e", BG_CARD="#262638", BORDER="#3a3a4e",
                 FG_DIM="#7a7a90", FG_TEXT="#e8e8f4",
                 KIMI_SOFT="#8db4e8", CODEX_SOFT="#83d4ab"),
    "light": dict(BG="#f2f3f7", BG_CARD="#ffffff", BORDER="#d9dae4",
                  FG_DIM="#8a8a9a", FG_TEXT="#23233a",
                  KIMI_SOFT="#4a7fc9", CODEX_SOFT="#3a9e6e"),
    # glass: root/spacer/bar pixels use TRANSP_KEY and become see-through,
    # acrylic blur is applied behind them; cards stay solid for readability
    "glass": dict(BG=TRANSP_KEY, BG_CARD="#2b2b3d", BORDER="#55556e",
                  FG_DIM="#a0a0b8", FG_TEXT="#f2f2f8",
                  KIMI_SOFT="#8db4e8", CODEX_SOFT="#83d4ab"),
}
BG = "#1e1e2e"
BG_CARD = "#262638"
FG_DIM = "#7a7a90"
FG_TEXT = "#e8e8f4"
KIMI_BLUE = "#5b9dff"
CODEX_GREEN = "#4ecf8a"
KIMI_BLUE_SOFT = "#8db4e8"
CODEX_GREEN_SOFT = "#83d4ab"
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
