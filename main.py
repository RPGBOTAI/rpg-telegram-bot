import os
import json
import asyncio
import logging
from typing import Dict, Any

import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from openai import OpenAI

# Налаштування логування
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфігурація - читаємо змінні середовища напряму
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
GOOGLE_SCRIPT_URL = os.environ.get('GOOGLE_SCRIPT_URL')

# Перевіряємо що всі змінні налаштовані
if not TELEGRAM_BOT_TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN не налаштований!")
    exit(1)

if not OPENAI_API_KEY:
    logger.error("OPENAI_API_KEY не налаштований!")
    exit(1)
    
if not GOOGLE_SCRIPT_URL:
    logger.error("GOOGLE_SCRIPT_URL не налаштований!")
    exit(1)

# Ініціалізація OpenAI клієнта
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Класи персонажів
CLASSES = {
    'knight': '🛡️ Лицар',
    'mage': '🧙‍♂️ Маг', 
    'archer': '🏹 Лучник',
    'thief': '🗡️ Злодій',
    'cleric': '⚕️ Жрець'
}

class GoogleSheetsAPI:
    """Клас для роботи з Google Sheets через Apps Script"""
    
    @staticmethod
    def make_request(data: Dict[str, Any]) -> Dict[str, Any]:
        """Відправляє запит до Google Apps Script"""
        try:
            response = requests.post(
                GOOGLE_SCRIPT_URL,
                json=data,
                headers={'Content-Type': 'application/json'},
                timeout=30
            )
            return response.json()
        except Exception as e:
            logger.error(f"Помилка запиту до Google Sheets: {e}")
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def get_player(user_id: int) -> Dict[str, Any]:
        """Отримує дані гравця"""
        return GoogleSheetsAPI.make_request({
            "action": "get_player",
            "user_id": str(user_id)
        })
    
    @staticmethod
    def create_player(user_id: int, name: str, player_class: str) -> Dict[str, Any]:
        """Створює нового гравця"""
        return GoogleSheetsAPI.make_request({
            "action": "create_player",
            "user_id": str(user_id),
            "name": name,
            "class": player_class
        })
    
    @staticmethod
    def update_hp(user_id: int, hp: int) -> Dict[str, Any]:
        """Оновлює HP гравця"""
        return GoogleSheetsAPI.make_request({
            "action": "update_hp",
            "user_id": str(user_id),
            "hp_current": hp
        })

class RPGGameLogic:
    """Клас для ігрової логіки"""
    
    @staticmethod
    def get_gpt_response(prompt: str, player_data: Dict) -> Dict[str, Any]:
        """Отримує відповідь від GPT з ігровою логікою"""
        
        system_prompt = f"""
        Ти - майстер гри D&D. Гравець:
        - Ім'я: {player_data.get('name')}
        - Клас: {player_data.get('class')} 
        - Рівень: {player_data.get('level')}
        - HP: {player_data.get('hp_current')}/{player_data.get('hp_max')}
        - Характеристики: STR:{player_data.get('str')} DEX:{player_data.get('dex')} CON:{player_data.get('con')} INT:{player_data.get('int')} WIS:{player_data.get('wis')} CHA:{player_data.get('cha')}
        - Інвентар: {player_data.get('inventory')}
        
        ЗАВЖДИ відповідай в JSON форматі:
        {{
            "main_response": "Основна відповідь для гравця",
            "dice_required": {{
                "type": "d20",
                "modifier": "+STR",
                "difficulty": 15
            }},
            "hint": "Коротка підказка (1-2 речення) про можливості класу",
            "damage": 0,
            "xp_reward": 0
        }}
        
        Дій гравця: {prompt}
        """
        
        try:
            response = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=500,
                temperature=0.7
            )
            
            # Парсимо JSON відповідь
            content = response.choices[0].message.content
            return json.loads(content)
            
        except Exception as e:
            logger.error(f"Помилка GPT: {e}")
            return {
                "main_response": "Щось пішло не так з магією...",
                "dice_required": None,
                "hint": "Спробуй ще раз!",
                "damage": 0,
                "xp_reward": 0
            }

