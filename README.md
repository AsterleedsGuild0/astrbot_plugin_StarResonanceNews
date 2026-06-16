# astrbot_plugin_StarResonanceNews

星痕共鸣（Star Resonance）国服官网新闻查询与自动推送插件。

支持在群聊中手动查询最近官网新闻，并按配置间隔自动轮询腾讯 WMP 新闻接口，发现新新闻后自动推送到指定群。

---

## 功能特性

- 命令别名：`星痕国服新闻`、`星痕共鸣国服新闻`、`星痕官网新闻`、`星痕国服公告`、`星痕官网公告`
- 查询最近 5 条（可配置）星痕共鸣国服官网新闻
- 新闻包含标题、发布时间、官网详情链接
- 自动轮询：默认每 5 分钟检测官网新闻更新
- 群聊订阅默认关闭，可由管理员在当前群开启或关闭星痕新闻推送
- 基于 `iNewsId` 去重，避免重复推送
- 持久化缓存：插件重启后不重复推送旧新闻
- 首次启动只建立缓存，不推送历史新闻
- AI 总结：提取新闻详情页全文，并调用 AstrBot 已启用的默认或指定 LLM 总结
- 自动推送新新闻后，可继续自动推送该新闻的 AI 总结
- AI 总结过长时可在插件内直接调用 AstrBot T2I 渲染为图片，减少刷屏
- 可配置轮询开关、间隔、推送目标、请求超时、最大推送条数等
- 随包提供 `skills/SKILL.md`，让 AstrBot LLM 能知道插件用途、命令和限制

---

## 软件要求

- AstrBot：`>= 4.11.2`
- Python：跟随 AstrBot 运行环境
- 第三方依赖：`httpx >= 0.27.0`

---

## 安装

### 本地开发源

将插件放在工作区插件源码目录：

```text
Plugins/astrbot_plugin_StarResonanceNews
```

### 打包安装

```bash
python scripts/package_plugin.py --dev-version
```

生成的 zip 包可在 AstrBot WebUI 的插件管理页面中上传安装。

---

## 使用说明

### 手动查询

| 命令 | 说明 |
| --- | --- |
| `星痕国服新闻` | 查看最近 5 条星痕共鸣国服新闻 |
| `星痕共鸣国服新闻` | 同上 |
| `星痕官网新闻` | 同上 |
| `星痕国服公告` | 同上 |
| `星痕官网公告` | 同上 |
| `星痕新闻帮助` | 查看插件帮助 |
| `星痕新闻总结` | 总结最近第 1 条新闻 |
| `星痕新闻总结 2` | 总结最近列表中的第 2 条新闻 |
| `星痕新闻总结 <newsid>` | 总结指定新闻 ID 对应的详情页 |
| `星痕新闻总结 <链接>` | 总结指定官网新闻详情链接 |
| `星痕新闻总结模型` | 查看当前 AstrBot 已启用的可用 Chat Provider |
| `星痕新闻推送开启` | 管理员开启当前群聊星痕新闻自动推送 |
| `星痕新闻推送关闭` | 管理员关闭当前群聊星痕新闻自动推送 |
| `星痕新闻推送状态` | 查看自动轮询、缓存和最近错误状态 |
| `星痕新闻检查更新` | 管理员手动检查并推送新增新闻 |

### 自动推送

插件启动后按配置间隔自动轮询官网接口：

- 群聊默认不订阅新闻推送，需要管理员发送 `星痕新闻推送开启`
- 发现新新闻时推送至已订阅群或 WebUI 配置的固定推送目标
- 推送新闻后默认继续推送对应 AI 总结，可用 `auto_summary_on_push` 关闭
- 无新新闻时仅记录日志，不发送群消息
- 接口异常时记录日志，不影响插件继续运行

---

