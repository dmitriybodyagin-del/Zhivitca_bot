import os
import logging
import json
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
USER_DATA_FILE = "user_data.json"

# Загрузка и сохранение данных пользователя
def load_user_data():
    try:
        with open(USER_DATA_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_user_data(user_id, data):
    all_data = load_user_data()
    all_data[str(user_id)] = data
    with open(USER_DATA_FILE, "w") as f:
        json.dump(all_data, f)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начинает диалог и спрашивает вес пользователя."""
    user_id = update.effective_user.id
    user_data = load_user_data().get(str(user_id), {})
    
    # Если у пользователя уже есть сохраненные данные, предлагаем дополнительные опции
    if user_data.get('schedule'):
        reply_keyboard = [
            ["Получить расчет"], 
            ["Скачать расписание"],
            ["Текущая доза"]
        ]
    else:
        reply_keyboard = [["Получить расчет"], ["Скачать расписание"]]

    await update.message.reply_text(
        "Привет! Я помогу рассчитать дозировку витамина.\n"
        "Выберите действие:",
        reply_markup=ReplyKeyboardMarkup(
            reply_keyboard, one_time_keyboard=True,
            input_field_placeholder="Выберите действие"
        )
    )
    return GET_WEIGHT

async def handle_current_dose(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показывает текущую дозу на основе сохраненных данных."""
    user_id = update.effective_user.id
    user_data = load_user_data().get(str(user_id), {})
    
    if not user_data.get('schedule'):
        await update.message.reply_text(
            "У вас нет сохраненного расписания. Пожалуйста, сначала получите расчет.",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END
    
    try:
        schedule = user_data['schedule']
        today = datetime.now().date()
        current_dose = None
        
        # Находим текущую дозу
        for entry in schedule:
            date = datetime.strptime(entry['date'], "%d.%m.%Y").date()
            if date <= today:
                current_dose = entry['dose']
            else:
                break
                
        if current_dose is None:
            await update.message.reply_text(
                f"Курс начнётся {user_data['start_date']}. Стартовая доза: {user_data['min_dose']} мл",
                reply_markup=ReplyKeyboardRemove()
            )
        elif datetime.strptime(user_data['end_date'], "%d.%m.%Y").date() < today:
            await update.message.reply_text(
                "Курс уже завершён.",
                reply_markup=ReplyKeyboardRemove()
            )
        else:
            await update.message.reply_text(
                f"Сегодня ({today.strftime('%d.%m.%Y')}) ваша доза: {current_dose} мл",
                reply_markup=ReplyKeyboardRemove()
            )
            
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Error in handle_current_dose: {e}")
        await update.message.reply_text(
            "Произошла ошибка при обработке вашего запроса.",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END

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
    user_id = update.effective_user.id

    if text == "Скачать расписание":
        return await handle_download(update, context)
        
    if text == "Текущая доза":
        return await handle_current_dose(update, context)

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

        context.user_data['weight'] = weight

        # Автоматический расчет минимальной дозы
        if weight < 60:
            min_dose = 0.1
        elif 60 <= weight <= 80:
            min_dose = 0.2
        else:
            min_dose = 0.4

        context.user_data['min_dose'] = min_dose

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
        user_id = update.effective_user.id
        date_str = update.message.text
        start_date = datetime.strptime(date_str, "%d.%m.%Y").date()
        today = datetime.now().date()

        weight = context.user_data['weight']
        min_dose = context.user_data['min_dose']

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
            schedule.append({
                'date': current_date.strftime('%d.%m.%Y'),
                'dose': round(current_dose, 2)
            })
            current_date += timedelta(days=1)
            current_dose += step

        schedule[-1]['dose'] = max_dose  # Коррекция максимума

        # Фаза уменьшения
        for _ in range(days_to_max):
            current_dose -= step
            schedule.append({
                'date': current_date.strftime('%d.%m.%Y'),
                'dose': round(current_dose, 2)
            })
            current_date += timedelta(days=1)

        # Сохранение данных пользователя
        user_data = {
            'weight': weight,
            'min_dose': min_dose,
            'max_dose': max_dose,
            'step': step,
            'start_date': start_date.strftime('%d.%m.%Y'),
            'end_date': end_date.strftime('%d.%m.%Y'),
            'schedule': schedule
        }
        save_user_data(user_id, user_data)

        # Определение текущего статуса
        if today < start_date:
            days_until_start = (start_date - today).days
            dose_status = (
                f"Курс начнётся через {days_until_start} дней ({start_date.strftime('%d.%m.%Y')})\n"
                f"Стартовая доза: {min_dose} мл"
            )
        elif today > end_date:
            dose_status = "Курс уже завершён"
        else:
            # Находим текущую дозу
            current_dose_value = min_dose
            for entry in schedule:
                date = datetime.strptime(entry['date'], "%d.%m.%Y").date()
                if date <= today:
                    current_dose_value = entry['dose']
                else:
                    break
            
            dose_status = f"Сегодня ({today.strftime('%d.%m.%Y')}) ваша доза: {current_dose_value} мл"

        # Формирование ответа
        msg = (
            f"Ваш вес: {weight} кг\n"
            f"Дата начала курса: {start_date.strftime('%d.%m.%Y')}\n"
            f"Дата окончания курса: {end_date.strftime('%d.%m.%Y')}\n"
            f"Шаг изменения дозы: {step} мл\n\n"
            f"{dose_status}"
        )

        await update.message.reply_text(msg)

        # Сохранение и отправка файла (даже если курс в будущем)
        filename = f"vitamin_schedule_{user_id}.txt"
        with open(filename, "w") as f:
            f.write("Дата\t\tДоза (мл)\n")
            for entry in schedule:
                f.write(f"{entry['date']}\t{entry['dose']}\n")

        await update.message.reply_document(
            document=open(filename, "rb"),
            caption="Полное расписание курса"
        )

        # Кнопки для дальнейших действий
        reply_keyboard = [
            ["Скачать расписание"],
            ["Текущая доза"]
        ]
        await update.message.reply_text(
            "Выберите действие:",
            reply_markup=ReplyKeyboardMarkup(
                reply_keyboard, 
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
