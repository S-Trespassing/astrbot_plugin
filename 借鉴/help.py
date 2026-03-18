from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageSegment

help_cmd = on_command("?", aliases={"help","menu",'菜单'})
mode_msg = ['J源(无损)','J源(高品)','N源(无损)','N源(高品)',"K源(无损)",'K源(高品)','B源(视频)', 'B源(标准)']
options = "\n".join([f" →  {i + 1}: {v}" for i, v in enumerate(mode_msg)])
@help_cmd.handle()
async def send_help():
    help_text = (
        "🎵【织梦音乐机器人 使用说明】🎵\n\n"
        "我是一个专注于音乐视频解析和下载的机器人，帮你轻松点歌，方便快捷！\n\n"
        "主要功能：\n"
        "🎤 点歌命令：\n"
        "  /点歌 歌曲名\n"
        "  → 搜索歌曲,以视频或音频的形式发送\n\n"
        "📹 视频解析：\n"
        "  /解析 B站视频链接\n"
        "  → 解析B站视频，发送到群里\n\n"
        "🎵 音乐下载：\n"
        "  /下载 序号\n"
        "  → 根据歌曲列表的序号下载音乐并上传群文件\n"
        "⚠️ 注意事项：\n"
        "  • 受协议适配器限制,视频超过100MB后将会以文件的形式发送\n"
        "  • 相关功能暂未适配私聊,请将我拉到群中使用\n"
        "  • 遇到问题请联系QQ:2669807502\n\n"
        "感谢使用，期待你的点歌！ ❤️\n\n"
        "—— 开发者 Trespassing"
    )
    await help_cmd.finish(MessageSegment.text(help_text))
