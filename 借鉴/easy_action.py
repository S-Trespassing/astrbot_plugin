from nonebot import on_command
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    Message,
    MessageSegment,
)
from nonebot.params import CommandArg
from nonebot.permission import SUPERUSER
from core.tools import extract_uid
from nonebot.exception import FinishedException

def is_admin_or_owner(event: GroupMessageEvent) -> bool:
    """判断是否为群主/管理员"""
    return event.sender.role in ("owner", "admin")

# /t 踢人
kick_user = on_command("t",aliases={"踢"}, permission=SUPERUSER, priority=5, block=True)


@kick_user.handle()
async def _(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    if not isinstance(event, GroupMessageEvent):
        return

    # 检查权限
    if not (is_admin_or_owner(event) or str(event.user_id) in bot.config.superusers):
        await kick_user.finish("⚠️ 只有群主/管理员/SUPERUSER 可以使用该命令")

    uid = extract_uid(args)
    if not uid:
        await kick_user.finish("⚠️ 请 @ 成员 或 输入 QQ号")

    try:
        await bot.set_group_kick(group_id=event.group_id, user_id=uid)
        await kick_user.finish(
            MessageSegment.text("✅ 已将 ") + MessageSegment.at(uid) + MessageSegment.text(" 踢出群聊")
        )

    except FinishedException:
        pass
    except Exception as e:
        await kick_user.finish(f"❌ 踢出失败：{e}")


# /jie 解禁
unban_user = on_command("jie",aliases={"解","解禁","解除"}, permission=SUPERUSER, priority=5, block=True)


@unban_user.handle()
async def _(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    if not isinstance(event, GroupMessageEvent):
        return

    # 检查权限
    if not (is_admin_or_owner(event) or str(event.user_id) in bot.config.superusers):
        await unban_user.finish("⚠️ 只有群主/管理员/SUPERUSER 可以使用该命令")

    uid = extract_uid(args)
    if not uid:
        await unban_user.finish("⚠️ 请 @ 成员 或 输入 QQ号")

    try:
        await bot.set_group_ban(group_id=event.group_id, user_id=uid, duration=0)
        await unban_user.finish(
            MessageSegment.text("✅ 已解除 ") + MessageSegment.at(uid) + MessageSegment.text(" 的禁言")
        )
    except FinishedException:
        pass
    except Exception as e:
        await unban_user.finish(f"❌ 解禁失败：{e}")
