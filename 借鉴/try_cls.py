import httpx
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message
from nonebot.params import CommandArg

dl_ask = on_command("查空教室", priority=5, block=True)


@dl_ask.handle()
async def _(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    arg_text = args.extract_plain_text().strip()

    # 默认查询参数为空
    query = arg_text if arg_text else '明天综合楼3-4节'

    try:
        # 发起 API 请求
        res = httpx.get(
            'http://web.werobot.easy-qfnu.top/api/free-classroom',
            params={'query': query}
        )

        # 检查请求是否成功
        res.raise_for_status()

        # 解析返回的 JSON 数据
        data = res.json()

        # 处理返回数据
        if data.get('status') == 'success':
            free_classrooms = data.get('data', [])
            if free_classrooms:
                msg=free_classrooms
            else:
                msg = "未找到符合条件的空教室。"
        else:
            msg = "查询失败，请稍后再试。"

    except httpx.RequestError as e:
        msg = f"请求失败: {e}"
    except Exception as e:
        msg = f"发生错误: {e}"

    # 发送消息到群组
    await bot.send_group_msg(group_id=event.group_id, message=msg)
