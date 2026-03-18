from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, Message,MessageEvent
from nonebot.params import CommandArg
from core.GD_music import search_song
from nonebot.adapters.onebot.v11 import GroupMessageEvent,MessageEvent,PrivateMessageEvent
import asyncio
from nonebot.exception import FinishedException
# 全局缓存，key = user_id，value = songs_list
song_cache = {}

song_list_cmd = on_command("歌曲名单", aliases={"歌单","名单","点歌","音乐","歌名"}, priority=5)

# 创建锁
my_plugin_lock = asyncio.Lock()

@song_list_cmd.handle()
async def send_song_list(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    if isinstance(event, GroupMessageEvent):
        try:
            group_id = event.group_id
            user_id = event.user_id
            cmd = args.extract_plain_text().strip()
            if not cmd:
                await song_list_cmd.finish("⚠️ 请在命令后输入歌曲名，比如：/点歌 青花瓷")
            tip_msg =await song_list_cmd.send(f"✅ 织梦收到你的命令啦,请稍等~")
            songs_list = await search_song(cmd)
            if not songs_list:
                await song_list_cmd.finish("⚠️ 未找到相关歌曲。")

            # 按群+用户缓存
            if group_id not in song_cache:
                song_cache[group_id] = {}
            song_cache[group_id][user_id] = songs_list
            # 构造节点，每个节点包含 5 条歌曲信息
            nodes = []
            batch_size = 5
            for i in range(0, len(songs_list), batch_size):
                batch_songs = songs_list[i:i + batch_size]
                content = ""
                for j, song in enumerate(batch_songs, i + 1):
                    if song.song_author:
                        content += f"{j}. {song.song_name} - {song.song_author}\n"
                    else:
                        content += f"{j}. {song.song_name}\n"
                nodes.append({
                    "type": "node",
                    "data": {
                        "name": "织梦",
                        "uin": bot.self_id,
                        "content": content.strip()
                    }
                })

            # 最后一条节点加上下载提示
            nodes.append({
                "type": "node",
                "data": {
                    "name": "织梦",
                    "uin": bot.self_id,
                    "content": "✅ 发送：/下载 序号 下载指定歌曲~"
                }
            })

            # 分批发送，每个转发卡片最多 4 个节点
            card_size = 10
            for i in range(0, len(nodes), card_size):
                batch = nodes[i:i + card_size]
                await bot.call_api("send_group_forward_msg", group_id=group_id, messages=batch)
            try:
                await bot.delete_msg(message_id=tip_msg["message_id"])
            except Exception as e:
                pass
        except FinishedException:
            pass
        except Exception as e:
            await song_list_cmd.finish(f"❌ 发生错误:{e}")
    elif isinstance(event, PrivateMessageEvent):
        await song_list_cmd.finish("⚠️ 该命令暂不支持私聊哦")
    else:
        await song_list_cmd.finish("❌ 消息类型异常")

download_cmd = on_command("下载",aliases={"下载音乐","dowonload"}, priority=5)
@download_cmd.handle()
async def download_song(bot:Bot,event: MessageEvent, args: Message = CommandArg()):
    if isinstance(event, GroupMessageEvent):
        try:
            group_id = event.group_id
            user_id = event.user_id
            text = args.extract_plain_text().strip()
            if not text.isdigit():
                await download_cmd.finish("⚠️ 请发送有效的序号，例如：/下载 1")

            index = int(text) - 1

            # 先取群缓存，再取用户缓存
            group_cache = song_cache.get(group_id, {})
            songs_list = group_cache.get(user_id)
            if not songs_list:
                await download_cmd.finish("⚠️ 请先在本群使用 /歌单 搜索歌曲")

            if index < 0 or index >= len(songs_list):
                await download_cmd.finish("⚠️ 序号无效，请重新发送")
            if my_plugin_lock.locked():
                await download_cmd.finish("⚠️ 忙不过来了呜呜呜，一会再试试吧~")
            song = songs_list[index]
            tip_msg=await song_list_cmd.send(f"✅ 织梦收到你的命令啦,请稍等~")
            async with my_plugin_lock:
                # 异步下载
                await song.download(group_id )
            try:
                await bot.delete_msg(message_id=tip_msg["message_id"])
            except Exception as e:
                pass
            await download_cmd.finish()
        except FinishedException:
            pass
        except Exception as e:
            await song_list_cmd.finish(f"❌ 发生错误:{e}")
    elif isinstance(event, PrivateMessageEvent):
        await download_cmd.finish("⚠️ 该命令暂不支持私聊哦")
    else:
        await download_cmd.finish("❌ 消息类型异常")





