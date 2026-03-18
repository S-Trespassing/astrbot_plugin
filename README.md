# 群管理插件

AstrBot 群管理插件，提供邀请树记录、入群防机器人验证、二维码/邀请卡片监控，以及插件自更新能力。

当前版本面向 `aiocqhttp` 平台，适用于需要在 QQ 群内做基础安全治理和成员管理的场景。

## 功能概览

- 邀请树记录
  - 记录成员邀请关系
  - 支持查看某个成员的邀请树
  - 支持一键踢出整棵邀请子树
- 入群防机器人
  - 新成员入群后先禁言，再触发验证码验证
  - 被邀请入群的成员也会参与验证
  - 优先私聊发送验证码图片
  - 如果私聊发送失败，会在群内发送兜底通知和验证码图片
  - 验证通过后自动解除禁言
  - 超时未完成验证会自动踢出群聊
- 群监控
  - 检测 QQ/微信群二维码
  - 检测邀请卡片类消息
  - 支持撤回违规消息
  - 支持将告警转发到指定告警群
- 白名单
  - 白名单用户不会触发防机器人
  - 白名单用户不会触发二维码监控
- 插件自更新
  - 支持配置 GitHub 仓库和分支
  - 支持通过命令拉取最新版本并尝试自动重载

## 运行要求

- AstrBot 版本：`>=4.13.0,<5`
- 平台适配器：`aiocqhttp`
- 机器人建议具备以下权限
  - 群禁言
  - 踢出成员
  - 撤回消息
  - 私聊成员

如果机器人没有私聊权限，防机器人流程会退化为群内发送验证码提示；如果群内兜底通知也失败，新成员会保持待验证状态，直到超时后被自动踢出。

## 安装方式

### 方式一：通过 GitHub 仓库安装

在 AstrBot 插件页中选择通过 URL 安装，填入：

```text
https://github.com/S-Trespassing/astrbot_plugin
```

### 方式二：通过自定义插件源安装

本仓库已经提供 AstrBot 可直接识别的插件源文件：

```text
https://raw.githubusercontent.com/S-Trespassing/astrbot_plugin/main/plugin_cache.json
```

在 AstrBot 插件市场中添加这条自定义源后，可以直接安装，也更容易被 AstrBot 识别为“可更新”插件。

### 方式三：本地打包后上传安装

在仓库根目录执行：

```bash
python pack_plugin.py
```

生成文件：

```text
dist/astrbot_plugin_group_manage.zip
```

然后在 AstrBot 插件页中通过 zip 上传安装。

## 快速开始

推荐的启用顺序：

1. 开启目标群的防机器人
2. 开启目标群的邀请树
3. 按需开启群监控
4. 配置白名单，排除可信用户

常见配置建议：

- `anti_bot_verify_timeout_seconds`：建议保持 `300`
- `anti_bot_mute_duration_seconds`：建议大于等于验证码有效期
- `skip_admins`：通常保持 `true`
- `delete_violation_message`：建议开启

## 命令说明

### 邀请树

- `/开启邀请树 <群号>`
- `/关闭邀请树 <群号>`
- `/查看邀请树配置`
- `/查看邀请树 <@群成员 或 QQ号>`
- `/踢出邀请树 <@群成员 或 QQ号>`

说明：

- `查看邀请树` 和 `踢出邀请树` 只能在群内使用
- 邀请树会记录普通入群和邀请入群关系
- 如果邀请者是管理员或群主，并且开启了 `skip_admins`，该成员会被作为树根处理

### 防机器人

- `/开启防机器人 <群号>`
- `/关闭防机器人 <群号>`
- `/查看防机器人配置`

验证流程：

1. 新成员入群后先被禁言
2. 机器人优先尝试私聊发送 6 位数字验证码图片
3. 私聊失败时，群内发送兜底提示
4. 成员向机器人私聊发送验证码
5. 验证成功后自动解除禁言
6. 超时未验证则自动踢出

注意：

- 被邀请入群的新成员同样参与验证
- 只接受纯 6 位数字验证码
- 验证超时时间由 `anti_bot_verify_timeout_seconds` 控制

### 群监控

- `/添加群监控 <源群号> <告警群号>`
- `/移除群监控 <群号>`
- `/查看群监控`

说明：

- 会检查消息中的二维码和邀请卡片
- 命中后可撤回原消息
- 可选是否在源群提示
- 可选是否转发到告警群

### 白名单

- `/添加白名单 <@群成员 或 QQ号>`
- `/移除白名单 <@群成员 或 QQ号>`
- `/查看白名单`

### 插件更新

以下命令仅 AstrBot 管理员可用：

- `/设置更新仓库 <GitHub仓库地址> [分支]`
- `/查看更新配置`
- `/更新群管理插件`

示例：

```text
/设置更新仓库 https://github.com/S-Trespassing/astrbot_plugin main
```

## 权限说明

群管理相关命令默认要求以下任一身份：

- 当前群群主
- 当前群管理员
- AstrBot 管理员

插件更新命令仅 AstrBot 管理员可用。

## 配置项说明

### 邀请树

- `invite_tree_enabled_groups`
  - 需要记录邀请树的群号列表

### 防机器人

- `anti_bot_enabled_groups`
  - 开启防机器人的群号列表
- `anti_bot_mute_duration_seconds`
  - 入群后禁言时长，默认 `1800`
- `anti_bot_verify_timeout_seconds`
  - 验证码有效期，默认 `300`
  - 超时未验证会自动踢出

### 群监控

- `monitor_groups`
  - 源群和告警群映射配置
- `delete_violation_message`
  - 命中后是否优先撤回消息
- `notify_group`
  - 命中后是否在源群发送处理提示
- `forward_alert`
  - 命中后是否转发告警到目标群

### 其他

- `whitelist_users`
  - 白名单用户列表
- `skip_admins`
  - 是否跳过群主和管理员
- `update_repo_url`
  - 插件自更新使用的 GitHub 仓库地址
- `update_branch`
  - 插件自更新使用的分支，默认 `main`
- `update_github_token`
  - 私有仓库或高频更新时可选填

## 更新与发布

仓库已内置两条 GitHub Actions 工作流：

- `Build Release Package`
  - 推送 `v*` 标签时自动打包 zip 并创建 GitHub Release
- `Sync Plugin Source`
  - 当 `metadata.yaml` 变化时自动同步 `plugin_cache.json`

推荐发布流程：

1. 修改 `metadata.yaml` 中的版本号
2. 提交并推送到 GitHub
3. 打标签并推送，例如：

```bash
git tag v1.2.1
git push origin v1.2.1
```

这样既能生成 Release，也能让 AstrBot 自定义源识别到新版本。

## 开发与测试

安装依赖后，可执行：

```bash
python -m unittest discover -s tests
```

仅跑防机器人相关测试：

```bash
python -m unittest discover -s tests -p "test_anti_bot*.py"
```

本地打包：

```bash
python pack_plugin.py
```

## 仓库地址

- GitHub 仓库：[S-Trespassing/astrbot_plugin](https://github.com/S-Trespassing/astrbot_plugin)
- AstrBot 项目：[AstrBotDevs/AstrBot](https://github.com/AstrBotDevs/AstrBot)

如果你准备继续扩展这个插件，建议优先保持 `metadata.yaml`、`plugin_cache.json` 和 `README.md` 三者信息一致，这样 AstrBot 插件页里的版本、仓库入口、文档和更新提示才不会错位。
