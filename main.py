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
TOKEN = os.getenv('TELEGRAM_TOKEN')
BOT_NAME = "VitaminBot"
USER_DATA_FILE = "user_data.json"

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
    """Начинает диалог с главного меню."""
    context.user_data.clear()
    
    user_id = update.effective_user.id
    user_data = load_user_data().get(str(user_id), {})
    
    buttons = [["Получить расчет"]]
    if user_data.get('schedule'):
        buttons.extend([["Скачать расписание"], ["Текущая доза"]])
    
    await update.message.reply_text(
        "Главное меню:",
        reply_markup=ReplyKeyboardMarkup(
            buttons, 
            one_time_keyboard=True,
            resize_keyboard=True,
            input_field_placeholder="Выберите действие"
        )
    )
    return GET_WEIGHT

async def handle_current_dose(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показывает текущую дозу."""
    user_id = update.effective_user.id
    user_data = context.user_data or load_user_data().get(str(user_id), {})
    
    if not user_data.get('schedule'):
        await update.message.reply_text(
            "Нет сохраненного расписания. Сначала получите расчет.",
            reply_markup=ReplyKeyboardRemove()
        )
        return await start(update, context)
    
    try:
        today = datetime.now().date()
        current_dose = None
        
        for entry in user_data['schedule']:
            date = datetime.strptime(entry['date'], "%d.%m.%Y").date()
            if date <= today:
                current_dose = entry['dose']
            else:
                break
                
        if current_dose is None:
            msg = f"Курс начнётся {user_data['start_date']}. Стартовая доза: {user_data['min_dose']} мл"
        elif datetime.strptime(user_data['end_date'], "%d.%m.%Y").date() < today:
            msg = "Курс уже завершён"
        else:
            msg = f"Сегодня ({today.strftime('%d.%m.%Y')}) доза: {current_dose} мл"
            
        await update.message.reply_text(msg)
        return await start(update, context)
        
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await update.message.reply_text("Ошибка обработки запроса")
        return await start(update, context)

async def handle_download(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отправляет файл расписания."""
    user_id = update.effective_user.id
    filename = f"vitamin_schedule_{user_id}.txt"

    try:
        await update.message.reply_document(
            document=open(filename, "rb"),
            caption="Ваше расписание",
            reply_markup=ReplyKeyboardRemove()
        )
    except FileNotFoundError:
        await update.message.reply_text("Файл не найден")
    
    return await start(update, context)

async def get_weight(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает выбор действия или ввод веса."""
    text = update.message.text

    if text == "Скачать расписание":
        return await handle_download(update, context)
    elif text == "Текущая доза":
        return await handle_current_dose(update, context)
    elif text == "Получить расчет":
        await update.message.reply_text(
            "Введите ваш вес в кг:",
            reply_markup=ReplyKeyboardRemove()
        )
        return GET_WEIGHT
    elif text == "/start":
        return await start(update, context)

    try:
        weight = float(text)
        if weight <= 0:
            raise ValueError
        
        context.user_data['weight'] = weight
        context.user_data['min_dose'] = 0.1 if weight < 60 else 0.2 if weight <= 80 else 0.4

        await update.message.reply_text(
            f"Вес: {weight} кг. Минимальная доза: {context.user_data['min_dose']} мл\n"
            "Введите дату начала курса (ДД.ММ.ГГГГ):"
        )
        return GET_START_DATE
    except ValueError:
        await update.message.reply_text("Введите корректный вес (число > 0)")
        return GET_WEIGHT

async def get_start_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает ввод даты и выдает результат."""
    try:
        start_date = datetime.strptime(update.message.text, "%d.%m.%Y").date()
        today = datetime.now().date()
        
        weight = context.user_data['weight']
        min_dose = context.user_data['min_dose']
        max_dose, step = (4.0, 0.1) if weight < 60 else (7.0, 0.2) if weight <= 80 else (8.0, 0.4)

        # Расчет расписания
        days_to_max = int((max_dose - min_dose) / step)
        schedule = []
        current_date = start_date
        current_dose = min_dose

        # Фаза увеличения
        for _ in range(days_to_max + 1):
            schedule.append({'date': current_date.strftime('%d.%m.%Y'), 'dose': round(current_dose, 2)})
            current_date += timedelta(days=1)
            current_dose += step
        schedule[-1]['dose'] = max_dose

        # Фаза уменьшения
        for _ in range(days_to_max):
            current_dose -= step
            schedule.append({'date': current_date.strftime('%d.%m.%Y'), 'dose': round(current_dose, 2)})
            current_date += timedelta(days=1)

        # Сохранение данных
        user_data = {
            'weight': weight,
            'min_dose': min_dose,
            'max_dose': max_dose,
            'step': step,
            'start_date': start_date.strftime('%d.%m.%Y'),
            'end_date': (start_date + timedelta(days=days_to_max*2)).strftime('%d.%m.%Y'),
            'schedule': schedule
        }
        save_user_data(update.effective_user.id, user_data)
        context.user_data.update(user_data)

        # Формирование ответа
        if today < start_date:
            status = f"Курс начнётся через {(start_date - today).days} дней"
        elif today > datetime.strptime(user_data['end_date'], "%d.%m.%Y").date():
            status = "Курс завершён"
        else:
            #current = next((x for x in schedule if datetime.strptime(x['date'], "%d.%m.%Y").date() <= today), None)
            status = f"{current_dose} мл"

        await update.message.reply_text(
            f"Даты: {user_data['start_date']} - {user_data['end_date']}\n"
            f"Шаг: {step} мл"
        )

        # Отправка файла
        filename = f"vitamin_schedule_{update.effective_user.id}.txt"
        with open(filename, "w") as f:
            f.write("Дата\tДоза\n" + "\n".join(f"{x['date']}\t{x['dose']}" for x in schedule))
        
        await update.message.reply_document(open(filename, "rb"))
        return await start(update, context)

    except ValueError:
        await update.message.reply_text("Неверный формат даты! Используйте ДД.ММ.ГГГГ")
        return GET_START_DATE

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Альтернативный способ вернуться в меню."""
    return await start(update, context)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Ошибка: {context.error}")

def main():
    app = Application.builder().token(TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            GET_WEIGHT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_weight),
                CommandHandler('start', start)
            ],
            GET_START_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_start_date),
                CommandHandler('start', start)
            ],
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            CommandHandler('start', start)
        ],
        allow_reentry=True
    )
    
    app.add_handler(conv_handler)
    app.add_error_handler(error_handler)
    app.run_polling()

if __name__ == '__main__':
    main()
