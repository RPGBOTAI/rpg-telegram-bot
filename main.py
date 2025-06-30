import os
import json
import asyncio
import logging
import random
from typing import Dict, Any, List, Optional
from datetime import datetime

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
    'knight': {
        'name': '🛡️ Лицар',
        'stats': {'str': 15, 'dex': 10, 'con': 14, 'int': 8, 'wis': 12, 'cha': 13},
        'hp_base': 15,
        'mp_base': 0,
        'equipment': ['sword', 'shield', 'chainmail'],
        'gold': 50,
        'abilities': ['mighty_strike', 'protect_ally']
    },
    'mage': {
        'name': '🧙‍♂️ Маг',
        'stats': {'str': 8, 'dex': 12, 'con': 10, 'int': 15, 'wis': 14, 'cha': 11},
        'hp_base': 8,
        'mp_base': 10,
        'equipment': ['staff', 'robe', 'spellbook'],
        'gold': 30,
        'abilities': ['magic_missile', 'fireball', 'heal']
    },
    'archer': {
        'name': '🏹 Лучник',
        'stats': {'str': 12, 'dex': 15, 'con': 13, 'int': 10, 'wis': 14, 'cha': 8},
        'hp_base': 12,
        'mp_base': 0,
        'equipment': ['bow', 'arrows:30', 'leather_armor'],
        'gold': 40,
        'abilities': ['precise_shot', 'multi_shot']
    },
    'thief': {
        'name': '🗡️ Злодій',
        'stats': {'str': 10, 'dex': 15, 'con': 12, 'int': 13, 'wis': 11, 'cha': 14},
        'hp_base': 10,
        'mp_base': 0,
        'equipment': ['dagger', 'dagger', 'thieves_tools', 'dark_cloak'],
        'gold': 60,
        'abilities': ['backstab', 'stealth']
    },
    'cleric': {
        'name': '⚕️ Жрець',
        'stats': {'str': 11, 'dex': 10, 'con': 13, 'int': 12, 'wis': 15, 'cha': 14},
        'hp_base': 12,
        'mp_base': 8,
        'equipment': ['mace', 'holy_symbol', 'healing_potion:2'],
        'gold': 35,
        'abilities': ['mass_heal', 'turn_undead']
    }
}

# Предмети та їх характеристики
ITEMS = {
    'sword': {'name': 'Меч', 'damage': 'd8', 'type': 'weapon', 'price': 50},
    'dagger': {'name': 'Кинджал', 'damage': 'd4', 'type': 'weapon', 'price': 10},
    'bow': {'name': 'Лук', 'damage': 'd8', 'type': 'ranged', 'price': 40},
    'staff': {'name': 'Посох', 'damage': 'd6', 'type': 'weapon', 'price': 25},
    'mace': {'name': 'Булава', 'damage': 'd6', 'type': 'weapon', 'price': 30},
    'shield': {'name': 'Щит', 'defense': 2, 'type': 'armor', 'price': 25},
    'chainmail': {'name': 'Кольчуга', 'defense': 3, 'type': 'armor', 'price': 100},
    'leather_armor': {'name': 'Шкіряна броня', 'defense': 2, 'type': 'armor', 'price': 30},
    'robe': {'name': 'Мантія', 'defense': 1, 'type': 'armor', 'price': 20},
    'healing_potion': {'name': 'Зілля лікування', 'heal': 'd6+1', 'type': 'consumable', 'price': 20}
}

