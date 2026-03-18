from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageSegment
import httpx
from core.myconfig import SAVE_PATH
from pathlib import Path
from core.tools import send_video_to_group
import time
# 注册命令，只能群聊触发
xjj = on_command("小姐姐", block=True, priority=5)


@xjj.handle()
async def _(bot: Bot, event: GroupMessageEvent):
    api_url = "https://api.istero.com/resource/v1/douyin/video/rand?token=TmyUZcJqhBqUtUHzSpDRdlHphcgWafFk"  # 你要调用的 API 地址

    try:
        # 请求 API
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(api_url)
            resp.raise_for_status()
            data = resp.json()

        if data.get("code") != 200:
            await xjj.finish("获取失败了~")

        video_url = data["data"]["video"]

        # 下载视频到临时文件
        async with httpx.AsyncClient(timeout=60) as client:
            video_resp = await client.get(video_url)
            video_resp.raise_for_status()
            video_path=SAVE_PATH / Path(f"{time.time()}.mp4")
            with open(video_path, "wb") as f:
                f.write(video_resp.content)

        # 发送视频
        await send_video_to_group(video_path,str(event.group_id),f"小姐姐{str(time.time())[0:3]}" )


    except Exception as e:
            await xjj.finish(f"出错了，{e}")
