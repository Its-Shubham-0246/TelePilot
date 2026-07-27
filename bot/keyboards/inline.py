from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_subscription_plans_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="1 Day – ₹49", callback_data="buy_sub_1"),
                InlineKeyboardButton(text="7 Days – ₹199", callback_data="buy_sub_7"),
            ],
            [
                InlineKeyboardButton(text="30 Days – ₹399", callback_data="buy_sub_30"),
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
    buttons = []
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


def get_mode_selection_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📢 Auto Group Messaging", callback_data="mode_AUTO_GROUP"),
            ],
            [
                InlineKeyboardButton(text="💬 Auto DM (Intended)", callback_data="mode_AUTO_DM"),
            ],
            [
                InlineKeyboardButton(text="⚡ Both (Group + DM)", callback_data="mode_BOTH"),
            ],
            [
                InlineKeyboardButton(text="🔙 Back", callback_data="back_to_main"),
            ],
        ]
    )