# Спеціальні здібності
ABILITIES = {
    'mighty_strike': {'name': 'Могутній удар', 'uses_per_battle': 1, 'effect': 'double_damage'},
    'protect_ally': {'name': 'Захист союзника', 'uses_per_battle': 1, 'effect': 'redirect_damage'},
    'magic_missile': {'name': 'Магічна стріла', 'mp_cost': 2, 'damage': 'd4+INT', 'auto_hit': True},
    'fireball': {'name': 'Вогняна куля', 'mp_cost': 4, 'damage': 'd8+INT', 'area': True},
    'heal': {'name': 'Лікування', 'mp_cost': 2, 'heal': 'd6+WIS'},
    'precise_shot': {'name': 'Точний постріл', 'uses_per_battle': 1, 'effect': '+5_attack'},
    'multi_shot': {'name': 'Багатократний постріл', 'uses_per_battle': 1, 'effect': '3_arrows'},
    'backstab': {'name': 'Удар зі спини', 'uses_per_battle': 1, 'damage': '+d6'},
    'stealth': {'name': 'Скрадання', 'uses_per_battle': 1, 'effect': 'advantage'},
    'mass_heal': {'name': 'Масове лікування', 'uses_per_day': 1, 'heal': 'd6_all'},
    'turn_undead': {'name': 'Вигнання нежиті', 'uses_per_battle': 1, 'effect': 'fear_undead'}
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
        class_data = CLASSES[player_class]
        return GoogleSheetsAPI.make_request({
            "action": "create_player",
            "user_id": str(user_id),
            "name": name,
            "class": player_class,
            "level": 1,
            "hp_current": class_data['hp_base'],
            "hp_max": class_data['hp_base'],
            "mp_current": class_data['mp_base'],
            "mp_max": class_data['mp_base'],
            "str": class_data['stats']['str'],
            "dex": class_data['stats']['dex'],
            "con": class_data['stats']['con'],
            "int": class_data['stats']['int'],
            "wis": class_data['stats']['wis'],
            "cha": class_data['stats']['cha'],
            "xp": 0,
            "gold": class_data['gold'],
            "inventory": ','.join(class_data['equipment'])
        })
    
    @staticmethod
    def update_player(user_id: int, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Оновлює дані гравця"""
        data = {
            "action": "update_player",
            "user_id": str(user_id)
        }
        data.update(updates)
        return GoogleSheetsAPI.make_request(data)
    
    @staticmethod
    def get_ability_usage(user_id: int, ability: str) -> Dict[str, Any]:
        """Перевіряє чи використовувалася здібність"""
        return GoogleSheetsAPI.make_request({
            "action": "get_ability",
            "user_id": str(user_id),
            "ability_name": ability
        })
    
    @staticmethod
    def use_ability(user_id: int, ability: str) -> Dict[str, Any]:
        """Позначає здібність як використану"""
        return GoogleSheetsAPI.make_request({
            "action": "use_ability",
            "user_id": str(user_id),
            "ability_name": ability,
            "used": True
        })

class DiceRoller:
    """Клас для кидання кубиків"""
    
    @staticmethod
    def roll(dice_str: str) -> int:
        """Кидає кубик по строці типу 'd20', '2d6', 'd8+3'"""
        try:
            # Парсимо строку кубика
            if '+' in dice_str:
                dice_part, bonus = dice_str.split('+')
                bonus = int(bonus)
            elif '-' in dice_str:
                dice_part, penalty = dice_str.split('-')
                bonus = -int(penalty)
            else:
                dice_part = dice_str
                bonus = 0
            
            if 'd' in dice_part:
                if dice_part.startswith('d'):
                    count = 1
                    sides = int(dice_part[1:])
                else:
                    count, sides = dice_part.split('d')
                    count = int(count)
                    sides = int(sides)
            else:
                # Просто число
                return int(dice_part) + bonus
            
            total = sum(random.randint(1, sides) for _ in range(count))
            return total + bonus
            
        except Exception as e:
            logger.error(f"Помилка при кидку кубика {dice_str}: {e}")
            return 1

    @staticmethod
    def get_modifier(stat_value: int) -> int:
        """Обчислює модифікатор характеристики"""
        return (stat_value - 10) // 2

class RPGGameLogic:
    """Клас для ігрової логіки"""
    
    @staticmethod
    def get_gpt_response(prompt: str, player_data: Dict, context: str = "") -> Dict[str, Any]:
        """Отримує відповідь від GPT з ігровою логікою"""
        
        # Формуємо характеристики з модифікаторами
        stats_str = ""
        for stat in ['str', 'dex', 'con', 'int', 'wis', 'cha']:
            value = player_data.get(stat, 10)
            modifier = DiceRoller.get_modifier(value)
            mod_str = f"+{modifier}" if modifier >= 0 else str(modifier)
            stats_str += f"{stat.upper()}: {value}({mod_str}) "
        
        system_prompt = f"""
        Ти - Майстер гри (Game Master) у RPG грі в стилі D&D.

        ПОТОЧНИЙ ГРАВЕЦЬ:
        - Ім'я: {player_data.get('name')}
        - Клас: {CLASSES.get(player_data.get('class'), {}).get('name', 'Невідомий')}
        - Рівень: {player_data.get('level')}
        - HP: {player_data.get('hp_current')}/{player_data.get('hp_max')}
        - MP: {player_data.get('mp_current')}/{player_data.get('mp_max')}
        - Характеристики: {stats_str}
        - Досвід: {player_data.get('xp')} XP
        - Золото: {player_data.get('gold')}
        - Інвентар: {player_data.get('inventory', '')}

        КОНТЕКСТ: {context}

        ТВОЯ РОЛЬ:
        1. Аналізуй дії гравців та визначай їх можливість
        2. Оцінюй кількість ходів (1 хід, 2 ходи, неможливо)
        3. Визначай складність (d20 + модифікатор проти цілі)
        4. Генеруй цікавий світ та ситуації
        5. Будь справедливим але викликаючим

        ПРАВИЛА КИДКІВ:
        - Проста дія: автоматичний успіх
        - Середня дія: d20 + модифікатор ≥ 12-15
        - Складна дія: d20 + модифікатор ≥ 16-18
        - Майже неможлива: d20 + модифікатор ≥ 20

        КІЛЬКІСТЬ ХОДІВ:
        - 1 хід: одна проста дія (атака, заклинання, рух)
        - 1 хід складний: комбо дія (скрадання+атака)
        - 2+ ходи: множинні дії (осліпити+атакувати+обшукати)
        - Неможливо: занадто багато за раунд

        ЗАВЖДИ відповідай у JSON форматі:
        {{
            "main_response": "Основна відповідь гравцю (2-3 речення)",
            "action_type": "simple/complex/multi_turn/impossible",
            "dice_required": {{
                "type": "d20/d6/d8/none",
                "modifier_stat": "STR/DEX/CON/INT/WIS/CHA/none",
                "difficulty": 12-20,
                "damage_dice": "d4/d6/d8/d10/none"
            }},
            "hint": "Підказка про можливості класу (1-2 речення)",
            "consequences": {{
                "success": "Що станеться при успіху",
                "failure": "Що станеться при невдачі"
            }},
            "xp_reward": 0-50,
            "gold_reward": 0-20
        }}

        Дія гравця: {prompt}
        """
        
        try:
            response = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=300,
                temperature=0.7,
                timeout=10
            )
            
            # Парсимо JSON відповідь
            content = response.choices[0].message.content
            return json.loads(content)
            
        except Exception as e:
            logger.error(f"Помилка GPT: {e}")
            return {
                "main_response": "Щось пішло не так з магією... Спробуй ще раз!",
                "action_type": "simple",
                "dice_required": {"type": "none"},
                "hint": "Перевір чи все правильно написано.",
                "consequences": {"success": "", "failure": ""},
                "xp_reward": 0,
                "gold_reward": 0
            }

    @staticmethod
    def calculate_attack(attacker_data: Dict, target_defense: int, weapon: str = "fists") -> Dict:
        """Обчислює атаку"""
        # Отримуємо дані зброї
        weapon_data = ITEMS.get(weapon, {'damage': 'd4', 'type': 'weapon'})
        
        # Модифікатор атаки
        if weapon_data.get('type') == 'ranged':
            attack_mod = DiceRoller.get_modifier(attacker_data.get('dex', 10))
        else:
            attack_mod = DiceRoller.get_modifier(attacker_data.get('str', 10))
        
        # Кидок атаки
        attack_roll = DiceRoller.roll('d20') + attack_mod
        
        if attack_roll >= target_defense:
            # Попадання - рахуємо урон
            damage_roll = DiceRoller.roll(weapon_data['damage'])
            if weapon_data.get('type') != 'ranged':
                damage_roll += DiceRoller.get_modifier(attacker_data.get('str', 10))
            
            return {
                'hit': True,
                'attack_roll': attack_roll,
                'damage': max(1, damage_roll),  # Мінімум 1 урон
                'critical': attack_roll >= 20
            }
        else:
            return {
                'hit': False,
                'attack_roll': attack_roll,
                'damage': 0,
                'critical': False
            }

# Обробники команд
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    user_id = update.effective_user.id
    
    # Перевіряємо чи гравець вже існує
    player_data = GoogleSheetsAPI.get_player(user_id)
    
    if player_data.get("success") and player_data.get("player"):
        player = player_data["player"]
        await update.message.reply_text(
            f"🎮 Вітаю знову, {player['name']}!\n"
            f"🛡️ Клас: {CLASSES.get(player['class'], {}).get('name', 'Невідомий')}\n"
            f"❤️ HP: {player['hp_current']}/{player['hp_max']}\n"
            f"💙 MP: {player['mp_current']}/{player['mp_max']}\n"
            f"⭐ Рівень: {player['level']} (XP: {player['xp']})\n"
            f"💰 Золото: {player['gold']}\n\n"
            f"Готовий до пригод? Напиши що хочеш зробити!\n\n"
            f"Доступні команди:\n"
            f"/stats - характеристики персонажа\n"
            f"/inventory - інвентар\n"
            f"/abilities - спеціальні здібності\n"
            f"/help - довідка"
        )
    else:
        # Показуємо кнопки вибору класу
        keyboard = []
        for class_key, class_data in CLASSES.items():
            keyboard.append([InlineKeyboardButton(class_data['name'], callback_data=f"class_{class_key}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "🏰 Ласкаво просимо до RPG пригоди!\n\n"
            "🎯 **Виберіть клас свого персонажа:**\n\n"
            "🛡️ **Лицар** - сильний воїн з мечем і щитом\n"
            "🧙‍♂️ **Маг** - володар магії та заклинань\n"
            "🏹 **Лучник** - майстер стрільби та виживання\n"
            "🗡️ **Злодій** - скритний та спритний\n"
            "⚕️ **Жрець** - цілитель та захисник від зла",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /stats - показати характеристики"""
    user_id = update.effective_user.id
    player_data = GoogleSheetsAPI.get_player(user_id)
    
    if not player_data.get("success") or not player_data.get("player"):
        await update.message.reply_text("❌ Спочатку створіть персонажа командою /start")
        return
    
    player = player_data["player"]
    
    # Формуємо статистику з модифікаторами
    stats_text = "📊 **ХАРАКТЕРИСТИКИ ПЕРСОНАЖА**\n\n"
    stats_text += f"👤 **{player['name']}** ({CLASSES.get(player['class'], {}).get('name', 'Невідомий')})\n"
    stats_text += f"⭐ Рівень: {player['level']} (XP: {player['xp']})\n\n"
    
    stats_text += f"❤️ **Здоров'я:** {player['hp_current']}/{player['hp_max']}\n"
    stats_text += f"💙 **Мана:** {player['mp_current']}/{player['mp_max']}\n"
    stats_text += f"💰 **Золото:** {player['gold']}\n\n"
    
    stats_text += "**Основні характеристики:**\n"
    for stat in ['str', 'dex', 'con', 'int', 'wis', 'cha']:
        value = player.get(stat, 10)
        modifier = DiceRoller.get_modifier(value)
        mod_str = f"+{modifier}" if modifier >= 0 else str(modifier)
        stat_names = {
            'str': '💪 Сила', 'dex': '🏃 Спритність', 'con': '🛡️ Витривалість',
            'int': '🧠 Інтелект', 'wis': '👁️ Мудрість', 'cha': '😊 Харизма'
        }
        stats_text += f"{stat_names[stat]}: {value} ({mod_str})\n"
    
    await update.message.reply_text(stats_text, parse_mode='Markdown')

async def inventory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /inventory - показати інвентар"""
    user_id = update.effective_user.id
    player_data = GoogleSheetsAPI.get_player(user_id)
    
    if not player_data.get("success") or not player_data.get("player"):
        await update.message.reply_text("❌ Спочатку створіть персонажа командою /start")
        return
    
    player = player_data["player"]
    inventory_str = player.get('inventory', '')
    
    if not inventory_str:
        await update.message.reply_text("🎒 Ваш інвентар порожній!")
        return
    
    items = inventory_str.split(',')
    inv_text = "🎒 **ІНВЕНТАР**\n\n"
    
    for item in items:
        if ':' in item:
            item_name, quantity = item.split(':')
            item_data = ITEMS.get(item_name, {'name': item_name})
            inv_text += f"• {item_data.get('name', item_name)} x{quantity}\n"
        else:
            item_data = ITEMS.get(item, {'name': item})
            inv_text += f"• {item_data.get('name', item)}\n"
    
    await update.message.reply_text(inv_text, parse_mode='Markdown')

async def abilities(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /abilities - показати здібності"""
    user_id = update.effective_user.id
    player_data = GoogleSheetsAPI.get_player(user_id)
    
    if not player_data.get("success") or not player_data.get("player"):
        await update.message.reply_text("❌ Спочатку створіть персонажа командою /start")
        return
    
    player = player_data["player"]
    player_class = player.get('class')
    class_abilities = CLASSES.get(player_class, {}).get('abilities', [])
    
    abilities_text = "⚡ **СПЕЦІАЛЬНІ ЗДІБНОСТІ**\n\n"
    
    for ability in class_abilities:
        ability_data = ABILITIES.get(ability, {'name': ability})
        abilities_text += f"🔸 **{ability_data['name']}**\n"
        
        # Додаємо опис здібності
        if 'mp_cost' in ability_data:
            abilities_text += f"   💙 Вартість: {ability_data['mp_cost']} MP\n"
        if 'uses_per_battle' in ability_data:
            abilities_text += f"   ⚔️ Використань за бій: {ability_data['uses_per_battle']}\n"
        if 'uses_per_day' in ability_data:
            abilities_text += f"   📅 Використань за день: {ability_data['uses_per_day']}\n"
        if 'damage' in ability_data:
            abilities_text += f"   💥 Урон: {ability_data['damage']}\n"
        
        abilities_text += "\n"
    
    await update.message.reply_text(abilities_text, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help - довідка"""
    help_text = """
🎮 **RPG BOT - ДОВІДКА**

**Основні команди:**
/start - почати гру або показати персонажа
/stats - характеристики персонажа
/inventory - показати інвентар
/abilities - спеціальні здібності
/help - ця довідка

**Як грати:**
1. Створіть персонажа командою /start
2. Пишіть що хочете робити звичайним текстом
3. Натискайте кнопки кубиків коли потрібно
4. Використовуйте кнопку "Підказка" для порад

**Приклади дій:**
• "Йду в ліс"
• "Атакую орка мечем"  
• "Шукаю скарби"
• "Розмовляю з торговцем"
• "Використовую зілля лікування"

**Система кубиків:**
• d20 - основні перевірки
• d6, d8, d10 - урон від зброї
• Модифікатори від характеристик

**Характеристики:**
💪 Сила - рукопашний бій, підйом важких речей
🏃 Спритність - стрільба, ухилення, скрадання  
🛡️ Витривалість - здоров'я, опір хворобам
🧠 Інтелект - магія, знання
👁️ Мудрість - інтуїція, сприйняття
😊 Харизма - переконання, торгівля

Приємної гри! 🎲
"""
    
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def handle_class_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробка вибору класу"""
    query = update.callback_query
    await query.answer()
    
    class_chosen = query.data.replace("class_", "")
    user_id = query.from_user.id
    user_name = query.from_user.first_name or "Герой"
    
    # Створюємо гравця
    result = GoogleSheetsAPI.create_player(user_id, user_name, class_chosen)
    
    if result.get("success"):
        class_data = CLASSES[class_chosen]
        await query.edit_message_text(
            f"🎉 **Персонаж створено!**\n\n"
            f"👤 **Ім'я:** {user_name}\n"
            f"🛡️ **Клас:** {class_data['name']}\n"
            f"❤️ **HP:** {class_data['hp_base']}\n"
            f"💙 **MP:** {class_data['mp_base']}\n"
            f"💰 **Золото:** {class_data['gold']}\n"
            f"🎒 **Спорядження:** {', '.join([ITEMS.get(item.split(':')[0], {'name': item}).get('name', item) for item in class_data['equipment']])}\n\n"
            f"🎮 **Ваша пригода починається!**\n"
            f"Напишіть що хочете зробити, наприклад:\n"
            f"• 'Йду досліджувати ліс'\n"
            f"• 'Шукаю пригоди в таверні'\n"
            f"• 'Треную свої навички'\n\n"
            f"💡 Використовуйте /help для довідки!",
            parse_mode='Markdown'
        )
    else:
        await query.edit_message_text(
            f"❌ Помилка створення персонажа: {result.get('error', 'Невідома помилка')}"
        )

async def handle_dice_roll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробка кидання кубиків"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    dice_data = query.data
    
    # Парсимо дані кубика
    if dice_data.startswith('roll_'):
        dice_info = dice_data.replace('roll_', '')
        
        # Отримуємо дані гравця для модифікаторів
        player_data = GoogleSheetsAPI.get_player(user_id)
        if not player_data.get("success"):
            await query.edit_message_text("❌ Помилка отримання даних гравця")
            return
        
        player = player_data["player"]
        
        # Кидаємо кубик
        if '+' in dice_info:
            dice_type, modifier_info = dice_info.split('+')
            if modifier_info.isdigit():
                modifier = int(modifier_info)
            else:
                # Модифікатор від характеристики
                stat_value = player.get(modifier_info.lower(), 10)
                modifier = DiceRoller.get_modifier(stat_value)
        else:
            dice_type = dice_info
            modifier = 0
        
        roll_result = DiceRoller.roll(dice_type)
        total = roll_result + modifier
        
        # Визначаємо результат
        if roll_result == 20:
            result_text = "🎯 **КРИТИЧНИЙ УСПІХ!**"
        elif roll_result == 1:
            result_text = "💥 **КРИТИЧНА НЕВДАЧА!**"
        elif total >= 15:
            result_text = "✅ **УСПІХ!**"
        else:
            result_text = "❌ **НЕВДАЧА**"
        
        mod_str = f"+{modifier}" if modifier >= 0 else str(modifier)
        
        await query.edit_message_text(
            f"🎲 **Кидок кубика**\n\n"
            f"🎯 {dice_type}{mod_str} = {roll_result}{mod_str} = **{total}**\n\n"
            f"{result_text}\n\n"
            f"Що робите далі?"
        )

async def handle_hint(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробка запиту підказки"""
    query = update.callback_query
    await query.answer()
    
    # Отримуємо збережену підказку з контексту
    hint = context.user_data.get('last_hint', 'Підказка недоступна')
    
    await query.edit_message_text(
        f"💡 **ПІДКАЗКА**\n\n{hint}\n\n"
        f"Що робите далі?",
        parse_mode='Markdown'
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробка звичайних повідомлень від гравців"""
    user_id = update.effective_user.id
    user_message = update.message.text
    
    # Отримуємо дані гравця
    player_data = GoogleSheetsAPI.get_player(user_id)
    
    if not player_data.get("success") or not player_data.get("player"):
        await update.message.reply_text(
            "❌ Спочатку створіть персонажа командою /start"
        )
        return
    
    player = player_data["player"]
    
    # Показуємо що бот думає
    thinking_message = await update.message.reply_text("🤔 Аналізую вашу дію...")
    
    # Отримуємо відповідь від GPT
    gpt_response = RPGGameLogic.get_gpt_response(user_message, player)
    
    # Видаляємо повідомлення "думаю"
    await thinking_message.delete()
    
    # Формуємо кнопки
    keyboard = []
    
    # Кнопка кубика якщо потрібна
    dice_info = gpt_response.get("dice_required", {})
    if dice_info.get("type") != "none" and dice_info.get("type"):
        dice_type = dice_info["type"]
        modifier_stat = dice_info.get("modifier_stat", "")
        
        if modifier_stat and modifier_stat != "none":
            stat_value = player.get(modifier_stat.lower(), 10)
            modifier = DiceRoller.get_modifier(stat_value)
            mod_str = f"+{modifier_stat}({modifier:+d})" if modifier != 0 else f"+{modifier_stat}"
            dice_text = f"🎲 {dice_type}{mod_str}"
            dice_callback = f"roll_{dice_type}+{modifier_stat}"
        else:
            dice_text = f"🎲 {dice_type}"
            dice_callback = f"roll_{dice_type}"
        
        keyboard.append([InlineKeyboardButton(dice_text, callback_data=dice_callback)])
    
    # Кнопка підказки (завжди)
    keyboard.append([InlineKeyboardButton("💡 Підказка", callback_data="show_hint")])
    
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    
    # Зберігаємо контекст для кнопок
    context.user_data['last_gpt_response'] = gpt_response
    context.user_data['last_hint'] = gpt_response.get('hint', 'Підказка недоступна')
    context.user_data['player_data'] = player
    
    # Додаємо інформацію про складність якщо є кубик
    response_text = gpt_response["main_response"]
    if dice_info.get("difficulty"):
        response_text += f"\n\n🎯 Складність: {dice_info['difficulty']}"
    
    await update.message.reply_text(
        response_text,
        reply_markup=reply_markup
    )

async def handle_button_press(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробка натискання кнопок"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "show_hint":
        await handle_hint(update, context)
    elif query.data.startswith("roll_"):
        await handle_dice_roll(update, context)

def main():
    """Головна функція"""
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Додаємо обробники
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("inventory", inventory))
    application.add_handler(CommandHandler("abilities", abilities))
    application.add_handler(CommandHandler("help", help_command))
    
    application.add_handler(CallbackQueryHandler(handle_class_selection, pattern="^class_"))
    application.add_handler(CallbackQueryHandler(handle_button_press, pattern="^(show_hint|roll_)"))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Запускаємо бота
    logger.info("🎮 RPG Бот запущений!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
