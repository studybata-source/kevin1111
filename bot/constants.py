BUTTON_SEARCH = "Find Track"
BUTTON_DOWNLOAD = "Get Audio"
BUTTON_LYRICS = "Lyrics"
BUTTON_SETTINGS = "Settings"
BUTTON_HISTORY = "Recents"
BUTTON_HELP = "Help"

MENU_TEXTS = frozenset(
    {
        BUTTON_SEARCH,
        BUTTON_DOWNLOAD,
        BUTTON_LYRICS,
        BUTTON_SETTINGS,
        BUTTON_HISTORY,
        BUTTON_HELP,
    }
)

QUALITY_LABELS = {
    "best": "Max quality",
    "balanced": "Balanced",
    "small": "Lite file",
}

QUALITY_DESCRIPTIONS = {
    "best": "Default mode. Push for the cleanest audio this bot can send.",
    "balanced": "Keep strong quality without making files too heavy.",
    "small": "Use lighter files when speed matters more than quality.",
}

FORMAT_LABELS = {
    "mp3": "MP3",
    "m4a": "M4A",
    "opus": "Opus",
    "original": "Original",
}

FORMAT_DESCRIPTIONS = {
    "mp3": "Most compatible. Best pick for everyday Telegram use.",
    "m4a": "Clean AAC audio with smaller files than MP3 at similar quality.",
    "opus": "Efficient streaming-friendly format for lightweight listening.",
    "original": "Keep the source container when possible instead of converting.",
}

COMMANDS = [
    ("start", "Start the bot"),
    ("help", "Show help"),
    ("settings", "Audio quality settings"),
    ("search", "Show song matches"),
    ("song", "Fetch the track directly"),
    ("download", "Fetch from a song name or link"),
    ("lyrics", "Show lyrics for a song"),
    ("history", "Show recent searches"),
    ("cancel", "Cancel the current flow"),
]

OWNER_COMMANDS = [
    ("stats", "Owner stats"),
    ("groups", "Tracked groups"),
    ("thischat", "Current chat info"),
    ("broadcast", "Broadcast to all chats"),
    ("broadcast_groups", "Broadcast to groups only"),
]

SUPPORTED_DOWNLOAD_PLATFORMS = (
    "YouTube",
    "TikTok",
    "Instagram",
    "Pinterest",
    "VK",
    "Rutube",
)
