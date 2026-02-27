"""MCP сервер для интеграции с ВкусВилл."""

import asyncio
import json
import logging
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    TextContent,
    Tool,
)

from .client import VkusvillClient, close_client, get_client

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Создаём MCP сервер
server = Server("vkusvill-mcp")


def format_product(product: dict[str, Any]) -> str:
    """Форматирование информации о товаре для вывода."""
    lines = []

    name = product.get("name") or product.get("title", "Без названия")
    # Убираем HTML entities
    name = name.replace("&nbsp;", " ")
    lines.append(f"**{name}**")

    # Цена может быть объектом {"current": 100, "old": 120, ...} или числом
    price_data = product.get("price")
    if isinstance(price_data, dict):
        if current := price_data.get("current"):
            lines.append(f"Цена: {current} ₽")
        if old := price_data.get("old"):
            lines.append(f"Старая цена: {old} ₽")
    elif price_data:
        lines.append(f"Цена: {price_data} ₽")

    # Рейтинг может быть объектом {"average": 4.9, "count": 1000} или числом
    rating_data = product.get("rating")
    if isinstance(rating_data, dict):
        if avg := rating_data.get("average"):
            count = rating_data.get("count", 0)
            lines.append(f"Рейтинг: {avg} ({count} отзывов)")
    elif rating_data:
        lines.append(f"Рейтинг: {rating_data}")

    # Вес может быть объектом {"value": 0.9, "unit": "кг"} или строкой
    weight_data = product.get("weight")
    if isinstance(weight_data, dict):
        value = weight_data.get("value", "")
        unit = weight_data.get("unit", "")
        if value:
            lines.append(f"Вес: {value} {unit}")
    elif weight_data:
        lines.append(f"Вес: {weight_data}")

    # URL может быть полным или относительным
    if url := product.get("url"):
        if url.startswith("http"):
            lines.append(f"URL: {url}")
        else:
            lines.append(f"URL: https://vkusvill.ru{url}")

    if product_id := product.get("id"):
        lines.append(f"ID: {product_id}")

    if xml_id := product.get("xml_id"):
        lines.append(f"XML ID: {xml_id}")

    return "\n".join(lines)


def format_product_details(product: dict[str, Any]) -> str:
    """Форматирование детальной информации о товаре."""
    lines = [format_product(product)]

    if description := product.get("description"):
        lines.append(f"\n**Описание:**\n{description}")

    if composition := product.get("composition"):
        lines.append(f"\n**Состав:**\n{composition}")

    # КБЖУ
    nutrition = []
    if calories := product.get("calories"):
        nutrition.append(f"Калории: {calories} ккал")
    if proteins := product.get("proteins"):
        nutrition.append(f"Белки: {proteins} г")
    if fats := product.get("fats"):
        nutrition.append(f"Жиры: {fats} г")
    if carbs := product.get("carbohydrates"):
        nutrition.append(f"Углеводы: {carbs} г")

    if nutrition:
        lines.append("\n**КБЖУ (на 100г):**")
        lines.extend(nutrition)

    if storage := product.get("storage_conditions"):
        lines.append(f"\n**Условия хранения:** {storage}")

    if shelf_life := product.get("shelf_life"):
        lines.append(f"**Срок годности:** {shelf_life}")

    return "\n".join(lines)


