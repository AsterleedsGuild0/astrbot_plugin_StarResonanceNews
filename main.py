from __future__ import annotations

import asyncio
from typing import Any

import astrbot.api.message_components as Comp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.event import MessageEventResult
from astrbot.api.star import Context, Star, StarTools

from .core.spider import CnSpider, NewsItem
from .core.store import NewsStore


QUERY_COMMANDS = {
    "星痕国服新闻",
    "星痕共鸣国服新闻",
    "星痕官网新闻",
    "星痕国服公告",
    "星痕官网公告",
}
HELP_COMMANDS = {"星痕新闻帮助"}
SUMMARY_COMMAND = "星痕新闻总结"


class StarResonanceNewsPlugin(Star):
    """星痕共鸣国服官网新闻查询与自动推送插件."""

    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.context = context
        self.config: AstrBotConfig = config

        self.store = NewsStore(
            StarTools.get_data_dir("astrbot_plugin_StarResonanceNews"),
            filename=str(config.get("storage_filename", "star_resonance_news.json")),
        )
        self.spider = CnSpider(config=dict(config))

        self._poller_task: asyncio.Task[None] | None = None
        self._running = False

    # ── Lifecycle ────────────────────────────────────────

    async def initialize(self) -> None:
        await self.store.load()
        logger.info("[星痕共鸣新闻] 插件初始化完成")

        if not self.config.get("polling_enabled", True):
            logger.info("[星痕共鸣新闻] 自动轮询已禁用，仅支持手动查询")
            return

        # First startup: build cache, don't push history
        if not self.store.get_seen_ids():
            await self._first_run_cache()
        else:
            logger.info(
                f"[星痕共鸣新闻] 已有缓存（{len(self.store.get_seen_ids())} 条已见 ID），跳过首次缓存"
            )

        # Start background poller
        self._running = True
        self._poller_task = asyncio.create_task(
            self._run_poller(), name="star_news_poller"
        )
        self._poller_task.add_done_callback(self._on_poller_done)
        logger.info("[星痕共鸣新闻] 轮询任务已启动")

    async def _first_run_cache(self) -> None:
        """Fetch current news on first run and mark all as seen without pushing."""
        try:
            items = await self.spider.fetch(page_size=10)
            self.store.initialize_cache(items)
            await self.store.save()
            logger.info(
                f"[星痕共鸣新闻] 首次启动，已缓存 {len(items)} 条新闻，不推送历史"
            )
        except Exception as e:
            logger.error(f"[星痕共鸣新闻] 首次缓存失败: {type(e).__name__}: {e}")

    def _on_poller_done(self, task: asyncio.Task[None]) -> None:
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.error(f"[星痕共鸣新闻] 轮询任务异常: {e}")
            return
        if exc is not None:
            logger.error(f"[星痕共鸣新闻] 轮询任务异常退出: {exc!r}")

    async def terminate(self) -> None:
        self._running = False
        if self._poller_task and not self._poller_task.done():
            self._poller_task.cancel()
            try:
                await self._poller_task
            except asyncio.CancelledError:
                pass
        logger.info("[星痕共鸣新闻] 插件已停止")

    # ── Polling ──────────────────────────────────────────

    async def _run_poller(self) -> None:
        interval = max(60, int(self.config.get("polling_interval_seconds", 300)))
        while self._running:
            try:
                await asyncio.sleep(interval)
                await self._check_and_push()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[星痕共鸣新闻] 轮询异常: {type(e).__name__}: {e}")

    async def _check_and_push(self) -> None:
        """Fetch latest news, detect new items, and push to subscribed groups."""
        try:
            items = await self.spider.fetch(
                page_size=max(5, int(self.config.get("max_push_count_per_poll", 5)) + 5)
            )
        except Exception as e:
            self.store.set_last_error(f"{type(e).__name__}: {e}")
            await self.store.save()
            logger.error(f"[星痕共鸣新闻] 获取新闻失败: {type(e).__name__}: {e}")
            return

        # Filter new items by seen IDs
        seen = self.store.get_seen_ids()
        new_items = [it for it in items if it.idx and it.idx not in seen]

        # Update cache and seen IDs regardless
        self.store.update_cache(items)
        self.store.set_last_success()
        await self.store.save()

        if not new_items:
            logger.debug("[星痕共鸣新闻] 无新新闻")
            return

        # Cap at configured max
        max_push = max(1, int(self.config.get("max_push_count_per_poll", 5)))
        push_items = new_items[:max_push]
        remaining = len(new_items) - len(push_items)

        logger.info(
            f"[星痕共鸣新闻] 发现 {len(new_items)} 条新新闻，推送 {len(push_items)} 条"
        )
        await self._push_news(push_items, remaining)

    async def _push_news(self, items: list[NewsItem], remaining: int = 0) -> None:
        """Push news items to configured target sessions."""
        include_time = bool(self.config.get("include_publish_time", True))
        msg = self.spider.format_items(
            items,
            prefix="星痕共鸣国服官网新闻更新",
            include_time=include_time,
        )
        if remaining > 0:
            msg += f"\n……还有 {remaining} 条未展示"

        sessions = self._get_target_sessions()
        if not sessions:
            logger.debug("[星痕共鸣新闻] 未配置推送目标，跳过推送")
            return

        chain = MessageChain([Comp.Plain(msg)])
        for session in sessions:
            try:
                await self.context.send_message(session, chain)
                logger.debug(f"[星痕共鸣新闻] 已推送至 {session}")
            except Exception as e:
                logger.error(f"[星痕共鸣新闻] 推送失败 session={session}: {e}")

    def _get_target_sessions(self) -> list[str]:
        """Build target session list from config.

        Supports two config approaches:
        1. ``target_sessions``: full session strings (e.g.
           ``aiocqhttp:GroupMessage:123456``)
        2. ``push_groups`` + ``platform_name``: construct sessions from
           group IDs and platform name.
        """
        sessions: list[str] = []

        # Full session strings
        raw_sessions = self.config.get("target_sessions", [])
        if isinstance(raw_sessions, list):
            for s in raw_sessions:
                s_str = str(s).strip()
                if s_str:
                    sessions.append(s_str)

        # Group IDs + platform name
        platform = str(self.config.get("platform_name", "aiocqhttp")).strip()
        group_ids = self.config.get("push_groups", [])
        if isinstance(group_ids, list):
            for gid in group_ids:
                gid_str = str(gid).strip()
                if gid_str:
                    candidate = f"{platform}:GroupMessage:{gid_str}"
                    if candidate not in sessions:
                        sessions.append(candidate)

        return sessions

    # ── Commands ─────────────────────────────────────────

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_plain_message(self, event: AstrMessageEvent):
        """兼容参考插件的无前缀自然语言命令。"""
        message = (event.get_message_str() or "").strip()
        if not message:
            return

        if message in QUERY_COMMANDS:
            event.stop_event()
            yield event.plain_result(await self._query_news())
            return

        if message in HELP_COMMANDS:
            event.stop_event()
            yield event.plain_result(self._help_text())
            return

        if message == SUMMARY_COMMAND or message.startswith(f"{SUMMARY_COMMAND} "):
            event.stop_event()
            yield self._summary_result(
                event, await self._summarize_news(event, message)
            )
            return

        if message == "星痕新闻总结模型":
            event.stop_event()
            yield event.plain_result(self._enabled_summary_models_text(event))
            return

    @filter.command(
        "星痕国服新闻",
        alias=QUERY_COMMANDS - {"星痕国服新闻"},
    )
    async def send_news(self, event: AstrMessageEvent):
        """手动查询最近星痕共鸣国服新闻."""
        yield event.plain_result(await self._query_news())

    async def _query_news(self) -> str:
        """Fetch latest news and return formatted string.

        Falls back to cached data on fetch failure.
        """
        include_time = bool(self.config.get("include_publish_time", True))
        try:
            max_query_count = max(1, int(self.config.get("max_query_count", 10)))
            page_size = min(
                max(1, int(self.config.get("default_query_count", 5))),
                max_query_count,
            )
            items = await self.spider.fetch(page_size=page_size)

            # Update store
            self.store.update_cache(items)
            self.store.set_last_success()
            await self.store.save()

            return self.spider.format_items(
                items[:page_size],
                prefix="星痕共鸣国服官网新闻",
                include_time=include_time,
            )
        except Exception as e:
            cached = self.store.get_cached_items()
            if cached:
                return (
                    self.spider.format_items(
                        cached, prefix="星痕共鸣国服官网新闻", include_time=include_time
                    )
                    + "\n⚠️ 当前为缓存数据，接口暂时不可用"
                )
            return f"新闻获取失败: {type(e).__name__}: {e}"

    @filter.command("星痕新闻帮助")
    async def news_help(self, event: AstrMessageEvent):
        """显示插件帮助信息."""
        yield event.plain_result(self._help_text())

    @filter.command(SUMMARY_COMMAND)
    async def summarize_news(self, event: AstrMessageEvent):
        """提取新闻详情页全文，并调用 AstrBot 已启用的 LLM 总结。"""
        yield self._summary_result(
            event,
            await self._summarize_news(event, (event.get_message_str() or "").strip()),
        )

    @filter.command("星痕新闻总结模型")
    async def summary_models(self, event: AstrMessageEvent):
        """列出当前 AstrBot 已启用的 Chat Provider。"""
        yield event.plain_result(self._enabled_summary_models_text(event))

    @filter.command("星痕新闻推送状态")
    async def news_status(self, event: AstrMessageEvent):
        """显示插件轮询与缓存状态."""
        yield event.plain_result(self._status_text())

    @filter.command("星痕新闻检查更新")
    async def manual_check_update(self, event: AstrMessageEvent):
        """手动检查新闻更新，并推送到配置目标。"""
        if not await self._is_plugin_admin(event):
            denied = self._permission_denied("此命令仅限管理员使用。")
            if denied:
                yield event.plain_result(denied)
            return

        try:
            items = await self.spider.fetch(
                page_size=max(5, int(self.config.get("max_push_count_per_poll", 5)) + 5)
            )
            seen = self.store.get_seen_ids()
            new_items = [it for it in items if it.idx and it.idx not in seen]

            self.store.update_cache(items)
            self.store.set_last_success()
            await self.store.save()

            if not new_items:
                yield event.plain_result("星痕共鸣国服官网暂无新新闻。")
                return

            max_push = max(1, int(self.config.get("max_push_count_per_poll", 5)))
            push_items = new_items[:max_push]
            remaining = len(new_items) - len(push_items)
            await self._push_news(push_items, remaining)
            yield event.plain_result(
                f"检查完成，发现 {len(new_items)} 条新新闻，已尝试推送 {len(push_items)} 条。"
            )
        except Exception as e:
            self.store.set_last_error(f"{type(e).__name__}: {e}")
            await self.store.save()
            yield event.plain_result(f"检查更新失败: {type(e).__name__}: {e}")

    def _help_text(self) -> str:
        return """星痕共鸣国服新闻插件帮助

查询命令：
  星痕国服新闻 / 星痕共鸣国服新闻
  星痕官网新闻 / 星痕国服公告
  星痕官网公告
  星痕新闻总结 [序号/新闻ID/链接]
  星痕新闻总结模型
  星痕新闻推送状态
  星痕新闻检查更新（管理员）

自动推送：
  每 5 分钟检测官网新闻更新（可配置），
  发现新新闻后自动推送至配置群。
  首次启动仅建立缓存，不推送历史新闻。

数据来源：
  腾讯游戏 WMP 新闻接口
  新闻详情页：
  https://gm.qq.com/web202503/news-detail.html?newsid=<ID>

权限：
  手动查询：所有群成员可用
  插件配置：Bot 管理员在 WebUI 中修改

配置项说明请在插件 WebUI 中查看。""".strip()

    def _status_text(self) -> str:
        sessions = self._get_target_sessions()
        summary_provider_id = str(self.config.get("ai_summary_provider_id", "") or "")
        return "\n".join(
            [
                "星痕共鸣国服新闻推送状态",
                f"自动轮询: {bool(self.config.get('polling_enabled', True))}",
                f"轮询任务运行中: {self._poller_task is not None and not self._poller_task.done()}",
                f"轮询间隔: {max(60, int(self.config.get('polling_interval_seconds', 300)))} 秒",
                f"推送目标数: {len(sessions)}",
                f"已见新闻数: {len(self.store.get_seen_ids())}",
                f"缓存新闻数: {len(self.store.cached_items)}",
                f"最近成功: {self.store.last_success_at or '暂无'}",
                f"最近错误: {self.store.last_error or '无'}",
                f"AI总结: {bool(self.config.get('ai_summary_enabled', True))}",
                f"AI总结模型: {summary_provider_id or '当前会话默认模型'}",
                f"AI总结转图片: {bool(self.config.get('ai_summary_t2i_enabled', True))}",
            ]
        )

    def _summary_result(self, event: AstrMessageEvent, text: str) -> MessageEventResult:
        result = event.plain_result(text)
        if not self.config.get("ai_summary_t2i_enabled", True):
            return result
        threshold = max(0, int(self.config.get("ai_summary_t2i_threshold", 800)))
        if len(text) >= threshold:
            result.use_t2i(True)
        return result

    async def _summarize_news(self, event: AstrMessageEvent, message: str) -> str:
        if not self.config.get("ai_summary_enabled", True):
            return "当前配置未启用 AI 总结。"

        try:
            item = await self._resolve_summary_item(message)
            if not item.url:
                return "未找到可用于提取全文的新闻详情链接。"

            article_text = await self.spider.fetch_article_text(item.url)
            max_chars = max(
                1000, int(self.config.get("ai_summary_max_article_chars", 12000))
            )
            if len(article_text) > max_chars:
                article_text = article_text[:max_chars] + "\n……（正文过长，已截断）"

            provider_id = await self._resolve_summary_provider_id(event)
            prompt = self._build_summary_prompt(item, article_text)
            response = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
                system_prompt="你是一个谨慎的中文新闻摘要助手，只能基于用户提供的新闻正文总结，不编造信息。",
            )
            summary = (getattr(response, "completion_text", "") or "").strip()
            if not summary:
                return "AI 总结失败：模型未返回有效内容。"

            return f"{item.title or '星痕共鸣官网新闻'}\n{item.url}\n\nAI 总结：\n{summary}"
        except Exception as e:
            logger.error(f"[星痕共鸣新闻] AI 总结失败: {type(e).__name__}: {e}")
            return f"AI 总结失败: {type(e).__name__}: {e}"

    async def _resolve_summary_item(self, message: str) -> NewsItem:
        arg = message.removeprefix(SUMMARY_COMMAND).strip()
        if not arg:
            items = await self._latest_or_cached_items()
            if not items:
                raise ValueError("暂无新闻数据可总结")
            return items[0]

        if arg.startswith("http://") or arg.startswith("https://"):
            news_id = arg.rsplit("newsid=", 1)[-1] if "newsid=" in arg else ""
            return NewsItem(idx=news_id, title="星痕共鸣官网新闻", url=arg)

        items = await self._latest_or_cached_items()
        if arg.isdigit():
            index = int(arg)
            if 1 <= index <= len(items):
                return items[index - 1]
            for item in items:
                if item.idx == arg:
                    return item
            return NewsItem(
                idx=arg,
                title=f"星痕共鸣官网新闻 {arg}",
                url=self.spider._build_detail_url(arg),
            )

        for item in items:
            if arg in item.title:
                return item
        raise ValueError(
            "未找到匹配的新闻。可发送“星痕新闻总结 1”或“星痕新闻总结 <newsid>”。"
        )

    async def _latest_or_cached_items(self) -> list[NewsItem]:
        try:
            page_size = max(5, int(self.config.get("default_query_count", 5)))
            items = await self.spider.fetch(page_size=page_size)
            self.store.update_cache(items)
            self.store.set_last_success()
            await self.store.save()
            return items
        except Exception:
            return self.store.get_cached_items()

    async def _resolve_summary_provider_id(self, event: AstrMessageEvent) -> str:
        configured = str(self.config.get("ai_summary_provider_id", "") or "").strip()
        enabled_ids = self._enabled_chat_provider_ids()
        if configured:
            if configured not in enabled_ids:
                raise ValueError(
                    f"配置的 AI 总结模型未启用或不存在: {configured}。已启用模型: {', '.join(enabled_ids) or '无'}"
                )
            return configured

        try:
            provider_id = await self.context.get_current_chat_provider_id(
                event.unified_msg_origin
            )
        except Exception:
            provider = self.context.get_using_provider(event.unified_msg_origin)
            provider_id = provider.meta().id if provider else ""
        if not provider_id:
            raise ValueError("AstrBot 当前没有可用的默认聊天模型")
        if enabled_ids and provider_id not in enabled_ids:
            raise ValueError(f"当前默认聊天模型未启用或不可用: {provider_id}")
        return provider_id

    def _enabled_chat_provider_ids(self) -> list[str]:
        ids: list[str] = []
        for provider in self.context.get_all_providers():
            try:
                provider_id = provider.meta().id
            except Exception:
                continue
            if provider_id:
                ids.append(provider_id)
        return ids

    def _enabled_summary_models_text(self, event: AstrMessageEvent) -> str:
        providers = self.context.get_all_providers()
        lines = ["星痕新闻 AI 总结可用模型（仅列出 AstrBot 已启用 Chat Provider）："]
        if not providers:
            return "当前 AstrBot 没有已启用的聊天模型，无法使用 AI 总结。"
        configured = str(self.config.get("ai_summary_provider_id", "") or "").strip()
        for provider in providers:
            meta = provider.meta()
            marker = ""
            if configured and meta.id == configured:
                marker = "（插件指定）"
            elif not configured:
                try:
                    current = self.context.get_using_provider(event.unified_msg_origin)
                    if current and current.meta().id == meta.id:
                        marker = "（当前会话默认）"
                except Exception:
                    pass
            lines.append(f"- {meta.id}: {meta.model or '未知模型'} {marker}".rstrip())
        return "\n".join(lines)

    def _build_summary_prompt(self, item: NewsItem, article_text: str) -> str:
        template = str(
            self.config.get(
                "ai_summary_prompt",
                "请用中文总结以下《星痕共鸣》官网新闻。要求：\n"
                "1. 先用一句话说明核心消息。\n"
                "2. 再列出 3 到 5 条要点。\n"
                "3. 如果是维护/活动公告，请特别提取时间、补偿、参与条件、奖励、影响范围。\n"
                "4. 不要编造正文中没有的信息。",
            )
        )
        return (
            f"{template}\n\n"
            f"新闻标题：{item.title}\n"
            f"新闻链接：{item.url}\n\n"
            f"新闻正文：\n{article_text}"
        )

    def _permission_denied(self, message: str = "权限不足。") -> str:
        if self.config.get("permission_denied_notice", True):
            return f"🚫 {message}"
        return ""

    # ── Permission helper ────────────────────────────────

    async def _is_plugin_admin(self, event: AstrMessageEvent) -> bool:
        """Check if the event sender is a plugin admin."""
        if event.is_admin():
            return True

        sender_id = str(event.get_sender_id() or "").strip()
        raw_admins = self.config.get("admin_users", []) or []
        if not isinstance(raw_admins, list):
            return False
        return sender_id in {str(x).strip() for x in raw_admins if str(x).strip()}


@filter.on_astrbot_loaded()
async def _on_loaded() -> None:
    logger.debug("[星痕共鸣新闻] AstrBot 已加载完成")
