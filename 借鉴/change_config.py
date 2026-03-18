from nonebot import on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.permission import SUPERUSER
from core.myconfig import load_config, save_config
from nonebot.params import CommandArg
from core.tools import extract_uid
import json
from core.myconfig import SENSITIVE_WORDS_FILE, load_sensitive_words
add_white_list = on_command("添加白名单", permission=SUPERUSER)
remove_white_list = on_command("移除白名单", permission=SUPERUSER)
monitor_on = on_command("添加群监控", permission=SUPERUSER)
monitor_off = on_command("移除群监控", permission=SUPERUSER)
monitor_show = on_command("查看群监控", permission=SUPERUSER)
add_ban_word = on_command("添加违禁词", permission=SUPERUSER, priority=5, block=True)
remove_ban_word = on_command("移除违禁词", permission=SUPERUSER, priority=5, block=True)
add_xiao_jin = on_command("添加群宵禁", permission=SUPERUSER, priority=5, block=True)
remove_xiao_jin = on_command("移除群宵禁", permission=SUPERUSER, priority=5, block=True)
add_group = on_command("添加防撤回", permission=SUPERUSER)
del_group = on_command("移除防撤回", permission=SUPERUSER)
set_forward = on_command("防撤回转发群", permission=SUPERUSER)

@add_white_list.handle()
async def _(event: GroupMessageEvent, args: Message = CommandArg()):
    data = load_config()
    uid = extract_uid(args)
    if not uid:
        await add_white_list.finish("⚠️ 用法：/添加白名单 <qq号 或 @群成员>")

    if "white_list" not in data:
        data["white_list"] = []

    if uid in data["white_list"]:
        await add_white_list.finish(f"✅ qq: {uid} 已在白名单中")
    else:
        data["white_list"].append(uid)
        save_config(data)
        await add_white_list.finish(f"✅ 已将 qq: {uid} 添加到白名单")


@remove_white_list.handle()
async def _(event: GroupMessageEvent, args: Message = CommandArg()):
    data = load_config()
    uid = extract_uid(args)
    if not uid:
        await remove_white_list.finish("⚠️ 用法：/移除白名单 <qq号 或 @群成员>")

    if "white_list" not in data or uid not in data["white_list"]:
        await remove_white_list.finish(f"❌ qq: {uid} 不在白名单中")

    data["white_list"].remove(uid)
    save_config(data)
    await remove_white_list.finish(f"✅ 已将 qq: {uid} 从白名单移除")


from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.params import CommandArg

@monitor_on.handle()
async def _(event: GroupMessageEvent, args: Message = CommandArg()):
    data = load_config()
    cmd = args.extract_plain_text().strip().split()
    if len(cmd) != 2 or not all(x.isdigit() for x in cmd):
        await monitor_on.finish("⚠️ 用法：/添加群监控 <被监控群号> <转发目标群号>")
    gid, target_gid = map(int, cmd)

    if "monitor_groups" not in data:
        data["monitor_groups"] = {}

    if str(gid) in data["monitor_groups"]:
        await monitor_on.finish(f"✅ 群 {gid} 已经开启群监控 (转发到 {data['monitor_groups'][str(gid)]})")
    else:
        data["monitor_groups"][str(gid)] = target_gid
        save_config(data)
        await monitor_on.finish(f"✅ 已添加群 {gid} 的监控，违规消息将转发到群 {target_gid}")


@monitor_off.handle()
async def _(event: GroupMessageEvent, args: Message = CommandArg()):
    data = load_config()
    cmd = args.extract_plain_text().strip()
    if not cmd.isdigit():
        await monitor_off.finish("⚠️ 用法：/移除群监控 <群号>")
    gid = int(cmd)

    if "monitor_groups" not in data or str(gid) not in data["monitor_groups"]:
        await monitor_off.finish(f"❌ 群 {gid} 未开启群监控")

    target_gid = data["monitor_groups"].pop(str(gid))
    save_config(data)
    await monitor_off.finish(f"✅ 已关闭群 {gid} 的监控 (原转发目标群 {target_gid})")


@monitor_show.handle()
async def _(event: GroupMessageEvent):
    data = load_config()
    if "monitor_groups" not in data or not data["monitor_groups"]:
        await monitor_show.finish("❌ 当前没有开启群监控的群")

    msg_lines = ["📋 当前开启群监控的群："]
    for gid, target_gid in data["monitor_groups"].items():
        msg_lines.append(f"- 群 {gid} → 转发到群 {target_gid}")

    await monitor_show.finish("\n".join(msg_lines))

