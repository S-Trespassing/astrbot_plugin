from pathlib import Path
from nonebot import on_notice,on_command
from nonebot.adapters.onebot.v11 import Bot, GroupIncreaseNoticeEvent, MessageSegment,GroupMessageEvent, Message
from core.myconfig import load_config, save_config
from nonebot.params import CommandArg
from nonebot.permission import SUPERUSER
CONFIG_PATH = Path(__file__).parent / "config.json"
welcome = on_notice(priority=5, block=False)
add_welcome = on_command("添加群欢迎",permission=SUPERUSER, priority=5, block=True)
del_welcome = on_command("移除群欢迎",permission=SUPERUSER, priority=5, block=True)
key_word="welcome_groups"
@welcome.handle()
async def _(bot: Bot, event: GroupIncreaseNoticeEvent):
    cfg = load_config()
    welcome_groups = cfg.get(key_word, {})

    group_id = str(event.group_id)  # 注意：JSON 中是字符串
    user_id = event.user_id

    if group_id in welcome_groups:
        content = welcome_groups[group_id]
        msg = Message( MessageSegment.at(user_id)+MessageSegment.text(f" {content}"))
        await bot.send_group_msg(group_id=event.group_id, message=msg)
@add_welcome.handle()
async def _(event: GroupMessageEvent, args: Message = CommandArg()):
    data = load_config()
    cmd = args.extract_plain_text().strip().split(" ",1)
    if len(cmd) != 2 :
        await add_welcome.finish("⚠️ 用法：/添加群欢迎 <群号> <欢迎语>")
    gid,target_gid = map(str,cmd)

    if key_word not in data:
        data[key_word] = {}
    data[key_word][str(gid)] = target_gid
    save_config(data)
    await add_welcome.finish(f"✅ 已添加 {gid} 的群欢迎")


@del_welcome.handle()
async def _(event: GroupMessageEvent, args: Message = CommandArg()):
    data = load_config()
    cmd = args.extract_plain_text().strip()
    if not cmd.isdigit():
        await del_welcome.finish("⚠️ 用法：/移除群欢迎 <群号>")
    gid = int(cmd)

    if key_word not in data or str(gid) not in data[key_word]:
        await del_welcome.finish(f"❌ 群 {gid} 未开启群欢迎")
    data[key_word].pop(str(gid))
    save_config(data)
    await del_welcome.finish(f"✅ 已移除 {gid} 的群欢迎")