## 配置说明

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `polling_enabled` | `bool` | `true` | 是否启用自动轮询 |
| `polling_interval_seconds` | `int` | `300` | 轮询间隔（秒），最小 60 秒 |
| `target_sessions` | `list` | `[]` | 推送会话列表（完整 session 格式） |
| `push_groups` | `list` | `[]` | 推送群 ID 列表（配合 platform_name） |
| `platform_name` | `string` | `aiocqhttp` | 消息平台名称 |
| `default_query_count` | `int` | `5` | 手动查询默认返回条数 |
| `max_query_count` | `int` | `10` | 手动查询最大返回条数 |
| `max_push_count_per_poll` | `int` | `5` | 单次轮询最多推送条数 |
| `admin_users` | `list` | `[]` | 插件管理员列表 |
| `request_timeout_seconds` | `int` | `15` | HTTP 请求超时（秒） |
| `request_verify_ssl` | `bool` | `false` | 校验 SSL 证书 |
| `request_proxy` | `string` | `""` | HTTP 请求代理地址，空表示不用代理 |
| `include_publish_time` | `bool` | `true` | 消息中是否包含发布时间 |
| `ai_summary_enabled` | `bool` | `true` | 是否启用 AI 总结命令 |
| `auto_summary_on_push` | `bool` | `true` | 自动推送新新闻后是否继续推送该新闻 AI 总结 |
| `ai_summary_provider_id` | `string` | `""` | AI 总结使用的 AstrBot Chat Provider ID，留空使用当前会话默认模型 |
| `ai_summary_max_article_chars` | `int` | `12000` | 详情页正文交给模型前的最大字符数 |
| `ai_summary_t2i_enabled` | `bool` | `true` | AI 总结结果过长时是否在插件内直接调用 AstrBot T2I 转图片 |
| `ai_summary_t2i_threshold` | `int` | `800` | AI 总结结果达到该字符数时转图片，设为 0 表示总是转图片 |
| `ai_summary_prompt` | `text` | 见配置页 | AI 总结提示词 |
| `storage_filename` | `string` | `star_resonance_news.json` | 数据文件名 |
| `permission_denied_notice` | `bool` | `true` | 权限不足时发送提示 |

### AI 总结模型选择

`ai_summary_provider_id` 使用 AstrBot 配置页的 `_special: select_provider` 选择器，只应选择当前 AstrBot 已启用的 Chat Provider。插件运行时也会通过 `context.get_all_providers()` 校验，未启用或不存在的 provider ID 会被拒绝。

留空时，插件使用当前会话默认聊天模型；可发送 `星痕新闻总结模型` 查看当前运行时可用模型列表，该列表只展示 AstrBot 已启用并加载成功的 Chat Provider，不展示未启用模型。

### AI 总结转图片

由于新闻总结可能较长，插件提供 `ai_summary_t2i_enabled` 与 `ai_summary_t2i_threshold`：

- 开启后，AI 总结文本长度达到阈值时，插件会在返回消息前直接调用 AstrBot `html_renderer.render_t2i()` 渲染为图片。
- T2I 端点、渲染模板、remote/local 策略等仍沿用 AstrBot 全局 T2I 配置。
- 如果 T2I 渲染失败，插件会记录错误并回退文本发送。
- 该方式不依赖 `ResultDecorateStage` 的后续 `use_t2i(True)` 装饰链，避免被其他插件的装饰 hook 截断。
- 阈值设为 `0` 时，所有 AI 总结都尝试转图片。

### 推送目标配置

两种配置方式：

1. **完整 session 格式**（推荐）：`target_sessions`，如 `aiocqhttp:GroupMessage:123456789`
2. **群 ID + 平台名**：`push_groups` 填入群号，`platform_name` 设置为当前适配器名称

也可以在群聊中由管理员发送 `星痕新闻推送开启` / `星痕新闻推送关闭` 管理当前群订阅。群聊订阅状态会持久化到插件数据文件，默认关闭。

---

## LLM Skill 说明

插件随包提供：

```text
skills/SKILL.md
```

AstrBot 启用插件 Skill 后，LLM 可通过该文档了解本插件的使用场景、命令、配置要点、状态排查方式和当前未实现能力。

维护要求：每次新增、删除或修改用户可感知功能时，必须同步更新：

- `README.md`
- `PRD.md` 或其他功能设计文档
- `skills/SKILL.md`

---

## 数据源

- 接口：`https://apps.game.qq.com/wmp/v3.1/`
- 详情页模板：`https://gm.qq.com/web202503/news-detail.html?newsid=<iNewsId>`

---

## 当前状态

当前版本为 MVP，已实现：

- [x] 手动查询最近新闻（5 条别名命令）
- [x] 自动轮询与去重推送
- [x] 群聊内开启 / 关闭当前群新闻推送，默认关闭
- [x] 基于 `iNewsId` 的持久化缓存
- [x] 首次启动仅建立缓存，不推送历史
- [x] 可配置的轮询开关、间隔、推送目标、超时、推送条数
- [x] 推送状态查看与管理员手动检查更新
- [x] 新闻详情页全文提取 + AstrBot LLM AI 总结
- [x] 自动推送后继续推送对应 AI 总结
- [x] AI 总结模型可配置为已启用 Chat Provider，留空使用当前会话默认模型
- [x] AI 总结长文本在插件内直接调用 AstrBot T2I 转图片

暂未实现（P1 / 后续版本）：

- 按分类查询（公告/新闻/活动）
- 查询指定数量
- 刷新 / 清空缓存命令
- 封面图发送
- WebUI / Pages 管理

---

## 致谢

- `azmiao/YuiChyanBot`：<https://github.com/azmiao/YuiChyanBot>
- StarResonanceNews 模块的产品思路与接口分析
- 插件 logo 复用 `astrbot_plugin_xqa` 图标

---

## 许可证

本仓库使用 GNU General Public License v3.0。
