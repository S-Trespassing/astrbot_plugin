from nonebot import on_command, get_driver
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message,MessageSegment
from nonebot_plugin_apscheduler import scheduler
import random
import json
from pathlib import Path
from datetime import datetime
from core.myconfig import load_config,save_config,BASE_DIR
from core.tools import f
from nonebot.permission import SUPERUSER
from nonebot.params import CommandArg
from nonebot.exception import FinishedException

add_banme_group = on_command("添加banme", permission=SUPERUSER, priority=5, block=True)
remove_banme_group = on_command("移除banme", permission=SUPERUSER, priority=5, block=True)
show_banme_groups = on_command("查看banme", permission=SUPERUSER, priority=5, block=True)
banrank = on_command("banrank", priority=5, block=True)

# 数据文件路径
DATA_PATH = BASE_DIR/'my_resources'/ 'banme_data.json'

# /banme 指令
banme = on_command("banme", priority=5, block=True)

def load_data():
    if not Path(DATA_PATH).exists():
        with open(DATA_PATH, 'w', encoding='utf-8') as file:
            json.dump({}, file, ensure_ascii=False, indent=4)
        return {}
    with open(DATA_PATH, 'r', encoding='utf-8') as file:
        return json.load(file)
def save_data(data):
    with open(DATA_PATH, 'w', encoding='utf-8') as file:
        json.dump(data, file, ensure_ascii=False, indent=4)

@banme.handle()
async def _(bot: Bot, event: GroupMessageEvent):
    cfg = load_config()
    banme_groups = cfg.get("banme_groups", [])
    if event.group_id not in banme_groups:
        return  # 不在配置群里，忽略

    user_id = str(event.user_id)
    group_id = str(event.group_id)

    # 随机 1~180 秒
    duration = max(1.0,random.random()*181)

    # 禁言
    try:
        await bot.set_group_ban(group_id=event.group_id, user_id=event.user_id, duration=int(duration))
        msg = Message(
            MessageSegment.at(user_id) +
            MessageSegment.text(f" 玉米投手向你投掷了{f(duration)}块黄油🧈,根据织梦弹性公式计算,实际沉默🌀时间为{int(duration)}秒")
        )
        await bot.send_group_msg(group_id=event.group_id, message=msg)
    except FinishedException:
        pass
    except Exception as e:
        await banme.finish(f"❌ 禁言失败: {e}")
    duration=int(duration)
    # 记录数据
    data = load_data()
    today = datetime.now().strftime("%Y-%m-%d")
    if group_id not in data:
        data[group_id] = {}
    if today not in data[group_id]:
        data[group_id][today] = {}

    # 判断是否产生新纪录
    current_record = data[group_id][today].get("user")
    current_duration = data[group_id][today].get("duration", 0)
    new_record = False

    if not current_record or duration > current_duration:
        data[group_id][today]["user"] = user_id
        data[group_id][today]["duration"] = duration
        new_record = True  # 标记为新纪录

    save_data(data)

    # 如果产生新纪录，发送额外提示
    if new_record:
        try:
            await bot.send_group_msg(
                group_id=event.group_id,
                message=Message(f"🎉 恭喜 {event.sender.card or event.sender.nickname} 创造了今日新纪录({duration}秒)!")
            )
        except Exception:
            pass

    await banme.finish()


@banrank.handle()
async def _(bot: Bot, event: GroupMessageEvent):
    cfg = load_config()
    banme_groups = cfg.get("banme_groups", [])
    if event.group_id not in banme_groups:
        return  # 不在配置群里，忽略

    group_id = str(event.group_id)
    data = load_data()
    today = datetime.now().strftime("%Y-%m-%d")
    record = data.get(group_id, {}).get(today, {})

    if not record:
        await banrank.finish("📊 目前还没有记录哦~")

    user_id = record["user"]
    duration = record["duration"]

    msg = f"📊 今日记录由 {user_id} 创造: {duration} 秒"
    await banrank.finish(Message(msg))


# 每天 00:00 给每个群推送成绩，并清空当天记录
@scheduler.scheduled_job("cron", hour=23, minute=58)
async def send_daily_rank():
    bot = get_driver().bots.get(list(get_driver().bots.keys())[0])
    if not bot:
        return

    cfg = load_config()
    banme_groups = cfg.get("banme_groups", [])

    data = load_data()
    today = datetime.now().strftime("%Y-%m-%d")

    for gid in banme_groups:
        group_id = str(gid)
        record = data.get(group_id, {}).get(today, {})

        if not record:
            continue

        user_id = record["user"]
        duration = record["duration"]
        message = MessageSegment.text(f"🏆 恭喜 {user_id}({duration}秒) 成为今天的禁言王(雾)")+MessageSegment.face(297)+MessageSegment.face(297)+MessageSegment.face(297)

        try:
            await bot.send_group_msg(group_id=gid, message=Message(message))
        except Exception:
            continue
        # 清空当天记录
        if group_id in data and today in data[group_id]:
            del data[group_id][today]
    save_data(data)

@add_banme_group.handle()
async def _(event: GroupMessageEvent, args: Message = CommandArg()):
    gid = args.extract_plain_text().strip()
    if not gid.isdigit():
        await add_banme_group.finish("⚠️ 用法：/添加banme <群号>")

    gid = int(gid)
    cfg = load_config()
    if "banme_groups" not in cfg:
        cfg["banme_groups"] = []

    if gid in cfg["banme_groups"]:
        await add_banme_group.finish(f"✅ 群 {gid} 已经在 banme 群列表中")
    else:
        cfg["banme_groups"].append(gid)
        save_config(cfg)
        await add_banme_group.finish(f"✅ 已添加群 {gid} 到 banme 群列表")

@remove_banme_group.handle()
async def _(event: GroupMessageEvent, args: Message = CommandArg()):
    gid = args.extract_plain_text().strip()
    if not gid.isdigit():
        await remove_banme_group.finish("⚠️ 用法：/移除banme <群号>")

    gid = int(gid)
    cfg = load_config()
    if "banme_groups" not in cfg or gid not in cfg["banme_groups"]:
        await remove_banme_group.finish(f"❌ 群 {gid} 不在 banme 群列表中")
    else:
        cfg["banme_groups"].remove(gid)
        save_config(cfg)
        await remove_banme_group.finish(f"✅ 已从 banme 群列表移除群 {gid}")
# 显示banme群

@show_banme_groups.handle()
async def _():
    cfg = load_config()
    banme_groups = cfg.get("banme_groups", [])

    if not banme_groups:
        await show_banme_groups.finish("📋 当前没有启用 banme 功能的群")
    else:
        group_list = "\n".join([str(gid) for gid in banme_groups])
        await show_banme_groups.finish(f"📋 当前启用 banme 功能的群：\n{group_list}")
