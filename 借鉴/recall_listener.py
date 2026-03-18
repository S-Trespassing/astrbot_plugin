from nonebot import on_command
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    GroupRecallNoticeEvent,
)
from nonebot.permission import SUPERUSER
from core.myconfig import load_config
from nonebot import on_message, on_notice


list_group = on_command("查看防撤回群", permission=SUPERUSER)
# 消息缓存（message_id → 消息详情）
MESSAGE_CACHE = {}

# === 监听所有群消息并缓存 ===
msg_cache = on_message(priority=10, block=False)

@msg_cache.handle()
async def _(event: GroupMessageEvent):
    """缓存消息内容，用于防撤回"""
    MESSAGE_CACHE[event.message_id] = {
        "group_id": event.group_id,
        "user_id": event.user_id,
        "message": event.message,
    }

    # 控制缓存大小，防止内存占用过高
    if len(MESSAGE_CACHE) > 2000:
        MESSAGE_CACHE.pop(next(iter(MESSAGE_CACHE)))

# === 监听撤回事件 ===
group_recall = on_notice(priority=5, block=False)

@group_recall.handle()
async def _(bot: Bot, event: GroupRecallNoticeEvent):
    """检测到群消息撤回"""
    config = load_config()
    gid = str(event.group_id)

    # 检查是否在监听列表中
    if "groups" not in config or gid not in config["groups"]:
        return

    if event.user_id  in [2669807502,3998534050,3933396434]:
        return
    dst_gid = config.get("forward_group") or config["groups"].get(gid)
    if not dst_gid:
        return

    # 从缓存中取被撤回的消息
    msg_data = MESSAGE_CACHE.get(event.message_id)
    if not msg_data:
        # 撤回太快，缓存中无此消息
        await bot.send_group_msg(group_id=dst_gid, message=f"[防撤回提示] 群({gid}) 有撤回，但内容未缓存。")
        return

    # 群与用户信息
    group_info = await bot.get_group_info(group_id=event.group_id)
    user_info = await bot.get_group_member_info(group_id=event.group_id, user_id=msg_data["user_id"])

    # 提示头
    header = (
        f"⚠️ 消息撤回提醒\n"
        f"来源群：{group_info['group_name']}({gid})\n"
        f"撤回人：{user_info['nickname']}({msg_data['user_id']})\n"
        f"以下是撤回的消息："
    )

    # 构造合并转发节点
    forward_nodes = [
        {
            "type": "node",
            "data": {
                "name": "防撤回Bot",
                "uin": (await bot.get_login_info())["user_id"],
                "content": header,
            },
        },
        {
            "type": "node",
            "data": {
                "name": user_info["nickname"],
                "uin": str(user_info["user_id"]),
                "content": msg_data["message"] if msg_data["message"] else "[消息内容为空]",
            },
        },
    ]

    await bot.send_group_forward_msg(group_id=dst_gid, messages=forward_nodes)


@list_group.handle()
async def _(event: GroupMessageEvent):
    data = load_config()
    if "groups" not in data or not data["groups"]:
        await list_group.finish("❌ 当前没有开启防撤回监听的群")

    msg_lines = ["📋 当前监听的群："]
    for src, dst in data["groups"].items():
        msg_lines.append(f"-  {src} ")

    await list_group.finish("\n".join(msg_lines))
