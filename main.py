from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, MessageEventResult, filter
from astrbot.api.message_components import At
from astrbot.api.star import Context, Star, StarTools, register

try:
    from .services.anti_bot import AntiBotService, ChallengeRecord
    from .services.invite_tree import InviteTreeService
    from .services.monitor import MonitorService, ViolationRecord
    from .services.self_update import SelfUpdateError, SelfUpdateService
    from .services.storage import JsonStorage
except ImportError:
    from services.anti_bot import AntiBotService, ChallengeRecord
    from services.invite_tree import InviteTreeService
    from services.monitor import MonitorService, ViolationRecord
    from services.self_update import SelfUpdateError, SelfUpdateService
    from services.storage import JsonStorage

PLUGIN_NAME = "astrbot_plugin_group_manage"
SUPPORTED_PLATFORM = "aiocqhttp"


def _raw_get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    getter = getattr(obj, "get", None)
    if callable(getter):
        try:
            return getter(key, default)
        except TypeError:
            pass
    return getattr(obj, key, default)


@register(
    PLUGIN_NAME,
    "Codex",
    "群管理插件，支持邀请树、二维码监控与入群防机器人验证",
    "1.2.0",
)
class GroupManagePlugin(Star):
    def __init__(self, context: Context, config: dict | None = None) -> None:
        super().__init__(context, config)
        self.config = config or {}
        plugin_name = getattr(self, "name", PLUGIN_NAME)
        self.plugin_dir = Path(__file__).resolve().parent
        self.data_dir = StarTools.get_data_dir(plugin_name)
        self.temp_dir = self.data_dir / "temp"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.update_lock = asyncio.Lock()
        self._anti_bot_timeout_tasks: dict[tuple[str, str], asyncio.Task[Any]] = {}
        self._anti_bot_runtime_bot: Any | None = None
        self._anti_bot_timeout_restore_finished = False
        self.invite_tree_service = InviteTreeService(
            JsonStorage(self.data_dir, "invite_tree.json")
        )
        self.monitor_service = MonitorService(self.temp_dir)
        self.anti_bot_service = AntiBotService(
            JsonStorage(self.data_dir, "anti_bot.json"),
            self.temp_dir,
        )
        self.self_update_service = SelfUpdateService(
            plugin_dir=self.plugin_dir,
            temp_dir=self.temp_dir,
            storage=JsonStorage(self.data_dir, "self_update.json"),
        )

    async def initialize(self) -> None:
        self.anti_bot_service.cleanup_stale_files(purge_expired=False)
        self.self_update_service.cleanup_stale_files()
        logger.info("群管理插件已初始化，数据目录: %s", self.data_dir)

    async def terminate(self) -> None:
        await self._cancel_all_anti_bot_timeout_tasks()
        self.monitor_service.cleanup_stale_files()
        self.anti_bot_service.cleanup_stale_files(purge_expired=False)
        self.self_update_service.cleanup_stale_files()

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def handle_group_event(self, event: AstrMessageEvent) -> None:
        if event.get_platform_name() != SUPPORTED_PLATFORM:
            return
        self._remember_anti_bot_bot(event)
        await self._restore_anti_bot_timeout_tasks()

        raw_message = getattr(event.message_obj, "raw_message", None)
        post_type = _raw_get(raw_message, "post_type", "")
        if post_type == "notice":
            await self._handle_group_notice(event, raw_message)
            return
        if post_type == "message":
            await self._handle_group_monitor(event, raw_message)

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    async def handle_private_event(self, event: AstrMessageEvent) -> None:
        if event.get_platform_name() != SUPPORTED_PLATFORM:
            return
        self._remember_anti_bot_bot(event)
        await self._restore_anti_bot_timeout_tasks()
        await self._handle_private_verification(event)

    @filter.command("开启邀请树")
    async def enable_invite_tree(
        self, event: AstrMessageEvent, group_id: int
    ):
        """开启指定群的邀请树记录。"""
        allow, target_group, error = await self._ensure_group_config_permission(
            event,
            group_id,
        )
        if not allow:
            yield error
            return

        enabled_groups = self._id_list(self._cfg("invite_tree_enabled_groups", []))
        if target_group in enabled_groups:
            yield self._stop_text("✅ 该群已经开启邀请树。")
            return

        enabled_groups.append(target_group)
        self._save_cfg_value("invite_tree_enabled_groups", enabled_groups)
        yield self._stop_text(f"✅ 已开启群 {target_group} 的邀请树记录。")

    @filter.command("关闭邀请树")
    async def disable_invite_tree(
        self, event: AstrMessageEvent, group_id: int
    ):
        """关闭指定群的邀请树记录。"""
        allow, target_group, error = await self._ensure_group_config_permission(
            event,
            group_id,
        )
        if not allow:
            yield error
            return

        enabled_groups = self._id_list(self._cfg("invite_tree_enabled_groups", []))
        if target_group not in enabled_groups:
            yield self._stop_text("⚠️ 该群尚未开启邀请树。")
            return

        enabled_groups.remove(target_group)
        self._save_cfg_value("invite_tree_enabled_groups", enabled_groups)
        yield self._stop_text(f"✅ 已关闭群 {target_group} 的邀请树记录。")

    @filter.command("查看邀请树配置")
    async def show_invite_tree_config(self, event: AstrMessageEvent):
        """查看当前启用邀请树的群列表。"""
        if not await self._has_management_permission(event):
            yield self._stop_text("⚠️ 只有群主、管理员或 AstrBot 管理员可以使用该命令。")
            return

        enabled_groups = self._id_list(self._cfg("invite_tree_enabled_groups", []))
        if not enabled_groups:
            yield self._stop_text("📋 当前没有开启邀请树的群。")
            return

        content = ["📋 当前开启邀请树的群："]
        content.extend(f"- {group_id}" for group_id in enabled_groups)
        yield self._stop_text("\n".join(content))

    @filter.command("查看邀请树")
    async def show_invite_tree(self, event: AstrMessageEvent):
        """查看某个成员在当前群里的邀请树。"""
        group_id = self._normalized_id(event.get_group_id())
        if not group_id:
            yield self._stop_text("⚠️ 该命令只能在群聊中使用。")
            return
        if not await self._has_management_permission(event):
            yield self._stop_text("⚠️ 只有群主、管理员或 AstrBot 管理员可以使用该命令。")
            return

        target_user_id = self._extract_target_user_id(event, "查看邀请树")
        if not target_user_id:
            yield self._stop_text("⚠️ 用法：/查看邀请树 <@群成员 或 QQ号>")
            return

        if not self.invite_tree_service.has_user(group_id, target_user_id):
            yield self._stop_text("⚠️ 该用户当前没有邀请树记录。")
            return

        children_map = self.invite_tree_service.build_children_map(group_id)
        children = children_map.get(target_user_id, [])
        if not children:
            yield self._stop_text("⚠️ 该用户当前没有下级成员。")
            return

        group = await event.get_group(group_id)
        root_name = self._member_label(group, target_user_id)
        lines = [f"✅ {root_name} 的邀请树："]
        lines.extend(self._render_tree_lines(children_map, target_user_id, group))
        yield self._stop_text("\n".join(lines))

    @filter.command("踢出邀请树")
    async def kick_invite_tree(self, event: AstrMessageEvent):
        """踢出某个成员及其整棵邀请子树。"""
        group_id = self._normalized_id(event.get_group_id())
        if not group_id:
            yield self._stop_text("⚠️ 该命令只能在群聊中使用。")
            return
        if not await self._has_management_permission(event):
            yield self._stop_text("⚠️ 只有群主、管理员或 AstrBot 管理员可以使用该命令。")
            return

        target_user_id = self._extract_target_user_id(event, "踢出邀请树")
        if not target_user_id:
            yield self._stop_text("⚠️ 用法：/踢出邀请树 <@群成员 或 QQ号>")
            return

        if not self.invite_tree_service.has_user(group_id, target_user_id):
            yield self._stop_text("⚠️ 没有找到该用户的邀请树记录。")
            return

        bot = getattr(event, "bot", None)
        if bot is None:
            yield self._stop_text("❌ 当前平台不支持该操作。")
            return

        group = await event.get_group(group_id)
        users_to_kick = self.invite_tree_service.get_subtree_user_ids(
            group_id,
            target_user_id,
            include_root=True,
            postorder=True,
        )

        removed_users: list[str] = []
        failed_users: list[str] = []
        for user_id in users_to_kick:
            try:
                await bot.call_action(
                    "set_group_kick",
                    group_id=int(group_id),
                    user_id=int(user_id),
                    reject_add_request=False,
                )
                removed_users.append(user_id)
                await asyncio.sleep(0.2)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "踢出邀请树成员失败 group=%s user=%s error=%s",
                    group_id,
                    user_id,
                    exc,
                )
                failed_users.append(user_id)

        if removed_users:
            self.invite_tree_service.delete_users(group_id, removed_users)

        if not removed_users:
            yield self._stop_text("❌ 没有成员被成功踢出，请检查机器人权限。")
            return

        removed_labels = "、".join(
            self._member_label(group, user_id) for user_id in removed_users
        )
        summary = [f"✅ 已踢出 {len(removed_users)} 人：{removed_labels}"]
        if failed_users:
            failed_labels = "、".join(
                self._member_label(group, user_id) for user_id in failed_users
            )
            summary.append(f"⚠️ 以下成员踢出失败：{failed_labels}")
        yield self._stop_text("\n".join(summary))

    @filter.command("开启防机器人")
    async def enable_anti_bot(self, event: AstrMessageEvent, group_id: int):
        """开启指定群的入群验证码防机器人。"""
        allow, target_group, error = await self._ensure_group_config_permission(
            event,
            group_id,
        )
        if not allow:
            yield error
            return

        enabled_groups = self._id_list(self._cfg("anti_bot_enabled_groups", []))
        if target_group in enabled_groups:
            yield self._stop_text("✅ 该群已经开启防机器人验证。")
            return

        enabled_groups.append(target_group)
        self._save_cfg_value("anti_bot_enabled_groups", enabled_groups)
        yield self._stop_text(f"✅ 已开启群 {target_group} 的入群验证码验证。")

    @filter.command("关闭防机器人")
    async def disable_anti_bot(self, event: AstrMessageEvent, group_id: int):
        """关闭指定群的入群验证码防机器人。"""
        allow, target_group, error = await self._ensure_group_config_permission(
            event,
            group_id,
        )
        if not allow:
            yield error
            return

        enabled_groups = self._id_list(self._cfg("anti_bot_enabled_groups", []))
        if target_group not in enabled_groups:
            yield self._stop_text("⚠️ 该群尚未开启防机器人验证。")
            return

        enabled_groups.remove(target_group)
        self._save_cfg_value("anti_bot_enabled_groups", enabled_groups)
        yield self._stop_text(f"✅ 已关闭群 {target_group} 的入群验证码验证。")

    @filter.command("查看防机器人配置")
    async def show_anti_bot_config(self, event: AstrMessageEvent):
        """查看当前防机器人验证配置。"""
        if not await self._has_management_permission(event):
            yield self._stop_text("⚠️ 只有群主、管理员或 AstrBot 管理员可以使用该命令。")
            return

        enabled_groups = self._id_list(self._cfg("anti_bot_enabled_groups", []))
        if not enabled_groups:
            yield self._stop_text("📋 当前没有开启防机器人验证的群。")
            return

        mute_duration = self._cfg_int("anti_bot_mute_duration_seconds", 1800)
        verify_timeout = self._cfg_int(
            "anti_bot_verify_timeout_seconds",
            300,
        )
        content = [
            "📋 当前开启防机器人验证的群：",
            *[f"- {group_id}" for group_id in enabled_groups],
            f"⏱ 禁言时长：{mute_duration} 秒",
            f"⌛ 验证有效期：{verify_timeout} 秒（超时自动静默踢出）",
        ]
        yield self._stop_text("\n".join(content))

    @filter.command("添加群监控")
    async def add_monitor_group(
        self, event: AstrMessageEvent, source_group_id: int, alert_group_id: int
    ):
        """为指定群开启二维码监控，并设置告警群。"""
        allow, target_group, error = await self._ensure_group_config_permission(
            event,
            source_group_id,
        )
        if not allow:
            yield error
            return

        monitor_groups = self.monitor_service.normalize_monitor_groups(
            self._cfg("monitor_groups", [])
        )
        monitor_groups[target_group] = self._normalized_id(alert_group_id)
        self._save_cfg_value(
            "monitor_groups",
            self.monitor_service.monitor_map_to_config(monitor_groups),
        )
        yield self._stop_text(
            f"✅ 已开启群 {target_group} 的监控，告警将转发到群 {alert_group_id}。"
        )

    @filter.command("移除群监控")
    async def remove_monitor_group(
        self, event: AstrMessageEvent, group_id: int
    ):
        """关闭指定群的二维码监控。"""
        allow, target_group, error = await self._ensure_group_config_permission(
            event,
            group_id,
        )
        if not allow:
            yield error
            return

        monitor_groups = self.monitor_service.normalize_monitor_groups(
            self._cfg("monitor_groups", [])
        )
        if target_group not in monitor_groups:
            yield self._stop_text("⚠️ 该群尚未开启监控。")
            return

        monitor_groups.pop(target_group, None)
        self._save_cfg_value(
            "monitor_groups",
            self.monitor_service.monitor_map_to_config(monitor_groups),
        )
        yield self._stop_text(f"✅ 已关闭群 {target_group} 的二维码监控。")

    @filter.command("查看群监控")
    async def show_monitor_groups(self, event: AstrMessageEvent):
        """查看当前开启二维码监控的群配置。"""
        if not await self._has_management_permission(event):
            yield self._stop_text("⚠️ 只有群主、管理员或 AstrBot 管理员可以使用该命令。")
            return

        monitor_groups = self.monitor_service.normalize_monitor_groups(
            self._cfg("monitor_groups", [])
        )
        if not monitor_groups:
            yield self._stop_text("📋 当前没有开启群监控。")
            return

        content = ["📋 当前开启群监控的群："]
        content.extend(
            f"- 源群 {group_id} -> 告警群 {alert_group_id}"
            for group_id, alert_group_id in monitor_groups.items()
        )
        yield self._stop_text("\n".join(content))

    @filter.command("添加白名单")
    async def add_whitelist_user(self, event: AstrMessageEvent):
        """将某个用户加入白名单。"""
        if not await self._has_management_permission(event):
            yield self._stop_text("⚠️ 只有群主、管理员或 AstrBot 管理员可以使用该命令。")
            return

        target_user_id = self._extract_target_user_id(event, "添加白名单")
        if not target_user_id:
            yield self._stop_text("⚠️ 用法：/添加白名单 <@群成员 或 QQ号>")
            return

        whitelist = self._id_list(self._cfg("whitelist_users", []))
        if target_user_id in whitelist:
            yield self._stop_text(f"✅ 用户 {target_user_id} 已经在白名单中。")
            return

        whitelist.append(target_user_id)
        self._save_cfg_value("whitelist_users", whitelist)
        yield self._stop_text(f"✅ 已将用户 {target_user_id} 添加到白名单。")

    @filter.command("移除白名单")
    async def remove_whitelist_user(self, event: AstrMessageEvent):
        """将某个用户移出白名单。"""
        if not await self._has_management_permission(event):
            yield self._stop_text("⚠️ 只有群主、管理员或 AstrBot 管理员可以使用该命令。")
            return

        target_user_id = self._extract_target_user_id(event, "移除白名单")
        if not target_user_id:
            yield self._stop_text("⚠️ 用法：/移除白名单 <@群成员 或 QQ号>")
            return

        whitelist = self._id_list(self._cfg("whitelist_users", []))
        if target_user_id not in whitelist:
            yield self._stop_text(f"⚠️ 用户 {target_user_id} 当前不在白名单中。")
            return

        whitelist.remove(target_user_id)
        self._save_cfg_value("whitelist_users", whitelist)
        yield self._stop_text(f"✅ 已将用户 {target_user_id} 从白名单移除。")

    @filter.command("查看白名单")
    async def show_whitelist(self, event: AstrMessageEvent):
        """查看当前白名单成员。"""
        if not await self._has_management_permission(event):
            yield self._stop_text("⚠️ 只有群主、管理员或 AstrBot 管理员可以使用该命令。")
            return

        whitelist = self._id_list(self._cfg("whitelist_users", []))
        if not whitelist:
            yield self._stop_text("📋 当前白名单为空。")
            return

        content = ["📋 当前白名单成员："]
        content.extend(f"- {user_id}" for user_id in whitelist)
        yield self._stop_text("\n".join(content))

    @filter.command("设置更新仓库")
    async def set_update_repo(self, event: AstrMessageEvent):
        """设置插件自更新使用的 GitHub 仓库地址和分支。"""
        error = self._ensure_superuser_result(event)
        if error is not None:
            yield error
            return

        payload = self._extract_command_payload(event, "设置更新仓库")
        if not payload:
            yield self._stop_text(
                "⚠️ 用法：/设置更新仓库 <GitHub仓库地址> [分支]\n"
                "示例：/设置更新仓库 https://github.com/yourname/astrbot_plugin_group_manage main"
            )
            return

        parts = payload.split()
        repo_url = self.self_update_service.normalize_repo_url(parts[0])
        if not repo_url:
            yield self._stop_text("⚠️ 仅支持 GitHub 仓库地址，请填写 https://github.com/用户名/仓库名。")
            return

        branch = (parts[1].strip() if len(parts) > 1 else "") or "main"
        self._save_cfg_value("update_repo_url", repo_url)
        self._save_cfg_value("update_branch", branch)
        yield self._stop_text(
            "✅ 已保存插件更新配置。\n"
            f"🔗 仓库：{repo_url}\n"
            f"🌿 分支：{branch}"
        )

    @filter.command("查看更新配置")
    async def show_update_config(self, event: AstrMessageEvent):
        """查看插件自更新配置。"""
        error = self._ensure_superuser_result(event)
        if error is not None:
            yield error
            return

        repo_url = self._resolve_update_repo_url()
        branch = self._resolve_update_branch()
        install_mode = "Git 仓库" if self.self_update_service.is_git_repo() else "GitHub 压缩包"
        content = [
            "📋 当前插件更新配置：",
            f"🔧 更新方式：{install_mode}",
            f"🔗 仓库：{repo_url or '未配置'}",
            f"🌿 分支：{branch}",
        ]
        if not repo_url:
            content.append("⚠️ 还没有配置更新仓库，请先执行 /设置更新仓库。")
        yield self._stop_text("\n".join(content))

    @filter.command("更新群管理插件")
    async def update_plugin_from_github(self, event: AstrMessageEvent):
        """从 GitHub 拉取最新插件代码并自动重载。"""
        error = self._ensure_superuser_result(event)
        if error is not None:
            yield error
            return

        repo_url = self._resolve_update_repo_url()
        if not repo_url:
            yield self._stop_text(
                "⚠️ 还没有配置更新仓库，请先执行 /设置更新仓库 <GitHub仓库地址> [分支]。"
            )
            return

        if self.update_lock.locked():
            yield self._stop_text("⚠️ 当前已经有一次插件更新正在执行，请稍后再试。")
            return

        branch = self._resolve_update_branch()
        github_token = self._cfg_str("update_github_token", "")
        await self._send_text_message(event, "🔄 正在从 GitHub 拉取群管理插件更新，请稍候...")

        async with self.update_lock:
            try:
                result = await self.self_update_service.update_from_github(
                    repo_url=repo_url,
                    branch=branch,
                    github_token=github_token,
                )
            except SelfUpdateError as exc:
                yield self._stop_text(f"❌ 插件更新失败：{exc}")
                return
            except Exception as exc:  # noqa: BLE001
                logger.exception("插件自动更新失败")
                yield self._stop_text(f"❌ 插件更新失败：{exc}")
                return

        if not result.changed:
            yield self._stop_text(
                "✅ 当前已经是最新版本，无需更新。\n"
                f"🔗 仓库：{result.repo_url}\n"
                f"🌿 分支：{result.branch}\n"
                f"🧾 提交：{(result.commit or '未知')[:7]}"
            )
            return

        star_manager = getattr(self.context, "_star_manager", None)
        auto_reload_enabled = star_manager is not None
        summary_lines = [
            "✅ 已拉取到群管理插件最新版本。",
            f"🔗 仓库：{result.repo_url}",
            f"🌿 分支：{result.branch}",
            f"🧾 提交：{(result.commit or '未知')[:7]}",
        ]
        if result.mode == "archive":
            summary_lines.append(
                f"📦 覆盖文件：{result.copied_files}，清理旧文件：{result.removed_files}"
            )
        if auto_reload_enabled:
            summary_lines.append("♻️ 即将自动重载插件，通常几秒内生效。")
            summary_lines.append("如果没有自动生效，请到 AstrBot 插件管理页手动重载一次。")
        else:
            summary_lines.append("⚠️ 当前环境未暴露自动重载接口，请到 AstrBot 插件管理页手动重载。")

        await self._send_text_message(event, "\n".join(summary_lines))
        if auto_reload_enabled:
            asyncio.create_task(self._reload_self_after_delay())
        yield MessageEventResult().stop_event()

    async def _handle_group_notice(
        self,
        event: AstrMessageEvent,
        raw_message: Any,
    ) -> None:
        notice_type = _raw_get(raw_message, "notice_type", "")
        if notice_type != "group_increase":
            return

        group_id = self._normalized_id(_raw_get(raw_message, "group_id"))
        user_id = self._normalized_id(_raw_get(raw_message, "user_id"))
        if not group_id or not user_id:
            return
        if user_id == self._normalized_id(_raw_get(raw_message, "self_id")):
            return

        sub_type = _raw_get(raw_message, "sub_type", "")
        # 邀请入群需要记录邀请树，不应被防机器人流程拦截。
        if (
            sub_type != "invite"
            and group_id in self._id_list(self._cfg("anti_bot_enabled_groups", []))
        ):
            await self._handle_anti_bot_group_increase(event, group_id, user_id)

        if group_id not in self._id_list(self._cfg("invite_tree_enabled_groups", [])):
            return

        operator_id = self._normalized_id(_raw_get(raw_message, "operator_id"))
        inviter_id = operator_id if sub_type == "invite" and operator_id != user_id else None
        inviter_role = ""
        if inviter_id:
            inviter_role = await self._get_group_member_role(event, group_id, inviter_id)

        self.invite_tree_service.record_invite(
            group_id=group_id,
            inviter_id=inviter_id,
            invitee_id=user_id,
            inviter_role=inviter_role,
            whitelist=set(self._id_list(self._cfg("whitelist_users", []))),
            skip_admins=bool(self._cfg("skip_admins", True)),
            joined_at=self._safe_int(_raw_get(raw_message, "time")) or int(time.time()),
        )

    async def _handle_anti_bot_group_increase(
        self,
        event: AstrMessageEvent,
        group_id: str,
        user_id: str,
    ) -> None:
        if user_id in set(self._id_list(self._cfg("whitelist_users", []))):
            return

        bot = getattr(event, "bot", None)
        if bot is None:
            logger.warning("防机器人验证启动失败：当前事件没有 bot 实例。")
            return

        mute_duration = self._cfg_int("anti_bot_mute_duration_seconds", 1800)
        verify_timeout = self._cfg_int(
            "anti_bot_verify_timeout_seconds",
            300,
        )

        try:
            await bot.call_action(
                "set_group_ban",
                group_id=int(group_id),
                user_id=int(user_id),
                duration=mute_duration,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "启动防机器人禁言失败 group=%s user=%s error=%s",
                group_id,
                user_id,
                exc,
            )
            return

        challenge = self.anti_bot_service.create_challenge(
            user_id=user_id,
            group_id=group_id,
            mute_duration=mute_duration,
            ttl_seconds=verify_timeout,
        )
        self._schedule_anti_bot_timeout(challenge, bot)

        captcha_path = None
        private_notice_sent = False
        group_notice_sent = False
        try:
            captcha_path = self.anti_bot_service.generate_captcha_image(challenge.code)
            private_notice_sent = await self._send_anti_bot_private_notice(
                user_id,
                captcha_path,
                verify_timeout,
            )
            if not private_notice_sent:
                group_notice_sent = await self._send_anti_bot_group_notice(
                    event,
                    group_id,
                    user_id,
                    captcha_path,
                    verify_timeout,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "发送入群验证码失败 group=%s user=%s error=%s",
                group_id,
                user_id,
                exc,
            )
        finally:
            self.anti_bot_service.cleanup_file(captcha_path)

        if private_notice_sent:
            return

        if not group_notice_sent:
            logger.warning(
                "私聊验证码发送失败，且群内兜底通知也发送失败 group=%s user=%s",
                group_id,
                user_id,
            )

    async def _send_anti_bot_group_notice(
        self,
        event: AstrMessageEvent,
        group_id: str,
        user_id: str,
        captcha_path: Any,
        verify_timeout: int,
    ) -> bool:
        minutes = max(1, verify_timeout // 60)
        chain = MessageChain()
        chain.at(user_id, user_id).message(
            " 私聊验证码发送失败，请点击机器人头像主动发起私聊。"
            "然后只发送下方图片中的 6 位数字验证码。"
            f"验证码约 {minutes} 分钟内有效。"
        )
        chain.file_image(str(captcha_path))
        try:
            await event.send(chain)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "群内发送验证码兜底通知失败 group=%s user=%s error=%s",
                group_id,
                user_id,
                exc,
            )
            return False

    async def _send_anti_bot_private_notice(
        self,
        user_id: str,
        captcha_path: Any,
        verify_timeout: int,
    ) -> bool:
        minutes = max(1, verify_timeout // 60)
        chain = MessageChain().message(
            "你刚刚触发了入群验证。请直接发送图片中的 6 位数字验证码。"
            "只发送数字，不要发送任何其他文字。"
            f"验证码约 {minutes} 分钟内有效。"
        )
        chain.file_image(str(captcha_path))
        try:
            await StarTools.send_message_by_id(
                type="PrivateMessage",
                id=user_id,
                message_chain=chain,
                platform=SUPPORTED_PLATFORM,
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.debug("私聊发送验证码提示失败 user=%s error=%s", user_id, exc)
            return False

    async def _handle_private_verification(self, event: AstrMessageEvent) -> None:
        sender_id = self._normalized_id(event.get_sender_id())
        if not sender_id:
            return

        pending_records = self.anti_bot_service.get_pending_records(sender_id)
        if not pending_records:
            return

        content = (event.get_message_str() or "").strip()
        event.should_call_llm(False)

        if not content.isdigit():
            await event.send(
                MessageChain().message(
                    "请只发送图片里的 6 位数字验证码，不要发送其他文字。"
                )
            )
            event.stop_event()
            return

        if len(content) != 6:
            await event.send(
                MessageChain().message("验证码应为 6 位数字，请重新发送。")
            )
            event.stop_event()
            return

        matched = self.anti_bot_service.match_code(sender_id, content)
        if matched is None:
            await event.send(
                MessageChain().message(
                    "验证码不正确或已过期，请检查后重新发送，且只发送数字。"
                )
            )
            event.stop_event()
            return

        bot = getattr(event, "bot", None)
        if bot is None:
            await event.send(
                MessageChain().message("当前无法完成自动解禁，请联系管理员处理。")
            )
            event.stop_event()
            return

        self._cancel_anti_bot_timeout_task(sender_id, matched.group_id)
        self.anti_bot_service.confirm_challenge(sender_id, matched.group_id)
        try:
            await self._unmute_user(bot, matched.group_id, matched.user_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "验证码匹配后解禁失败 group=%s user=%s error=%s",
                matched.group_id,
                matched.user_id,
                exc,
            )
            await event.send(
                MessageChain().message(
                    "验证码正确，但自动解除禁言失败，请联系管理员处理。"
                )
            )
            event.stop_event()
            return

        await event.send(
            MessageChain().message(
                f"验证通过，已自动解除你在群 {matched.group_id} 的禁言。"
            )
        )
        event.stop_event()

    async def _handle_group_monitor(
        self,
        event: AstrMessageEvent,
        raw_message: Any,
    ) -> None:
        group_id = self._normalized_id(event.get_group_id())
        sender_id = self._normalized_id(event.get_sender_id())
        if not group_id or not sender_id:
            return

        monitor_groups = self.monitor_service.normalize_monitor_groups(
            self._cfg("monitor_groups", [])
        )
        alert_group_id = monitor_groups.get(group_id)
        if not alert_group_id:
            return

        whitelist = set(self._id_list(self._cfg("whitelist_users", [])))
        if sender_id in whitelist:
            return

        if bool(self._cfg("skip_admins", True)) and await self._is_group_admin_or_owner(event):
            return

        violation = await self.monitor_service.inspect_raw_message(
            raw_message=raw_message,
            group_id=group_id,
            user_id=sender_id,
        )
        if not violation:
            return

        try:
            await self._handle_violation(event, raw_message, alert_group_id, violation)
        finally:
            self.monitor_service.cleanup_violation(violation)

    async def _handle_violation(
        self,
        event: AstrMessageEvent,
        raw_message: Any,
        alert_group_id: str,
        violation: ViolationRecord,
    ) -> None:
        bot = getattr(event, "bot", None)
        group_id = self._normalized_id(event.get_group_id()) or "未知群"
        sender_id = self._normalized_id(event.get_sender_id()) or "未知用户"
        sender_name = event.get_sender_name() or sender_id

        if bool(self._cfg("delete_violation_message", True)) and bot is not None:
            message_id = _raw_get(raw_message, "message_id")
            if message_id is not None:
                try:
                    await bot.call_action("delete_msg", message_id=int(message_id))
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "撤回违规消息失败 group=%s sender=%s message_id=%s error=%s",
                        group_id,
                        sender_id,
                        message_id,
                        exc,
                    )

        if bool(self._cfg("notify_group", True)):
            chain = MessageChain()
            chain.at(sender_name, sender_id).message(
                " 请不要发送 QQ/微信群二维码或邀请卡片，消息已处理。"
            )
            await event.send(chain)

        if bool(self._cfg("forward_alert", True)) and alert_group_id:
            summary = [
                "⚠️ 群监控告警",
                f"来源群：{group_id}",
                f"发送者：{sender_name}({sender_id})",
                f"命中类型：{violation.summary}",
            ]
            if violation.detail:
                summary.append(f"二维码内容：{violation.detail}")

            chain = MessageChain().message("\n".join(summary))
            if violation.image_path:
                chain.file_image(str(violation.image_path))

            try:
                await StarTools.send_message_by_id(
                    type="GroupMessage",
                    id=alert_group_id,
                    message_chain=chain,
                    platform=SUPPORTED_PLATFORM,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "转发违规告警失败 src_group=%s alert_group=%s error=%s",
                    group_id,
                    alert_group_id,
                    exc,
                )

        event.should_call_llm(False)
        event.stop_event()

    async def _ensure_group_config_permission(
        self,
        event: AstrMessageEvent,
        target_group_id: int | str,
    ) -> tuple[bool, str, MessageEventResult | None]:
        normalized_target = self._normalized_id(target_group_id)
        if not normalized_target:
            return False, "", self._stop_text("⚠️ 群号格式不正确。")

        if self._is_superuser(event):
            return True, normalized_target, None

        current_group_id = self._normalized_id(event.get_group_id())
        if not current_group_id:
            return (
                False,
                normalized_target,
                self._stop_text("⚠️ 只有 AstrBot 管理员可以在私聊里配置群管理功能。"),
            )
        if current_group_id != normalized_target:
            return (
                False,
                normalized_target,
                self._stop_text("⚠️ 只有 AstrBot 管理员可以跨群修改配置。"),
            )
        if not await self._is_group_admin_or_owner(event):
            return (
                False,
                normalized_target,
                self._stop_text("⚠️ 只有群主、管理员或 AstrBot 管理员可以使用该命令。"),
            )
        return True, normalized_target, None

    async def _has_management_permission(self, event: AstrMessageEvent) -> bool:
        if self._is_superuser(event):
            return True
        if not event.get_group_id():
            return False
        return await self._is_group_admin_or_owner(event)

    async def _is_group_admin_or_owner(self, event: AstrMessageEvent) -> bool:
        role = self._sender_role(event)
        if role in {"owner", "admin"}:
            return True

        group = await event.get_group(event.get_group_id())
        if not group:
            return False

        sender_id = self._normalized_id(event.get_sender_id())
        if not sender_id:
            return False

        owner_id = self._normalized_id(getattr(group, "group_owner", ""))
        if sender_id == owner_id:
            return True

        admin_ids = {self._normalized_id(admin_id) for admin_id in getattr(group, "group_admins", [])}
        return sender_id in admin_ids

    async def _get_group_member_role(
        self,
        event: AstrMessageEvent,
        group_id: str,
        user_id: str,
    ) -> str:
        if (
            self._normalized_id(event.get_group_id()) == group_id
            and self._normalized_id(event.get_sender_id()) == user_id
        ):
            return self._sender_role(event)

        bot = getattr(event, "bot", None)
        if bot is None:
            return ""

        try:
            info = await bot.call_action(
                "get_group_member_info",
                group_id=int(group_id),
                user_id=int(user_id),
                no_cache=False,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "获取群成员角色失败 group=%s user=%s error=%s",
                group_id,
                user_id,
                exc,
            )
            return ""
        return str(_raw_get(info, "role", "") or "")

    def _remember_anti_bot_bot(self, event: AstrMessageEvent) -> None:
        bot = getattr(event, "bot", None)
        if bot is not None:
            self._anti_bot_runtime_bot = bot

    async def _restore_anti_bot_timeout_tasks(self) -> None:
        if self._anti_bot_timeout_restore_finished:
            return

        bot = self._anti_bot_runtime_bot
        if bot is None:
            return

        for challenge in self.anti_bot_service.list_records():
            self._schedule_anti_bot_timeout(challenge, bot)
        self._anti_bot_timeout_restore_finished = True

    def _schedule_anti_bot_timeout(
        self,
        challenge: ChallengeRecord,
        bot: Any,
    ) -> None:
        task_key = self._anti_bot_task_key(challenge.user_id, challenge.group_id)
        existing_task = self._anti_bot_timeout_tasks.get(task_key)
        if existing_task is not None:
            existing_task.cancel()

        task = asyncio.create_task(
            self._kick_user_if_anti_bot_timeout(bot, challenge)
        )
        self._anti_bot_timeout_tasks[task_key] = task
        task.add_done_callback(
            lambda done_task, current_key=task_key: self._finalize_anti_bot_timeout_task(
                current_key,
                done_task,
            )
        )

    def _cancel_anti_bot_timeout_task(self, user_id: str, group_id: str) -> None:
        task = self._anti_bot_timeout_tasks.pop(
            self._anti_bot_task_key(user_id, group_id),
            None,
        )
        if task is not None:
            task.cancel()

    async def _cancel_all_anti_bot_timeout_tasks(self) -> None:
        tasks = list(self._anti_bot_timeout_tasks.values())
        self._anti_bot_timeout_tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _finalize_anti_bot_timeout_task(
        self,
        task_key: tuple[str, str],
        task: asyncio.Task[Any],
    ) -> None:
        if self._anti_bot_timeout_tasks.get(task_key) is task:
            self._anti_bot_timeout_tasks.pop(task_key, None)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("防机器人超时任务执行异常: %s", exc)

    async def _kick_user_if_anti_bot_timeout(
        self,
        bot: Any,
        challenge: ChallengeRecord,
    ) -> None:
        delay_seconds = max(0, challenge.expires_at - int(time.time()))
        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)

        current = self.anti_bot_service.get_record(
            challenge.user_id,
            challenge.group_id,
        )
        if current is None:
            return

        kicked = await self._kick_user_silently(
            bot,
            current.group_id,
            current.user_id,
            reason="入群验证码超时自动踢出",
        )
        if not kicked:
            return

        self.anti_bot_service.remove_challenge(current.user_id, current.group_id)
        self.invite_tree_service.delete_users(current.group_id, [current.user_id])

    async def _kick_user_silently(
        self,
        bot: Any,
        group_id: str,
        user_id: str,
        reason: str,
    ) -> bool:
        try:
            await bot.call_action(
                "set_group_kick",
                group_id=int(group_id),
                user_id=int(user_id),
                reject_add_request=False,
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "%s失败 group=%s user=%s error=%s",
                reason,
                group_id,
                user_id,
                exc,
            )
            return False

    def _anti_bot_task_key(self, user_id: str, group_id: str) -> tuple[str, str]:
        return (user_id, group_id)

    async def _unmute_user(self, bot: Any, group_id: str, user_id: str) -> None:
        await bot.call_action(
            "set_group_ban",
            group_id=int(group_id),
            user_id=int(user_id),
            duration=0,
        )

    def _sender_role(self, event: AstrMessageEvent) -> str:
        raw_message = getattr(event.message_obj, "raw_message", None)
        sender = _raw_get(raw_message, "sender", {})
        return str(_raw_get(sender, "role", "") or "")

    def _is_superuser(self, event: AstrMessageEvent) -> bool:
        sender_id = self._normalized_id(event.get_sender_id())
        admin_ids = {
            self._normalized_id(admin_id)
            for admin_id in self.context.get_config().get("admins_id", [])
        }
        return sender_id in admin_ids

    def _cfg(self, key: str, default: Any) -> Any:
        value = self.config.get(key, default)
        return default if value is None else value

    def _cfg_int(self, key: str, default: int) -> int:
        try:
            value = int(self._cfg(key, default))
            return max(1, value)
        except (TypeError, ValueError):
            return default

    def _cfg_str(self, key: str, default: str = "") -> str:
        value = self._cfg(key, default)
        if value is None:
            return default
        return str(value).strip()

    def _save_cfg_value(self, key: str, value: Any) -> None:
        self.config[key] = value
        save_config = getattr(self.config, "save_config", None)
        if callable(save_config):
            save_config()

    def _ensure_superuser_result(
        self,
        event: AstrMessageEvent,
    ) -> MessageEventResult | None:
        if self._is_superuser(event):
            return None
        return self._stop_text("⚠️ 只有 AstrBot 管理员可以执行插件更新操作。")

    def _extract_command_payload(
        self,
        event: AstrMessageEvent,
        command_name: str,
    ) -> str:
        payload = (event.get_message_str() or "").strip()
        for prefix in (f"/{command_name}", f"／{command_name}", command_name):
            if payload.startswith(prefix):
                return payload[len(prefix) :].strip()
        return payload

    def _resolve_update_repo_url(self) -> str:
        configured_repo = self.self_update_service.normalize_repo_url(
            self._cfg_str("update_repo_url", "")
        )
        if configured_repo:
            return configured_repo

        plugin_meta = self.context.get_registered_star(getattr(self, "name", PLUGIN_NAME))
        metadata_repo = self.self_update_service.normalize_repo_url(
            str(getattr(plugin_meta, "repo", "") or "")
        )
        if metadata_repo:
            return metadata_repo

        return self.self_update_service.detect_origin_repo()

    def _resolve_update_branch(self) -> str:
        configured_branch = self._cfg_str("update_branch", "")
        if configured_branch:
            return configured_branch
        detected_branch = self.self_update_service.detect_current_branch()
        return detected_branch or "main"

    async def _send_text_message(
        self,
        event: AstrMessageEvent,
        content: str,
    ) -> None:
        chain = MessageChain().message(content)
        try:
            await event.send(chain)
        except Exception as exc:  # noqa: BLE001
            logger.warning("发送插件更新提示失败 error=%s", exc)

    async def _reload_self_after_delay(self, delay_seconds: float = 1.0) -> None:
        await asyncio.sleep(delay_seconds)
        star_manager = getattr(self.context, "_star_manager", None)
        if star_manager is None:
            logger.warning("当前上下文未暴露 StarManager，无法自动重载群管理插件。")
            return
        try:
            success, error_message = await star_manager.reload(
                getattr(self, "name", PLUGIN_NAME)
            )
            if not success:
                logger.error("群管理插件自动重载失败：%s", error_message)
        except Exception as exc:  # noqa: BLE001
            logger.exception("群管理插件自动重载异常: %s", exc)

    def _stop_text(self, text: str) -> MessageEventResult:
        return MessageEventResult().message(text).stop_event()

    def _normalized_id(self, value: Any) -> str:
        if value is None or isinstance(value, bool):
            return ""
        return str(value).strip()

    def _id_list(self, values: Any) -> list[str]:
        result: list[str] = []
        if not isinstance(values, list):
            return result
        for value in values:
            normalized = self._normalized_id(value)
            if normalized and normalized not in result:
                result.append(normalized)
        return result

    def _safe_int(self, value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _extract_target_user_id(self, event: AstrMessageEvent, command_name: str) -> str:
        self_id = self._normalized_id(event.get_self_id())
        for segment in event.get_messages():
            if isinstance(segment, At):
                target = self._normalized_id(getattr(segment, "qq", ""))
                if target and target not in {self_id, "all"}:
                    return target

        payload = (event.get_message_str() or "").strip()
        if payload.startswith(command_name):
            payload = payload[len(command_name) :].strip()

        for token in ("(", "（"):
            if token in payload:
                start = payload.rfind(token)
                end = payload.rfind(")") if token == "(" else payload.rfind("）")
                if end > start:
                    maybe_id = payload[start + 1 : end].strip()
                    if maybe_id.isdigit():
                        return maybe_id

        digits = "".join(ch if ch.isdigit() else " " for ch in payload).split()
        for item in digits:
            if len(item) >= 5:
                return item
        return ""

    def _member_label(self, group: Any, user_id: str) -> str:
        if group:
            for member in getattr(group, "members", []) or []:
                if self._normalized_id(getattr(member, "user_id", "")) == user_id:
                    nickname = getattr(member, "nickname", "") or user_id
                    return f"{nickname}({user_id})"
        return user_id

    def _render_tree_lines(
        self,
        children_map: dict[str, list[str]],
        root_id: str,
        group: Any,
        prefix: str = "",
    ) -> list[str]:
        lines: list[str] = []
        children = children_map.get(root_id, [])
        for index, child_id in enumerate(children):
            is_last = index == len(children) - 1
            branch = "└─ " if is_last else "├─ "
            lines.append(f"{prefix}{branch}{self._member_label(group, child_id)}")
            child_prefix = prefix + ("   " if is_last else "│  ")
            lines.extend(self._render_tree_lines(children_map, child_id, group, child_prefix))
        return lines
