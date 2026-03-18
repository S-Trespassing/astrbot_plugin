from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent
from nonebot.typing import T_State
import json
from core.tools import handle_violation_text,check_number_type,handle_violation_image
import re
from nonebot.exception import FinishedException
from nonebot import on_message
from core.myconfig import SAVE_PATH, load_config,load_sensitive_words
from core.tools import download_image
from core.QRCodeDetector.detector import qrcode_ck
import asyncio

# 监听所有群消息
sensitive_checker = on_message(priority=5, block=False)

# 监控消息
@sensitive_checker.handle()
async def check_sensitive(bot: Bot, event: GroupMessageEvent, state: T_State):
    if not isinstance(event, GroupMessageEvent):
        return  # 只在群聊检测

    cfg = load_config()
    monitor_groups: dict = cfg.get("monitor_groups", {})
    white_list = cfg.get("white_list", [])
    gid = str(event.group_id)

    # 只处理配置中的群
    if gid not in monitor_groups:
        return
    if event.user_id in white_list:
        return  # 白名单用户跳过
    # 获取群员权限
    role = event.sender.role  # "owner", "admin", "member"
    if role in ["owner", "admin"]:
        return  # 群主/管理员跳过
    #qq号,群号检测
    msg_text = event.get_plaintext().strip()
    sensitive_words = load_sensitive_words()
    numbers = re.findall(r"\d{5,12}", msg_text)
    # qq号检测
    for num in numbers:
        try:
            if await check_number_type(num):
                await handle_violation_text(bot, event, msg_text, num, monitor_groups[gid])
                return
        except FinishedException:
            pass
        except Exception as e:
            await sensitive_checker.finish(f"⚠️ 检测失败: {e}")

    # 普通文本违禁词检测
    for word in sensitive_words:
        if word and word in msg_text:
            await handle_violation_text(bot, event, msg_text, word, monitor_groups[gid])
            return

    # JSON 卡片消息检测（好友 / 群聊邀请）
    for seg in event.message:
        if seg.type == "json":
            raw = seg.data.get("data", "")
            try:
                j = json.loads(raw)
                app = j.get("app")
                view = j.get("view")
                if app == "com.tencent.contact.lua" and view == "contact":
                    await handle_violation_text(
                        bot,
                        event,
                        "[邀请卡片消息]",
                        "邀请卡片",
                        monitor_groups[gid],
                    )
                    return
            except Exception:
                continue
        # 遍历消息中的图片
    for seg in event.message:
        if seg.type != "image":
            continue
        #尝试获取图片url
        url = seg.data.get("url")
        if not url:
            continue
        filename = f"{event.group_id}_{event.user_id}_{int(event.time)}.jpg"
        pic_path = SAVE_PATH / filename

        try:
            await download_image(url, filename)
            # 检测二维码是否违规
            if qrcode_ck(pic_path):
                await handle_violation_image(bot, event, pic_path, monitor_groups[gid])
                return

        except FinishedException:
            # NoneBot 内部结束事件，这里直接跳过
            return
        except Exception as e:
            await bot.send_group_msg(
                group_id=event.group_id,
                message=f"❌ 操作失败: {e}"
            )
        await asyncio.sleep(0.1)  # 避免触发风控





