"""Клиент для работы с официальным MCP API ВкусВилл."""

import re
from typing import Any

import httpx

VKUSVILL_MCP_URL = "https://mcp001.vkusvill.ru/mcp"
VKUSVILL_WEB_BASE = "https://vkusvill.ru"


class VkusvillClient:
    """Клиент для работы с MCP API ВкусВилл."""

    def __init__(self, timeout: float = 30.0):
        self.mcp_url = VKUSVILL_MCP_URL
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._session_id: str | None = None
        self._initialized: bool = False

    async def _get_client(self) -> httpx.AsyncClient:
        """Получить или создать HTTP клиент."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self) -> None:
        """Закрыть HTTP клиент."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
        self._session_id = None
        self._initialized = False

    async def _init_session(self) -> bool:
        """Инициализировать MCP сессию."""
        client = await self._get_client()

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }

        init_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "vvmcp-client", "version": "1.0"},
            },
        }

        response = await client.post(self.mcp_url, json=init_payload, headers=headers)

        # Сервер должен ответить корректным JSON-RPC результатом инициализации
        try:
            init_result = response.json()
        except ValueError:
            return False
        if "error" in init_result or "result" not in init_result:
            return False

        # Session ID опционален: официальный API ВкусВилл работает без него (stateless).
        # Если заголовок есть — сохраняем и передаём в последующих запросах.
        session_id = response.headers.get("mcp-session-id")
        if not session_id:
            for key, value in response.headers.items():
                if key.lower() == "mcp-session-id":
                    session_id = value
                    break
        self._session_id = session_id or None

        # Отправляем уведомление об инициализации
        notify_payload = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        await client.post(self.mcp_url, json=notify_payload, headers=headers)

        self._initialized = True
        return True

    async def _call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Вызвать инструмент MCP API."""
        # Инициализируем сессию если нужно
        if not self._initialized:
            if not await self._init_session():
                raise RuntimeError("Не удалось инициализировать MCP сессию")

        client = await self._get_client()

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        payload = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }

        response = await client.post(self.mcp_url, json=payload, headers=headers)
        result = response.json()

        # Проверяем на ошибки
        if "error" in result:
            error = result["error"]
            raise RuntimeError(f"MCP ошибка: {error.get('message', error)}")

        return result.get("result", result)

    async def _call_tool_with_retry(
        self, tool_name: str, arguments: dict[str, Any], max_retries: int = 1
    ) -> dict[str, Any]:
        """Вызвать инструмент с повторной попыткой при ошибке."""
        import asyncio

        last_error = None

        for attempt in range(max_retries + 1):
            try:
                if attempt > 0:
                    # Сбрасываем сессию перед повторной попыткой
                    self._session_id = None
                    self._initialized = False
                    await asyncio.sleep(2)

                return await self._call_tool(tool_name, arguments)

            except Exception as e:
                last_error = e

        raise last_error or RuntimeError("MCP запрос не удался")

    async def search_products(
        self,
        query: str,
        page: int = 1,
        per_page: int = 10,
        sort: str = "popular",
    ) -> dict[str, Any]:
        """
        Поиск товаров по запросу.

        Args:
            query: Поисковый запрос
            page: Номер страницы (начиная с 1)
            per_page: Количество товаров на странице
            sort: Сортировка (popular, rating, price_asc, price_desc)

        Returns:
            Результаты поиска с товарами
        """
        # Маппинг сортировки на формат API
        sort_map = {
            "popular": "popularity",
            "rating": "rating",
            "price_asc": "price",
            "price_desc": "price_desc",
        }

        result = await self._call_tool_with_retry(
            "vkusvill_products_search",
            {
                "q": query,
                "page": page,
                "sort": sort_map.get(sort, "popularity"),
            },
        )

        parsed = self._parse_mcp_result(result)
        self._raise_if_api_error(parsed)
        return parsed

    def _raise_if_api_error(self, parsed: dict[str, Any]) -> None:
        """Поднять понятную ошибку, если API вернул бизнес-ошибку ({"ok": false}).

        Официальный API оборачивает ошибки внутрь текстового content с полем
        ``ok: false`` (например rate limit / 429), а на уровне MCP при этом
        ``isError`` = false. Без этой проверки сервер молча отдаёт «не найдено».
        """
        if isinstance(parsed, dict) and parsed.get("ok") is False:
            err = parsed.get("error") or {}
            msg = err.get("message") or parsed.get("code") or "неизвестная ошибка API"
            status = err.get("http_status")
            suffix = f" (HTTP {status})" if status else ""
            raise RuntimeError(f"API ВкусВилл: {msg}{suffix}")

    def _parse_mcp_result(self, result: dict[str, Any]) -> dict[str, Any]:
        """Парсинг результата MCP в унифицированный формат."""
        if "content" in result:
            content = result["content"]
            if isinstance(content, list) and len(content) > 0:
                text = content[0].get("text", "")
                # Пробуем распарсить как JSON
                try:
                    import json
                    return json.loads(text)
                except (json.JSONDecodeError, TypeError):
                    return {"text": text}
        return result

    async def get_product_details(self, product_id: int | str) -> dict[str, Any]:
        """
        Получить детальную информацию о товаре.

        Args:
            product_id: ID товара

        Returns:
            Детальная информация о товаре (состав, КБЖУ, цена и т.д.)
        """
        # Преобразуем в int если строка
        if isinstance(product_id, str):
            product_id = int(product_id)

        result = await self._call_tool_with_retry(
            "vkusvill_product_details",
            {"id": product_id},
        )

        parsed = self._parse_mcp_result(result)
        self._raise_if_api_error(parsed)
        return parsed

    async def get_product_by_url(self, url: str) -> dict[str, Any]:
        """
        Получить информацию о товаре по URL.

        Args:
            url: URL товара на сайте ВкусВилл

        Returns:
            Информация о товаре
        """
        # Извлекаем ID товара из URL
        # Формат: https://vkusvill.ru/goods/moloko-vkusvill-12345.html
        match = re.search(r"-(\d+)\.html", url)
        if not match:
            # Альтернативный формат: /goods/xmlid/12345
            match = re.search(r"/goods/(?:xmlid/)?(\d+)", url)

        if not match:
            raise ValueError(f"Не удалось извлечь ID товара из URL: {url}")

        product_id = int(match.group(1))
        return await self.get_product_details(product_id)

    async def create_cart_link(self, items: list[dict[str, Any]]) -> str:
        """
        Создать ссылку на корзину с товарами.

        Args:
            items: Список товаров в формате [{"xml_id": "...", "quantity": N}, ...]

        Returns:
            URL для добавления товаров в корзину
        """
        # Преобразуем формат для API: {"xml_id": int, "q": float}
        products = []
        for item in items:
            product_id = item.get("xml_id") or item.get("id")
            quantity = item.get("quantity", 1)
            products.append({"xml_id": int(product_id), "q": float(quantity)})

        result = await self._call_tool_with_retry(
            "vkusvill_cart_link_create",
            {"products": products},
        )

        # Извлекаем URL из результата
        parsed = self._parse_mcp_result(result)
        self._raise_if_api_error(parsed)

        if isinstance(parsed, dict):
            # Пробуем разные варианты структуры ответа
            if "url" in parsed:
                return parsed["url"]
            if "link" in parsed:
                return parsed["link"]
            if "text" in parsed:
                text = parsed["text"]
                # URL может быть в тексте
                if "vkusvill.ru" in text:
                    match = re.search(r'https?://[^\s<>"]+', text)
                    if match:
                        return match.group(0)
                return text

        return str(parsed)

    async def get_categories(self) -> dict[str, Any]:
        """
        Получить список категорий товаров.

        Returns:
            Список категорий
        """
        # MCP API может не иметь этого метода
        return {"categories": []}

    async def get_products_by_category(
        self,
        category_id: int | str,
        page: int = 1,
        per_page: int = 10,
    ) -> dict[str, Any]:
        """
        Получить товары из категории.

        Args:
            category_id: ID категории
            page: Номер страницы
            per_page: Количество товаров на странице

        Returns:
            Товары из категории
        """
        # Используем поиск по категории как запрос
        return await self.search_products(str(category_id), page, per_page)


# Синглтон клиента
_client: VkusvillClient | None = None


def get_client() -> VkusvillClient:
    """Получить глобальный экземпляр клиента."""
    global _client
    if _client is None:
        _client = VkusvillClient()
    return _client


async def close_client() -> None:
    """Закрыть глобальный клиент."""
    global _client
    if _client is not None:
        await _client.close()
        _client = None
