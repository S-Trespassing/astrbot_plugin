from nonebot import get_driver, on_command
from nonebot.adapters.onebot.v11 import  GroupMessageEvent, Message
from nonebot_plugin_apscheduler import scheduler
from nonebot.permission import SUPERUSER
from nonebot.params import CommandArg
from core.myconfig import load_config, save_config

# 宵禁时间（固定）
CURFEW_START = {"hour": 2, "minute": 0}   # 02:00 开启宵禁
CURFEW_END = {"hour": 6, "minute": 30}    # 06:30 解除宵禁


show_xiao_jin = on_command("查看群宵禁", permission=SUPERUSER, priority=5, block=True)

# 宵禁开始任务
@scheduler.scheduled_job("cron", hour=CURFEW_START["hour"], minute=CURFEW_START["minute"])
async def curfew_start():
    bot = get_driver().bots.get(list(get_driver().bots.keys())[0])
    if not bot:
        return

    cfg = load_config()
    curfew_groups = cfg.get("curfew_groups", [])

    for gid in curfew_groups:
        await bot.set_group_whole_ban(group_id=gid, enable=True)


# 宵禁结束任务
@scheduler.scheduled_job("cron", hour=CURFEW_END["hour"], minute=CURFEW_END["minute"])
async def curfew_end():
    bot = get_driver().bots.get(list(get_driver().bots.keys())[0])
    if not bot:
        return

    cfg = load_config()
    curfew_groups = cfg.get("curfew_groups", [])

    for gid in curfew_groups:
        await bot.set_group_whole_ban(group_id=gid, enable=False)


# 查看宵禁群
@show_xiao_jin.handle()
async def _():
    cfg = load_config()
    curfew_groups = cfg.get("curfew_groups", [])

    if not curfew_groups:
        await show_xiao_jin.finish("📋 当前没有启用宵禁的群")
    else:
        group_list = "\n".join([str(gid) for gid in curfew_groups])
        await show_xiao_jin.finish(f"📋 当前启用宵禁的群：\n{group_list}")
