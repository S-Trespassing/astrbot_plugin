from __future__ import annotations

import importlib
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path


def _install_astrbot_stubs() -> None:
    if "astrbot" in sys.modules:
        return

    astrbot_module = types.ModuleType("astrbot")
    api_module = types.ModuleType("astrbot.api")
    event_module = types.ModuleType("astrbot.api.event")
    message_components_module = types.ModuleType("astrbot.api.message_components")
    star_module = types.ModuleType("astrbot.api.star")

    class _Logger:
        def info(self, *args, **kwargs):
            return None

        def warning(self, *args, **kwargs):
            return None

        def debug(self, *args, **kwargs):
            return None

        def error(self, *args, **kwargs):
            return None

        def exception(self, *args, **kwargs):
            return None

    class MessageChain:
        def __init__(self) -> None:
            self.parts: list[tuple[str, str]] = []

        def message(self, content: str):
            self.parts.append(("message", content))
            return self

        def file_image(self, content: str):
            self.parts.append(("file_image", content))
            return self

        def at(self, name: str, user_id: str):
            self.parts.append(("at", f"{name}:{user_id}"))
            return self

    class MessageEventResult:
        def __init__(self) -> None:
            self.content = ""
            self.stopped = False

        def message(self, content: str):
            self.content = content
            return self

        def stop_event(self):
            self.stopped = True
            return self

    class _Filter:
        class EventMessageType:
            GROUP_MESSAGE = "group"
            PRIVATE_MESSAGE = "private"

        @staticmethod
        def event_message_type(_message_type):
            def decorator(func):
                return func

            return decorator

        @staticmethod
        def command(_name):
            def decorator(func):
                return func

            return decorator

    class AstrMessageEvent:
        pass

    class At:
        pass

    class Context:
        def __init__(self) -> None:
            self._config = {"admins_id": []}

        def get_config(self):
            return self._config

        def get_registered_star(self, _name):
            return types.SimpleNamespace(repo="")

    class Star:
        def __init__(self, context, config=None) -> None:
            self.context = context
            self.config = config or {}

    class StarTools:
        data_dir = Path(tempfile.gettempdir()) / "astrbot_plugin_test_data"

        @staticmethod
        def get_data_dir(_plugin_name: str) -> Path:
            StarTools.data_dir.mkdir(parents=True, exist_ok=True)
            return StarTools.data_dir

        @staticmethod
        async def send_message_by_id(**kwargs):
            return kwargs

    def register(name, *args, **kwargs):
        def decorator(cls):
            cls.name = name
            return cls

        return decorator

    api_module.logger = _Logger()
    event_module.AstrMessageEvent = AstrMessageEvent
    event_module.MessageChain = MessageChain
    event_module.MessageEventResult = MessageEventResult
    event_module.filter = _Filter()
    message_components_module.At = At
    star_module.Context = Context
    star_module.Star = Star
    star_module.StarTools = StarTools
    star_module.register = register

    sys.modules["astrbot"] = astrbot_module
    sys.modules["astrbot.api"] = api_module
    sys.modules["astrbot.api.event"] = event_module
    sys.modules["astrbot.api.message_components"] = message_components_module
    sys.modules["astrbot.api.star"] = star_module


_install_astrbot_stubs()

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

main = importlib.import_module("main")


class _FakeBot:
    def __init__(self) -> None:
        self.actions: list[tuple[str, dict]] = []

    async def call_action(self, action: str, **kwargs):
        self.actions.append((action, kwargs))
        if action == "get_group_member_info":
            return {"role": "member"}
        return {"ok": True}


class _FakeEvent:
    def __init__(self, bot: _FakeBot) -> None:
        self.bot = bot
        self.sent_messages: list[object] = []

    async def send(self, chain):
        self.sent_messages.append(chain)


class AntiBotPluginTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        main.StarTools.data_dir = Path(self.temp_dir.name)
        self.context = main.Context()
        self.plugin = main.GroupManagePlugin(self.context, {})

    async def asyncTearDown(self) -> None:
        await self.plugin.terminate()
        self.temp_dir.cleanup()

    async def test_group_increase_only_sends_private_notice(self) -> None:
        bot = _FakeBot()
        event = _FakeEvent(bot)
        sent_private_messages: list[dict] = []
        captcha_path = Path(self.temp_dir.name) / "captcha.png"
        captcha_path.write_bytes(b"captcha")

        async def fake_send_message_by_id(**kwargs):
            sent_private_messages.append(kwargs)
            return {"ok": True}

        self.plugin._schedule_anti_bot_timeout = lambda challenge, current_bot: None
        self.plugin.anti_bot_service.generate_captcha_image = lambda code: captcha_path
        original_send = main.StarTools.send_message_by_id
        main.StarTools.send_message_by_id = fake_send_message_by_id
        try:
            await self.plugin._handle_anti_bot_group_increase(event, "20001", "10001")
        finally:
            main.StarTools.send_message_by_id = original_send

        self.assertEqual(event.sent_messages, [])
        self.assertEqual(len(sent_private_messages), 1)
        self.assertEqual(bot.actions[0][0], "set_group_ban")

    async def test_private_notice_failure_falls_back_to_group_notice(self) -> None:
        bot = _FakeBot()
        event = _FakeEvent(bot)
        captcha_path = Path(self.temp_dir.name) / "captcha.png"
        captcha_path.write_bytes(b"captcha")

        async def fake_send_message_by_id(**kwargs):
            raise RuntimeError("private blocked")

        self.plugin._schedule_anti_bot_timeout = lambda challenge, current_bot: None
        self.plugin.anti_bot_service.generate_captcha_image = lambda code: captcha_path
        original_send = main.StarTools.send_message_by_id
        main.StarTools.send_message_by_id = fake_send_message_by_id
        try:
            await self.plugin._handle_anti_bot_group_increase(event, "20001", "10001")
        finally:
            main.StarTools.send_message_by_id = original_send

        self.assertEqual(len(event.sent_messages), 1)
        self.assertEqual(
            [action for action, _ in bot.actions],
            ["set_group_ban"],
        )
        self.assertIsNotNone(self.plugin.anti_bot_service.get_record("10001", "20001"))

    async def test_invited_member_only_records_invite_tree(self) -> None:
        bot = _FakeBot()
        event = _FakeEvent(bot)
        anti_bot_calls: list[tuple[str, str]] = []
        recorded_invites: list[dict] = []

        async def fake_handle_anti_bot(_event, group_id: str, user_id: str) -> None:
            anti_bot_calls.append((group_id, user_id))

        async def fake_get_group_member_role(_event, _group_id: str, _user_id: str) -> str:
            return "member"

        self.plugin.config["anti_bot_enabled_groups"] = ["20001"]
        self.plugin.config["invite_tree_enabled_groups"] = ["20001"]
        self.plugin._handle_anti_bot_group_increase = fake_handle_anti_bot
        self.plugin._get_group_member_role = fake_get_group_member_role
        self.plugin.invite_tree_service.record_invite = lambda **kwargs: recorded_invites.append(
            kwargs
        )

        await self.plugin._handle_group_notice(
            event,
            {
                "notice_type": "group_increase",
                "sub_type": "invite",
                "group_id": "20001",
                "user_id": "10001",
                "operator_id": "90001",
                "self_id": "77777",
                "time": 123456,
            },
        )

        self.assertEqual(anti_bot_calls, [])
        self.assertEqual(len(recorded_invites), 1)
        self.assertEqual(recorded_invites[0]["group_id"], "20001")
        self.assertEqual(recorded_invites[0]["inviter_id"], "90001")
        self.assertEqual(recorded_invites[0]["invitee_id"], "10001")

    async def test_timeout_kick_removes_pending_record(self) -> None:
        bot = _FakeBot()
        removed_users: list[tuple[str, list[str]]] = []
        self.plugin.invite_tree_service.delete_users = (
            lambda group_id, users: removed_users.append((group_id, users))
        )

        challenge = self.plugin.anti_bot_service.create_challenge(
            user_id="10001",
            group_id="20001",
            mute_duration=1800,
            ttl_seconds=60,
            now=int(time.time()) - 120,
        )

        await self.plugin._kick_user_if_anti_bot_timeout(bot, challenge)

        self.assertIn(
            (
                "set_group_kick",
                {
                    "group_id": 20001,
                    "user_id": 10001,
                    "reject_add_request": False,
                },
            ),
            bot.actions,
        )
        self.assertIsNone(self.plugin.anti_bot_service.get_record("10001", "20001"))
        self.assertEqual(removed_users, [("20001", ["10001"])])


if __name__ == "__main__":
    unittest.main()
