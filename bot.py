import os
import logging
import base64
from io import BytesIO
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from openai import OpenAI

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ZAI_API_KEY = os.getenv("ZAI_API_KEY")

client = OpenAI(
    api_key=ZAI_API_KEY,
    base_url="https://api.z.ai/api/paas/v4/"  # или https://open.bigmodel.cn/api/paas/v4/
)

# История диалога
user_histories: dict[int, list] = {}

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def get_or_create_history(user_id: int) -> list:
    if user_id not in user_histories:
        user_histories[user_id] = [
            {
                "role": "system",
                "content": "Ты полезный, вежливый и точный ассистент. Отвечай на языке пользователя. Если пользователь присылает изображение, внимательно его анализируй."
            }
        ]
    return user_histories[user_id]


def trim_history(history: list, max_messages: int = 20) -> list:
    """Оставляет system + последние max_messages сообщений."""
    if len(history) <= max_messages + 1:
        return history
    return [history[0]] + history[-(max_messages):]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_histories[user_id] = [
        {
            "role": "system",
            "content": "Ты полезный, вежливый и точный ассистент. Отвечай на языке пользователя. Если пользователь присылает изображение, внимательно его анализируй."
        }
    ]
    await update.message.reply_text(
        "Привет! Я бот на базе **GLM-5.3-Flash**.\n\n"
        "• Пишите текстом — отвечу\n"
        "• Отправляйте фото (с подписью или без) — проанализирую\n"
        "• /clear — очистить историю диалога"
    )


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_histories[user_id] = [
        {
            "role": "system",
            "content": "Ты полезный, вежливый и точный ассистент. Отвечай на языке пользователя. Если пользователь присылает изображение, внимательно его анализируй."
        }
    ]
    await update.message.reply_text("История диалога очищена.")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_text = update.message.text

    history = get_or_create_history(user_id)
    history.append({"role": "user", "content": user_text})
    history = trim_history(history)
    user_histories[user_id] = history

    await generate_and_reply(update, context, history)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    message = update.message

    # Берём фото наибольшего разрешения
    photo = message.photo[-1]
    file = await context.bot.get_file(photo.file_id)

    # Скачиваем в память
    bio = BytesIO()
    await file.download_to_memory(bio)
    bio.seek(0)
    image_bytes = bio.read()

    # Кодируем в base64
    b64_image = base64.b64encode(image_bytes).decode("utf-8")
    data_url = f"data:image/jpeg;base64,{b64_image}"

    # Текст подписи (если есть)
    caption = message.caption or "Опиши, что изображено на фото, и ответь на вопрос, если он есть."

    # Формируем multimodal-сообщение
    content = [
        {"type": "text", "text": caption},
        {
            "type": "image_url",
            "image_url": {
                "url": data_url
            }
        }
    ]

    history = get_or_create_history(user_id)
    history.append({"role": "user", "content": content})
    history = trim_history(history)
    user_histories[user_id] = history

    await generate_and_reply(update, context, history)


async def generate_and_reply(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    history: list
) -> None:
    try:
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action="typing"
        )

        response = client.chat.completions.create(
            model="glm-5.3-flash",
            messages=history,
            temperature=0.7,
            max_tokens=4096,
        )

        assistant_reply = response.choices[0].message.content

        # Добавляем ответ модели в историю
        user_id = update.effective_user.id
        user_histories[user_id].append(
            {"role": "assistant", "content": assistant_reply}
        )

        await update.message.reply_text(assistant_reply)

    except Exception as e:
        logger.error(f"Ошибка при обращении к API: {e}", exc_info=True)
        await update.message.reply_text(
            "Произошла ошибка при обработке запроса. "
            "Проверьте API-ключ и попробуйте позже."
        )


def main() -> None:
    if not TELEGRAM_TOKEN or not ZAI_API_KEY:
        raise ValueError("Укажите TELEGRAM_TOKEN и ZAI_API_KEY в файле .env")

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("clear", clear))
    application.add_handler(MessageHandler(filters.TEXT & \~filters.COMMAND, handle_text))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    logger.info("Бот запущен (с поддержкой фото)...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
