from nonebot import on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent,PrivateMessageEvent,MessageEvent,Bot
from nonebot.params import CommandArg
import re
from core.myconfig import load_headers,BASE_DIR
from core.bilibili import  get_video_and_audio,get_bv
from core.tools import extract_url,send_video_to_group
send_video = on_command("解析")
headers = load_headers()

@send_video.handle()
async def handle_send_video(bot:Bot,event: MessageEvent, msg=CommandArg()):
    if isinstance(event,GroupMessageEvent):
        tip_msg=await send_video.send(f"✅ 织梦收到你的命令啦,请稍等~")
        url = extract_url(msg.extract_plain_text().strip())
        group_id=str(event.group_id)
        if "b23.tv" in url:
            bv = await get_bv(url)
            if not bv:
                await send_video.finish("⚠️ 无法解析BV号，url可能已经失效")
        else:
            bv_match = re.search(r"BV[0-9A-Za-z]{10}", url)
            if not bv_match:
                await send_video.finish("⚠️ 请确保URL中包含有效的BV号")
            bv = bv_match.group()

        save_dir = BASE_DIR / "tmp"
        video_path=""
        title=""

        try:
            video_path,title = await get_video_and_audio(bv, save_dir,False)
        except Exception as e:
            await send_video.finish(f"❌ 视频下载或合成失败：{e}")
        await send_video_to_group(video_path,group_id, title,f"已发送视频：{title}")
        try:
            await bot.delete_msg(message_id=tip_msg["message_id"])
        except Exception as e:
            pass
        await send_video.finish()
    elif isinstance(event,PrivateMessageEvent):
        await send_video.finish("⚠️ 该命令暂不支持私聊哦")
    else:
        await send_video.finish("❌ 消息类型异常")