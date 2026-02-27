# VkusVill MCP Server

MCP (Model Context Protocol) сервер для интеграции с ВкусВилл — российской сетью продуктовых магазинов.

Использует официальный MCP API ВкусВилла (`https://mcp001.vkusvill.ru/mcp`).

## Возможности

- **Поиск товаров** — поиск по ключевым словам с сортировкой и пагинацией
- **Детали товара** — состав, КБЖУ, цена, рейтинг
- **Создание корзины** — генерация ссылки для быстрого добавления товаров в корзину

## Установка

```bash
# Клонировать репозиторий
git clone <url>
cd vvmcp

# Создать виртуальное окружение
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# или .venv\Scripts\activate  # Windows

# Установить зависимости
pip install -e .
```

## Использование

### Подключение к Claude Code

Создайте файл `.mcp.json` в папке проекта:

```json
{
  "mcpServers": {
    "vkusvill": {
      "command": "/path/to/vvmcp/.venv/bin/python",
      "args": ["-m", "vvmcp.server"],
      "cwd": "/path/to/vvmcp"
    }
  }
}
```

### Подключение к Claude Desktop

Добавьте в конфигурацию (`~/.config/claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "vkusvill": {
      "command": "python",
      "args": ["-m", "vvmcp.server"],
      "cwd": "/path/to/vvmcp"
    }
  }
}
```

## Доступные инструменты

### search_products

Поиск товаров по ключевым словам.

**Параметры:**
- `query` (обязательный) — поисковый запрос
- `page` — номер страницы (по умолчанию: 1)
- `sort` — сортировка: `popular`, `rating`, `price_asc`, `price_desc`

**Пример:**
```
Найди молоко ВкусВилл 3.2%
```

### get_product_details

Получить детальную информацию о товаре (состав, КБЖУ).

**Параметры:**
- `product_id` (обязательный) — ID товара

### get_product_by_url

Получить информацию о товаре по URL.

**Параметры:**
- `url` (обязательный) — ссылка на товар

**Пример URL:** `https://vkusvill.ru/goods/moloko-3-2-1-l-173.html`

### create_cart_link

Создать ссылку на корзину с товарами.

**Параметры:**
- `items` (обязательный) — массив товаров:
  - `xml_id` — XML ID товара (из результатов поиска)
  - `quantity` — количество (по умолчанию: 1)

**Пример:**
```json
{
  "items": [
    {"xml_id": "173", "quantity": 2},
    {"xml_id": "36296", "quantity": 1}
  ]
}
```

**Возвращает:** ссылку вида `https://vkusvill.ru/?share_basket=XXXXXXXXXX`

## Архитектура

```
vvmcp/
├── src/vvmcp/
│   ├── __init__.py
│   ├── client.py      # Клиент для MCP API ВкусВилл
│   └── server.py      # MCP сервер
├── pyproject.toml
└── README.md
```

### Как это работает

1. **VkusvillClient** (`client.py`) — клиент для официального MCP API ВкусВилла:
   - Инициализирует сессию через JSON-RPC
   - Вызывает инструменты: `vkusvill_products_search`, `vkusvill_product_details`, `vkusvill_cart_link_create`

2. **MCP Server** (`server.py`) — сервер, реализующий протокол MCP для Claude

## Ограничения

- **Проверка наличия по адресу** — официальный API не предоставляет данные о наличии товара по конкретному адресу доставки. Для этого требуется отдельный сервис с Puppeteer (см. [openclaw-homebot-guide](https://github.com/artwist-polyakov/openclaw-homebot-guide)).

## Благодарности

Проект вдохновлён [openclaw-homebot-guide](https://github.com/artwist-polyakov/openclaw-homebot-guide) — руководством по развёртыванию AI-бота с интеграцией ВкусВилл.

## Лицензия

MIT