@add_ban_word.handle()
async def _(event: GroupMessageEvent, args: Message = CommandArg()):
    data = load_sensitive_words()
    uid = args.extract_plain_text().strip()
    if not uid:
        await add_ban_word.finish("⚠️ 用法：/添加违禁词 <qq号 或 @群成员>")
    if uid in data:
        await add_ban_word.finish(f"✅ 该违禁词已存在：{uid}")
    else:
        data.append(uid)
        with open(SENSITIVE_WORDS_FILE, "w", encoding="utf-8") as f:
            json.dump({"ban_words": data}, f, ensure_ascii=False, indent=4)
        await add_ban_word.finish(f"✅ 成功添加违禁词：{uid}")

@remove_ban_word.handle()
async def _(event: GroupMessageEvent, args: Message = CommandArg()):
    data = load_sensitive_words()
    word = args.extract_plain_text().strip()
    if not word:
        await remove_ban_word.finish("⚠️ 用法：/移除违禁词 <关键词>")
    if word not in data:
        await remove_ban_word.finish(f"❌ 该违禁词不存在：{word}")
    else:
        data.remove(word)
        with open(SENSITIVE_WORDS_FILE, "w", encoding="utf-8") as f:
            json.dump({"ban_words": data}, f, ensure_ascii=False, indent=4)
        await remove_ban_word.finish(f"✅ 成功移除违禁词：{word}")

# 添加宵禁群
@add_xiao_jin.handle()
async def _(event: GroupMessageEvent, args: Message = CommandArg()):
    gid = args.extract_plain_text().strip()
    if not gid.isdigit():
        await add_xiao_jin.finish("⚠️ 用法：/添加群宵禁 <群号>")

    gid = int(gid)
    cfg = load_config()
    if "curfew_groups" not in cfg:
        cfg["curfew_groups"] = []

    if gid in cfg["curfew_groups"]:
        await add_xiao_jin.finish(f"✅ 群 {gid} 已经在宵禁群列表中")
    else:
        cfg["curfew_groups"].append(gid)
        save_config(cfg)
        await add_xiao_jin.finish(f"✅ 已添加群 {gid} 到宵禁群列表")


# 移除宵禁群
@remove_xiao_jin.handle()
async def _(event: GroupMessageEvent, args: Message = CommandArg()):
    gid = args.extract_plain_text().strip()
    if not gid.isdigit():
        await remove_xiao_jin.finish("⚠️ 用法：/移除群宵禁 <群号>")

    gid = int(gid)
    cfg = load_config()
    if "curfew_groups" not in cfg or gid not in cfg["curfew_groups"]:
        await remove_xiao_jin.finish(f"❌ 群 {gid} 不在宵禁群列表中")
    else:
        cfg["curfew_groups"].remove(gid)
        save_config(cfg)
        await remove_xiao_jin.finish(f"✅ 已从宵禁群列表移除群 {gid}")

@add_group.handle()
async def _(event: GroupMessageEvent, args: Message = CommandArg()):
    cmd = args.extract_plain_text().strip()
    if not cmd.isdigit():
        await add_group.finish("用法：/添加防撤回 <群号>")

    gid = int(cmd)
    data = load_config()
    if "groups" not in data:
        data["groups"] = {}
    if str(gid) in data["groups"]:
        await add_group.finish(f"✅ 群 {gid} 已在防撤回列表中")

    data["groups"][str(gid)] = None
    save_config(data)
    await add_group.finish(f"✅ 已添加群 {gid} 到防撤回列表")


@del_group.handle()
async def _(event: GroupMessageEvent, args: Message = CommandArg()):
    cmd = args.extract_plain_text().strip()
    if not cmd.isdigit():
        await del_group.finish("用法：/移除群撤回 <群号>")

    gid = str(cmd)
    data = load_config()
    if "groups" not in data or gid not in data["groups"]:
        await del_group.finish(f"❌ 群 {gid} 不在防撤回列表中")

    data["groups"].pop(gid)
    save_config(data)
    await del_group.finish(f"✅ 已移除群 {gid} 的群撤回")
@set_forward.handle()
async def _(event: GroupMessageEvent, args: Message = CommandArg()):
    cmd = args.extract_plain_text().strip()
    if not cmd.isdigit():
        await set_forward.finish("⚠️ 用法：/防撤转发群 <目标群号>")

    dst = int(cmd)
    data = load_config()
    data["forward_group"] = dst
    save_config(data)
    await set_forward.finish(f"✅ 设置成功：所有撤回消息将统一转发到群 {dst}")

