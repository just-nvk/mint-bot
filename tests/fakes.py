"""Тестовый Telegram: перехватывает запросы бота и ведёт «чат», в котором можно нажимать кнопки."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import EditMessageReplyMarkup, EditMessageText, SendMessage, TelegramMethod
from aiogram.types import CallbackQuery, Chat, InlineKeyboardMarkup, Message, Update, User

BOT_USER = User(id=42, is_bot=True, first_name="Мята · запись", username="mint_demo_bot")


class FakeSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.log: list[tuple[TelegramMethod, Any]] = []
        self.fail: Callable[[TelegramMethod], Exception | None] | None = None
        self._message_id = 100

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None) -> Any:
        if self.fail is not None and (error := self.fail(method)) is not None:
            raise error
        result: Any = True
        if isinstance(method, SendMessage):
            self._message_id += 1
            result = Message(
                message_id=self._message_id, date=datetime.now(UTC), chat=_chat(int(method.chat_id)),
                from_user=BOT_USER, text=method.text, reply_markup=method.reply_markup,
            )
        self.log.append((method, result))
        return result

    async def close(self) -> None:
        pass

    async def stream_content(self, *args: Any, **kwargs: Any):  # pragma: no cover
        yield b""


def labels(markup: InlineKeyboardMarkup | None) -> list[list[str]] | None:
    return [[b.text for b in row] for row in markup.inline_keyboard] if markup else None


@dataclass
class Shown:
    chat_id: int
    message_id: int
    text: str
    markup: InlineKeyboardMarkup | None

    @property
    def keyboard(self) -> list[list[str]] | None:
        return labels(self.markup)


@dataclass
class Conversation:
    """Что видит пользователь: сообщения бота с текущими кнопками."""
    dp: Dispatcher
    bot: Bot
    session: FakeSession
    user: User
    messages: dict[tuple[int, int], Shown] = field(default_factory=dict)
    _cursor: int = 0
    _update_id: int = 0

    def sync(self) -> list[TelegramMethod]:
        new = self.session.log[self._cursor:]
        self._cursor = len(self.session.log)
        for method, result in new:
            if isinstance(method, SendMessage):
                self.messages[(result.chat.id, result.message_id)] = Shown(
                    result.chat.id, result.message_id, method.text, method.reply_markup)
            elif isinstance(method, EditMessageText):
                shown = self.messages[(int(method.chat_id), method.message_id)]
                shown.text, shown.markup = method.text, method.reply_markup
            elif isinstance(method, EditMessageReplyMarkup):
                self.messages[(int(method.chat_id), method.message_id)].markup = method.reply_markup
        return [m for m, _ in new]

    def _next_update_id(self) -> int:
        self._update_id += 1
        return self._update_id

    async def send(self, text: str, chat_id: int | None = None) -> list[TelegramMethod]:
        """Пользователь пишет боту — в личку или, если указан chat_id, в группу."""
        self.sync()
        message = Message(
            message_id=self._next_update_id(), date=datetime.now(UTC),
            chat=_chat(self.user.id if chat_id is None else chat_id), from_user=self.user, text=text,
        )
        await self.dp.feed_update(self.bot, Update(update_id=self._next_update_id(), message=message))
        return self.sync()

    def find(self, label: str) -> tuple[Shown, str]:
        """Самое свежее сообщение в чате пользователя с кнопкой label."""
        for shown in sorted(self.messages.values(), key=lambda s: s.message_id, reverse=True):
            if shown.chat_id != self.user.id or not shown.markup:
                continue
            for row in shown.markup.inline_keyboard:
                for button in row:
                    if button.text == label:
                        return shown, button.callback_data
        raise AssertionError(f"Кнопки «{label}» нет в чате")

    async def tap(self, label: str, *, shown: Shown | None = None) -> list[TelegramMethod]:
        self.sync()
        if shown is None:
            shown, data = self.find(label)
        else:
            data = next(b.callback_data for row in shown.markup.inline_keyboard for b in row if b.text == label)
        await self.press(shown, data)
        return self.sync()

    async def press(self, shown: Shown, data: str) -> None:
        message = Message(
            message_id=shown.message_id, date=datetime.now(UTC), chat=_chat(shown.chat_id),
            from_user=BOT_USER, text=shown.text, reply_markup=shown.markup,
        )
        query = CallbackQuery(id=str(self._next_update_id()), from_user=self.user, chat_instance="test",
                              message=message, data=data)
        await self.dp.feed_update(self.bot, Update(update_id=self._next_update_id(), callback_query=query))

    def last(self, chat_id: int | None = None) -> Shown:
        chat_id = self.user.id if chat_id is None else chat_id
        return max((s for s in self.messages.values() if s.chat_id == chat_id), key=lambda s: s.message_id)


def _chat(chat_id: int) -> Chat:
    return Chat(id=chat_id, type="private" if chat_id > 0 else "supergroup")


def sent(methods: list[TelegramMethod], chat_id: int | None = None) -> list[SendMessage]:
    return [m for m in methods if isinstance(m, SendMessage) and (chat_id is None or int(m.chat_id) == chat_id)]
