import os
import random
import redis
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext

# Настройки
TOKEN = "YOUR_BOT_TOKEN"  # Замени на свой токен
ADMIN_ID = 123456789  # Твой ID для админ-команд
REDIS_URL = "redis://localhost:6379/0"  # Адрес Redis

# Подключение к Redis
db = redis.from_url(REDIS_URL)

# Карточки и их шансы (веса)
CARDS = {
    "common": [
        {"name": "Обычная карта 1", "image": "common1.png", "weight": 50},
        {"name": "Обычная карта 2", "image": "common2.png", "weight": 30}
    ],
    "rare": [
        {"name": "Редкая карта", "image": "rare1.png", "weight": 15},
    ],
    "legendary": [
        {"name": "Легендарная карта", "image": "legendary1.png", "weight": 5}
    ]
}

# Стандартный фон (если не установлен)
DEFAULT_BACKGROUND = "default_bg.jpg"

# Клавиатуры
def main_menu():
    keyboard = [
        [InlineKeyboardButton("🎁 Купить пак (15 звёзд)", callback_data="buy_pack")],
        [InlineKeyboardButton("📖 Профиль", callback_data="profile"),
         InlineKeyboardButton("🔙 На главную", callback_data="back")]
    ]
    return InlineKeyboardMarkup(keyboard)

# Получение случайной карты
def get_random_card():
    total_weight = sum(card["weight"] for rarity in CARDS.values() for card in rarity)
    random_value = random.uniform(0, total_weight)
    current = 0
    for rarity, cards in CARDS.items():
        for card in cards:
            current += card["weight"]
            if random_value <= current:
                return {"rarity": rarity, **card}

# Сохранение карт пользователя
def save_user_card(user_id, card):
    user_cards = db.get(f"user:{user_id}:cards")
    if not user_cards:
        cards = []
    else:
        cards = eval(user_cards.decode('utf-8'))
    cards.append(card)
    db.set(f"user:{user_id}:cards", str(cards))

# Получение карт пользователя
def get_user_cards(user_id):
    user_cards = db.get(f"user:{user_id}:cards")
    return eval(user_cards.decode('utf-8')) if user_cards else []

# Получение баланса
def get_balance(user_id):
    balance = db.hgetall(f"user:{user_id}:balance")
    if not balance:
        return {"stars": 0, "coins": 0}
    return {k.decode('utf-8'): int(v.decode('utf-8')) for k, v in balance.items()}

# Установка баланса
def set_balance(user_id, stars=0, coins=0):
    db.hset(f"user:{user_id}:balance", "stars", stars)
    db.hset(f"user:{user_id}:balance", "coins", coins)

# Получение фона
def get_background():
    bg_path = db.get("app:background")
    return bg_path.decode('utf-8') if bg_path else DEFAULT_BACKGROUND

# Команда /start
def start(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if not db.exists(f"user:{user_id}:balance"):
        set_balance(user_id, stars=50, coins=0)  # Стартовый баланс
    
    bg_path = get_background()
    try:
        with open(bg_path, 'rb') as bg_file:
            update.message.reply_photo(
                photo=bg_file,
                caption=f"🎮 Добро пожаловать!\n⭐ Звёзды: {get_balance(user_id)['stars']}\n🪙 Монеты: {get_balance(user_id)['coins']}",
                reply_markup=main_menu()
            )
    except FileNotFoundError:
        update.message.reply_text("Ошибка: фон не найден. Админ, установите новый фон /setbg")

# Покупка пака
def buy_pack(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    balance = get_balance(user_id)
    
    if balance["stars"] < 15:
        query.answer("❌ Недостаточно звёзд!")
        return
    
    # Списание звёзд и начисление монет
    set_balance(user_id, balance["stars"] - 15, balance["coins"] + 15)
    
    # Выдача 5 карт
    new_cards = [get_random_card() for _ in range(5)]
    for card in new_cards:
        save_user_card(user_id, card)
    
    # Формирование сообщения
    cards_text = "\n".join([f"🎴 {card['name']} ({card['rarity']})" for card in new_cards])
    query.edit_message_caption(
        caption=f"🎉 Вы получили:\n{cards_text}\n\n⭐ Звёзды: {get_balance(user_id)['stars']}\n🪙 Монеты: {get_balance(user_id)['coins']}",
        reply_markup=main_menu()
    )

# Профиль
def show_profile(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    cards = get_user_cards(user_id)
    
    if not cards:
        query.edit_message_caption(
            caption="📖 Ваш профиль пуст.\n\nОткройте хотя бы один пак!",
            reply_markup=main_menu()
        )
        return
    
    # Группировка по редкости
    cards_by_rarity = {}
    for card in cards:
        if card["rarity"] not in cards_by_rarity:
            cards_by_rarity[card["rarity"]] = []
        cards_by_rarity[card["rarity"]].append(card["name"])
    
    profile_text = "📚 Ваши карточки:\n"
    for rarity, cards_list in cards_by_rarity.items():
        profile_text += f"\n🌟 {rarity.upper()}:\n"
        profile_text += "\n".join([f"• {card}" for card in cards_list])
    
    query.edit_message_caption(
        caption=f"{profile_text}\n\n⭐ Звёзды: {get_balance(user_id)['stars']}\n🪙 Монеты: {get_balance(user_id)['coins']}",
        reply_markup=main_menu()
    )

# Админ: смена фона
def set_background(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("❌ Только админ может использовать эту команду!")
        return
    
    if not update.message.photo:
        update.message.reply_text("❌ Отправьте изображение!")
        return
    
    photo = update.message.photo[-1].get_file()
    new_bg_path = "custom_bg.jpg"
    photo.download(new_bg_path)
    db.set("app:background", new_bg_path)
    update.message.reply_text("✅ Фон обновлён!")

# Главная функция
def main():
    updater = Updater(TOKEN)
    dp = updater.dispatcher
    
    # Обработчики
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("setbg", set_background))
    dp.add_handler(CallbackQueryHandler(buy_pack, pattern="buy_pack"))
    dp.add_handler(CallbackQueryHandler(show_profile, pattern="profile"))
    dp.add_handler(CallbackQueryHandler(start, pattern="back"))
    
    print("Бот запущен!")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