@server.list_tools()
async def list_tools() -> list[Tool]:
    """Список доступных инструментов."""
    return [
        Tool(
            name="search_products",
            description="Поиск товаров ВкусВилл по ключевым словам. "
            "Возвращает список товаров с ценами, рейтингами и ссылками.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Поисковый запрос (например: 'молоко', 'хлеб черный')",
                    },
                    "page": {
                        "type": "integer",
                        "description": "Номер страницы результатов (начиная с 1)",
                        "default": 1,
                    },
                    "per_page": {
                        "type": "integer",
                        "description": "Количество товаров на странице (макс. 50)",
                        "default": 10,
                    },
                    "sort": {
                        "type": "string",
                        "description": "Сортировка результатов",
                        "enum": ["popular", "rating", "price_asc", "price_desc"],
                        "default": "popular",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="get_product_details",
            description="Получить детальную информацию о товаре по ID. "
            "Включает состав, КБЖУ, условия хранения и срок годности.",
            inputSchema={
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": ["string", "integer"],
                        "description": "ID товара (число или строка)",
                    },
                },
                "required": ["product_id"],
            },
        ),
        Tool(
            name="get_product_by_url",
            description="Получить информацию о товаре по URL со страницы ВкусВилл.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL товара (например: https://vkusvill.ru/goods/moloko-12345.html)",
                    },
                },
                "required": ["url"],
            },
        ),
        Tool(
            name="create_cart_link",
            description="Создать ссылку на корзину с выбранными товарами. "
            "Пользователь может перейти по ссылке и оформить заказ.",
            inputSchema={
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "description": "Список товаров для добавления в корзину",
                        "items": {
                            "type": "object",
                            "properties": {
                                "xml_id": {
                                    "type": "string",
                                    "description": "XML ID товара (из поля xml_id в результатах поиска)",
                                },
                                "quantity": {
                                    "type": "integer",
                                    "description": "Количество единиц товара",
                                    "default": 1,
                                },
                            },
                            "required": ["xml_id"],
                        },
                    },
                },
                "required": ["items"],
            },
        ),
        Tool(
            name="get_categories",
            description="Получить список категорий товаров ВкусВилл.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="get_products_by_category",
            description="Получить товары из определённой категории.",
            inputSchema={
                "type": "object",
                "properties": {
                    "category_id": {
                        "type": ["string", "integer"],
                        "description": "ID категории",
                    },
                    "page": {
                        "type": "integer",
                        "description": "Номер страницы",
                        "default": 1,
                    },
                    "per_page": {
                        "type": "integer",
                        "description": "Количество товаров на странице",
                        "default": 10,
                    },
                },
                "required": ["category_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Обработка вызова инструмента."""
    client = get_client()

    try:
        if name == "search_products":
            result = await client.search_products(
                query=arguments["query"],
                page=arguments.get("page", 1),
                per_page=arguments.get("per_page", 10),
                sort=arguments.get("sort", "popular"),
            )

            # API возвращает данные в формате {"ok": true, "data": {"items": [...]}}
            data = result.get("data", result)
            products = data.get("items", data.get("goods", []))
            if not products:
                return [TextContent(type="text", text="Товары не найдены.")]

            output_lines = [f"Найдено товаров: {len(products)}\n"]
            for i, product in enumerate(products, 1):
                output_lines.append(f"### {i}. {format_product(product)}\n")

            return [TextContent(type="text", text="\n".join(output_lines))]

        elif name == "get_product_details":
            result = await client.get_product_details(arguments["product_id"])
            product = result.get("good", result)
            return [TextContent(type="text", text=format_product_details(product))]

        elif name == "get_product_by_url":
            result = await client.get_product_by_url(arguments["url"])
            product = result.get("good", result)
            return [TextContent(type="text", text=format_product_details(product))]

        elif name == "create_cart_link":
            cart_url = await client.create_cart_link(arguments["items"])
            return [
                TextContent(
                    type="text",
                    text=f"Ссылка на корзину:\n{cart_url}\n\n"
                    "Перейдите по ссылке, чтобы добавить товары в корзину и оформить заказ.",
                )
            ]

        elif name == "get_categories":
            result = await client.get_categories()
            categories = result.get("categories", result.get("items", []))

            if not categories:
                return [TextContent(type="text", text="Категории не найдены.")]

            lines = ["**Категории товаров:**\n"]
            for cat in categories:
                cat_id = cat.get("id")
                cat_name = cat.get("name") or cat.get("title")
                lines.append(f"- {cat_name} (ID: {cat_id})")

            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "get_products_by_category":
            result = await client.get_products_by_category(
                category_id=arguments["category_id"],
                page=arguments.get("page", 1),
                per_page=arguments.get("per_page", 10),
            )

            data = result.get("data", result)
            products = data.get("items", data.get("goods", []))
            if not products:
                return [TextContent(type="text", text="Товары в категории не найдены.")]

            output_lines = [f"Товаров в категории: {len(products)}\n"]
            for i, product in enumerate(products, 1):
                output_lines.append(f"### {i}. {format_product(product)}\n")

            return [TextContent(type="text", text="\n".join(output_lines))]

        else:
            return [TextContent(type="text", text=f"Неизвестный инструмент: {name}")]

    except Exception as e:
        logger.exception(f"Ошибка при выполнении {name}")
        return [TextContent(type="text", text=f"Ошибка: {str(e)}")]


async def run_server():
    """Запуск MCP сервера."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main():
    """Точка входа."""
    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        logger.info("Сервер остановлен")
    finally:
        asyncio.run(close_client())


if __name__ == "__main__":
    main()
