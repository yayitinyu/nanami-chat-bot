from __future__ import annotations

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from app.admins import AdminFilter, AdminStore
from app.handlers import admin_menu, captcha, errors, start, user


def register(application: Application, store: AdminStore) -> None:
    admin = AdminFilter(store)
    private = filters.ChatType.PRIVATE
    not_edited = ~filters.UpdateType.EDITED_MESSAGE

    application.add_handler(
        CommandHandler("start", start.cmd_start, filters=private & not_edited)
    )
    application.add_handler(
        CommandHandler("help", start.cmd_help, filters=private & not_edited)
    )
    application.add_handler(
        CommandHandler("id", start.cmd_id, filters=private & not_edited)
    )
    application.add_handler(
        CommandHandler("admin", admin_menu.cmd_admin, filters=admin & not_edited)
    )
    application.add_handler(
        CommandHandler("cancel", admin_menu.cmd_cancel, filters=admin & not_edited)
    )
    application.add_handler(
        CommandHandler("ban", admin_menu.cmd_ban, filters=admin & not_edited)
    )
    application.add_handler(
        CommandHandler("unban", admin_menu.cmd_unban, filters=admin & not_edited)
    )

    application.add_handler(CallbackQueryHandler(captcha.on_callback, pattern=r"^c:x:"))
    application.add_handler(CallbackQueryHandler(admin_menu.on_callback))

    application.add_handler(
        MessageHandler(
            admin & ~filters.COMMAND & not_edited,
            admin_menu.on_admin_message,
        )
    )
    application.add_handler(
        MessageHandler(
            private
            & ~filters.COMMAND
            & ~filters.UpdateType.EDITED_MESSAGE
            & ~admin,
            user.on_user_message,
        )
    )
    application.add_handler(
        MessageHandler(
            private & filters.UpdateType.EDITED_MESSAGE & ~admin,
            user.on_user_edit,
        )
    )
    application.add_handler(
        ChatMemberHandler(user.on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER)
    )
    application.add_error_handler(errors.on_error)
