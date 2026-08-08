from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from services.subscription_service import get_active_pricing, is_sale_active


def get_subscription_plans_keyboard() -> InlineKeyboardMarkup:
    plans = get_active_pricing()
    sale = is_sale_active()
    badge = "🔥 " if sale else ""

    p1  = plans[1]["price"]
    p7  = plans[7]["price"]
    p30 = plans[30]["price"]

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=f"{badge}1 Day – ₹{p1}",   callback_data="buy_sub_1"),
                InlineKeyboardButton(text=f"{badge}7 Days – ₹{p7}",  callback_data="buy_sub_7"),
            ],
            [
                InlineKeyboardButton(text=f"{badge}30 Days – ₹{p30}", callback_data="buy_sub_30"),
            ],
            [
                InlineKeyboardButton(text="🔄 Verify Payment", callback_data="verify_payment"),
            ],
            [
                InlineKeyboardButton(text="🔙 Back", callback_data="back_to_main"),
            ],
        ]
    )



def get_account_manage_keyboard(account_id: int, is_active: bool) -> InlineKeyboardMarkup:
    toggle_text = "⏸ Deactivate Account" if is_active else "▶️ Activate Account"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=toggle_text, callback_data=f"acc_toggle_{account_id}"),
                InlineKeyboardButton(text="🔄 Re-login", callback_data=f"acc_relogin_{account_id}"),
            ],
            [
                InlineKeyboardButton(text="⚙️ Config Message & Timer", callback_data=f"acc_msg_cfg_{account_id}"),
            ],
            [
                InlineKeyboardButton(text="🗑 Remove Account", callback_data=f"acc_delete_{account_id}"),
            ],
            [
                InlineKeyboardButton(text="🔙 Back", callback_data="back_to_main"),
            ],
        ]
    )


def get_messages_accounts_keyboard(accounts: list) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="🌐 Common Message (All Accounts)", callback_data="cfg_common_msg")],
        [InlineKeyboardButton(text="⏱ Common Timer (All Accounts)", callback_data="cfg_common_timer")],
    ]
    for acc in accounts:
        msg_status = "💬 Message Set" if acc.custom_message else "⚠️ No Message"
        toggle_icon = "🟢 ENABLED" if acc.auto_group_enabled else "🔴 DISABLED"
        label = f"📱 {acc.phone_number} | {msg_status} | {toggle_icon}"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"acc_msg_cfg_{acc.id}")])

    buttons.append([InlineKeyboardButton(text="🔙 Back to Main Menu", callback_data="back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_account_msg_config_keyboard(account_id: int, auto_group_enabled: bool) -> InlineKeyboardMarkup:
    toggle_text = "🟢 Auto-Messaging: ENABLED (Tap to Disable)" if auto_group_enabled else "🔴 Auto-Messaging: DISABLED (Tap to Enable)"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📝 Set / Edit Message", callback_data=f"cfg_set_msg_{account_id}"),
                InlineKeyboardButton(text="⏱ Set Timer (Mins)", callback_data=f"cfg_set_timer_{account_id}"),
            ],
            [
                InlineKeyboardButton(text=toggle_text, callback_data=f"cfg_toggle_group_{account_id}"),
            ],
            [
                InlineKeyboardButton(text="🔙 Back to Messages", callback_data="msg_list_accounts"),
            ],
        ]
    )


def get_timer_preset_keyboard(account_id: int) -> InlineKeyboardMarkup:
    back_cb = f"acc_msg_cfg_{account_id}" if account_id > 0 else "msg_list_accounts"
    back_text = "🔙 Back to Account Config" if account_id > 0 else "🔙 Back to Messages"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⚡ 1 min", callback_data=f"set_timer_val_{account_id}_1"),
                InlineKeyboardButton(text="⏱ 2 min", callback_data=f"set_timer_val_{account_id}_2"),
                InlineKeyboardButton(text="⏱ 5 min", callback_data=f"set_timer_val_{account_id}_5"),
                InlineKeyboardButton(text="⏱ 10 min", callback_data=f"set_timer_val_{account_id}_10"),
            ],
            [
                InlineKeyboardButton(text="⏱ 30 min", callback_data=f"set_timer_val_{account_id}_30"),
                InlineKeyboardButton(text="⌛ 1 hr", callback_data=f"set_timer_val_{account_id}_60"),
                InlineKeyboardButton(text="⌛ 2 hr", callback_data=f"set_timer_val_{account_id}_120"),
                InlineKeyboardButton(text="⌛ 5 hr", callback_data=f"set_timer_val_{account_id}_300"),
            ],
            [
                InlineKeyboardButton(text=back_text, callback_data=back_cb),
            ],
        ]
    )



