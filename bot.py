import os
import logging
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters
)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Константы
GET_WEIGHT, GET_START_DATE = range(2)
TOKEN = os.getenv('TELEGRAM_TOKEN')  # Токен через переменные окружения
BOT_NAME = "VitaminBot"

# Глобальные переменные для хранения данных пользователя
user_data = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начинает диалог и спрашивает вес пользователя."""
    reply_keyboard = [["Получить расчет"], ["Скачать расписание"]]

    await update.message.reply_text(
        "Привет! Я помогу рассчитать дозировку.\n"
        "Выберите действие:",
        reply_markup=ReplyKeyboardMarkup(
            reply_keyboard, one_time_keyboard=True,
            input_field_placeholder="Выберите действие"
        )
    )
    return GET_WEIGHT

async def handle_download(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает запрос на скачивание расписания."""
    user_id = update.effective_user.id
    filename = f"vitamin_schedule_{user_id}.txt"

    try:
        await update.message.reply_document(
            document=open(filename, "rb"),
            caption="Ваше расписание курса витамина",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END
    except FileNotFoundError:
        await update.message.reply_text(
            "Расписание не найдено. Пожалуйста, сначала получите расчет.",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END

async def get_weight(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает ввод веса или выбор действия."""
    text = update.message.text

    if text == "Скачать расписание":
        return await handle_download(update, context)

    if text == "Получить расчет":
        await update.message.reply_text(
            "Пожалуйста, введите ваш вес в кг:",
            reply_markup=ReplyKeyboardRemove()
        )
        return GET_WEIGHT

    try:
        weight = float(text)
        if weight <= 0:
            raise ValueError("Вес должен быть положительным числом")

        user_data['weight'] = weight

        # Автоматический расчет минимальной дозы
        if weight < 60:
            min_dose = 0.1
        elif 60 <= weight <= 80:
            min_dose = 0.2
        else:
            min_dose = 0.4

        user_data['min_dose'] = min_dose

        await update.message.reply_text(
            f"Ваш вес: {weight} кг.\n"
            f"Минимальная дозировка: {min_dose} мл.\n"
            "Введите дату начала курса (ДД.ММ.ГГГГ):",
            reply_markup=ReplyKeyboardRemove()
        )
        return GET_START_DATE
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите корректное число для веса.")
        return GET_WEIGHT

async def get_start_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Рассчитывает расписание и отправляет результат."""
    try:
        date_str = update.message.text
        start_date = datetime.strptime(date_str, "%d.%m.%Y").date()
        today = datetime.now().date()

        if start_date > today:
            await update.message.reply_text("Дата начала не может быть в будущем!")
            return GET_START_DATE

        weight = user_data['weight']
        min_dose = user_data['min_dose']

        # Параметры курса
        if weight < 60:
            max_dose, step = 4.0, 0.1
        elif 60 <= weight <= 80:
            max_dose, step = 7.0, 0.2
        else:
            max_dose, step = 8.0, 0.4

        days_to_max = int((max_dose - min_dose) / step)
        total_days = days_to_max * 2
        end_date = start_date + timedelta(days=total_days)

        # Генерация расписания
        schedule = []
        current_date = start_date
        current_dose = min_dose

        # Фаза увеличения
        for _ in range(days_to_max + 1):
            schedule.append((current_date, round(current_dose, 2)))
            current_date += timedelta(days=1)
            current_dose += step

        schedule[-1] = (schedule[-1][0], max_dose)  # Коррекция максимума

        # Фаза уменьшения
        for _ in range(days_to_max):
            current_dose -= step
            schedule.append((current_date, round(current_dose, 2)))
            current_date += timedelta(days=1)

        # Текущая доза
        current_dose_info = next(
            ((date, dose) for date, dose in schedule if date <= today),
            None
        )

        # Формирование ответа
        if current_dose_info:
            msg = (
                f"На {today.strftime('%d.%m.%Y')} дозировка: {current_dose_info[1]} мл\n"
                f"Курс: {start_date.strftime('%d.%m.%Y')} → {end_date.strftime('%d.%m.%Y')}\n"
                f"Доза: {min_dose} → {max_dose} (шаг: {step} мл)"
            )
        else:
            msg = f"Курс начнется {start_date.strftime('%d.%m.%Y')}. Стартовая доза: {min_dose} мл"

        await update.message.reply_text(msg)

        # Сохранение и отправка файла
        filename = f"vitamin_schedule_{update.effective_user.id}.txt"
        with open(filename, "w") as f:
            f.write("Дата\t\tДоза (мл)\n")
            for date, dose in schedule:
                f.write(f"{date.strftime('%d.%m.%Y')}\t{dose}\n")

        await update.message.reply_document(
            document=open(filename, "rb"),
            caption="Полное расписание"
        )

        # Кнопка для повторного скачивания
        await update.message.reply_text(
            "Скачать расписание снова:",
            reply_markup=ReplyKeyboardMarkup(
                [["Скачать расписание"]], 
                one_time_keyboard=True
            )
        )

        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text("Неверный формат даты! Используйте ДД.ММ.ГГГГ")
        return GET_START_DATE

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отменяет диалог."""
    await update.message.reply_text(
        "Диалог отменен.",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Логирует ошибки."""
    logger.error(f"Ошибка: {context.error}")

def main():
    """Запуск бота."""
    app = Application.builder().token(TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            GET_WEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_weight)],
            GET_START_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_start_date)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    app.add_handler(conv_handler)
    app.add_error_handler(error_handler)
    
    logger.info("Бот запущен")
    app.run_polling()

if __name__ == '__main__':
    main()
