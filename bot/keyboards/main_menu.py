from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton


def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🏠 Dashboard"),
                KeyboardButton(text="➕ Add Account"),
                KeyboardButton(text="👤 My Accounts"),
            ],
            [
                KeyboardButton(text="💬 Messages"),
                KeyboardButton(text="⏰ Scheduler"),
            ],
            [
                KeyboardButton(text="▶️ Start"),
                KeyboardButton(text="⏸ Pause"),
                KeyboardButton(text="⏹ Stop"),
            ],
            [
                KeyboardButton(text="📊 Status"),
                KeyboardButton(text="💳 Subscription"),
            ],
            [
                KeyboardButton(text="⚙️ Settings"),
                KeyboardButton(text="🆘 Support"),
            ],
        ],
        resize_keyboard=True,
        persistent=True,
    )


def get_cancel_keyboard() -> ReplyKeyboardMarkup:
    """Keyboard shown during FSM flows — allows user to cancel and go back to main menu."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔙 Back to Main Menu")],
        ],
        resize_keyboard=True,
    )


def get_back_inline_button() -> InlineKeyboardMarkup:
    """Simple inline Back button for inline menus."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Back to Main Menu", callback_data="back_to_main")]
        ]
    )
