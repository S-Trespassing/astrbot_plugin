import httpx
import json  # 用于将字典转换为字符串
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message
from nonebot.params import CommandArg

# 查空教室的命令
dl_ask = on_command("查空教室", aliases={'空教室', '教室', '查教室','查室'}, priority=5, block=True)

# 查课表的命令
dl_schedule = on_command("查课表", aliases={'课表', '课程','查课'}, priority=5, block=True)

@dl_ask.handle()
async def _(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    arg_text = args.extract_plain_text().strip()
    if not arg_text:
        await bot.send_group_msg(group_id=event.group_id, message="⚠️ 缺少必要参数, 示例:\n/查空教室 c楼 9-11(可选)")
        return
    
    try:
        # 使用提取的arg_text作为query参数
        res = httpx.get(
            'https://web.werobot.easy-qfnu.top/api/free-classroom',
            follow_redirects=True,
            params={'query': arg_text},  # 这里使用arg_text
            timeout=10 
        )
        data = res.json()
        
        # 处理返回数据
        if data.get('success'):
            classroom_count = data['data'].get('classroom_count', 0)
            target_date = data['data']['parsed_params'].get('target_date', '未知日期')
            building = data['data']['parsed_params'].get('building', '未知楼层')
            periods = data['data']['parsed_params'].get('periods', '未知时间')
            weekday = data['data']['parsed_params'].get('weekday', '未知星期')

            url = data['data'].get('html_url')
            if url:
                try:
                    final = httpx.get(url, follow_redirects=True, timeout=10)
                    msg = f"✅️ 查询成功啦: {str(final.url)}"
                except Exception:
                    msg = f"✅️ 查询成功啦: {url}"
            else:
                msg = "✅️ 查询成功啦: 暂无详情链接"
        else:
            # 错误处理（如果 success 为 false）
            error_code = data.get('error', {}).get('code', '未知错误代码')
            error_message = data.get('error', {}).get('message', '没有错误描述信息')
            if error_code == 'NO_RESULT':
                msg = "未找到符合条件的空闲教室"
            else:
                msg = f"❌️ 查询失败，错误代码: {error_code}\n错误描述: {error_message}"

    except httpx.RequestError as e:
        try:
            data = e.response.json() if e.response is not None else None
        except Exception:
            data = None
        if isinstance(data, dict) and data.get('error'):
            code = data.get('error', {}).get('code', '未知错误代码')
            if code == 'NO_RESULT':
                msg = "未找到符合条件的空闲教室"
            else:
                msg = f"❌️ 查询失败，错误代码: {code}\n错误描述: {data.get('error', {}).get('message', '没有错误描述信息')}"
        else:
            msg = f"❌️ 请求失败: {e}"
    except Exception as e:
        msg = f"❌️ 发生错误: {e}"
    
    # 发送消息到群组
    await bot.send_group_msg(group_id=event.group_id, message=msg)


@dl_schedule.handle()
async def _(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    arg_text = args.extract_plain_text().strip()
    if not arg_text:
        await bot.send_group_msg(group_id=event.group_id, message="⚠️ 缺少必要参数, 示例:\n/查课表 c楼 9-11(可选)")
        return
    
    try:
        # 使用提取的arg_text作为query参数
        res = httpx.post(
            'https://web.werobot.easy-qfnu.top/api/classroom-schedule',
            json={'query': arg_text},  # 这里使用arg_text
            follow_redirects=True,
            timeout=10 
        )
        data = res.json()
        
        # 处理返回数据
        if data.get('success'):
            target_date = data['data']['parsed_params'].get('target_date', '未知日期')
            building = data['data']['parsed_params'].get('building', '未知楼层')
            classroom_count = data['data'].get('classroom_count', 0)
            weekday = data['data']['parsed_params'].get('weekday', '未知星期')
            url = data['data'].get('html_url')
            if url:
                try:
                    final = httpx.get(url, follow_redirects=True, timeout=10)
                    msg = f"✅️ 查询成功啦: {str(final.url)}"
                except Exception:
                    msg = f"✅️ 查询成功啦: {url}"
            else:
                msg = "✅️ 查询成功啦: 暂无详情链接"
        else:
            # 错误处理（如果 success 为 false）
            error_code = data.get('error', {}).get('code', '未知错误代码')
            error_message = data.get('error', {}).get('message', '没有错误描述信息')
            if error_code == 'NO_RESULT':
                msg = "未找到符合条件的空闲教室"
            else:
                msg = f"❌️ 查询失败，错误代码: {error_code}\n错误描述: {error_message}"

    except httpx.RequestError as e:
        try:
            data = e.response.json() if e.response is not None else None
        except Exception:
            data = None
        if isinstance(data, dict) and data.get('error'):
            code = data.get('error', {}).get('code', '未知错误代码')
            if code == 'NO_RESULT':
                msg = "未找到符合条件的空闲教室"
            else:
                msg = f"❌️ 查询失败，错误代码: {code}\n错误描述: {data.get('error', {}).get('message', '没有错误描述信息')}"
        else:
            msg = f"❌️ 请求失败: {e}"
    except Exception as e:
        msg = f"❌️ 发生错误: {e}"
    
    # 发送消息到群组
    await bot.send_group_msg(group_id=event.group_id, message=msg)
