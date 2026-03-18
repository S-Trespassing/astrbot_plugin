from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageSegment
from core.myconfig import BASE_DIR
# 定义命令触发器
send_image = on_command("校历", priority=5)
xiao_li_path = BASE_DIR /"my_resources" / "xiao_li.jpg"
@send_image.handle()
async def _(event):
    await send_image.finish(MessageSegment.image(xiao_li_path.as_uri()))