# Обробники команд
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    user_id = update.effective_user.id
    
    # Перевіряємо чи гравець вже існує
    player_data = GoogleSheetsAPI.get_player(user_id)
    
    if player_data["success"]:
        player = player_data["player"]
        await update.message.reply_text(
            f"🎮 Вітаю знову, {player['name']}!\n"
            f"🛡️ Клас: {CLASSES.get(player['class'], player['class'])}\n"
            f"❤️ HP: {player['hp_current']}/{player['hp_max']}\n"
            f"⭐ Рівень: {player['level']}\n\n"
            f"Готовий до пригод? Напиши що хочеш зробити!"
        )
    else:
        # Показуємо кнопки вибору класу
        keyboard = []
        for class_key, class_name in CLASSES.items():
            keyboard.append([InlineKeyboardButton(class_name, callback_data=f"class_{class_key}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "🏰 Ласкаво просимо до RPG пригоди!\n\n"
            "Оберіть клас свого персонажа:",
            reply_markup=reply_markup
        )

async def handle_class_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробка вибору класу"""
    query = update.callback_query
    await query.answer()
    
    class_chosen = query.data.replace("class_", "")
    user_id = query.from_user.id
    user_name = query.from_user.first_name or "Герой"
    
    # Створюємо гравця
    result = GoogleSheetsAPI.create_player(user_id, user_name, class_chosen)
    
    if result["success"]:
        await query.edit_message_text(
            f"🎉 Персонаж створено!\n\n"
            f"👤 Ім'я: {user_name}\n"
            f"🛡️ Клас: {CLASSES[class_chosen]}\n\n"
            f"Ваша пригода починається! Напишіть що хочете зробити."
        )
    else:
        await query.edit_message_text(
            f"❌ Помилка створення персонажа: {result.get('error', 'Невідома помилка')}"
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробка звичайних повідомлень від гравців"""
    user_id = update.effective_user.id
    user_message = update.message.text
    
    # Отримуємо дані гравця
    player_data = GoogleSheetsAPI.get_player(user_id)
    
    if not player_data["success"]:
        await update.message.reply_text(
            "❌ Спочатку створіть персонажа командою /start"
        )
        return
    
    player = player_data["player"]
    
    # Отримуємо відповідь від GPT
    gpt_response = RPGGameLogic.get_gpt_response(user_message, player)
    
    # Формуємо кнопки
    keyboard = []
    
    # Кнопка кубика якщо потрібна
    if gpt_response.get("dice_required"):
        dice_info = gpt_response["dice_required"]
        dice_text = f"🎲 {dice_info['type']} {dice_info.get('modifier', '')}"
        keyboard.append([InlineKeyboardButton(dice_text, callback_data="roll_dice")])
    
    # Кнопка підказки (завжди)
    keyboard.append([InlineKeyboardButton("💡 Підказка", callback_data="show_hint")])
    
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    
    # Зберігаємо контекст для кнопок
    context.user_data['last_gpt_response'] = gpt_response
    context.user_data['player_data'] = player
    
    await update.message.reply_text(
        gpt_response["main_response"],
        reply_markup=reply_markup
    )

async def handle_button_press(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробка натискання кнопок"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "show_hint":
        gpt_response = context.user_data.get('last_gpt_response', {})
        hint = gpt_response.get('hint', 'Підказка недоступна')
        await query.edit_message_text(
            f"💡 {hint}\n\n"
            f"Що робити далі?"
        )
    
    elif query.data == "roll_dice":
        # Тут буде логіка кидання кубика
        await query.edit_message_text("🎲 Кидаємо кубик... (поки що в розробці)")

def main():
    """Головна функція"""
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Додаємо обробники
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(handle_class_selection, pattern="^class_"))
    application.add_handler(CallbackQueryHandler(handle_button_press, pattern="^(show_hint|roll_dice)$"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Запускаємо бота
    logger.info("Бот запущений!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
