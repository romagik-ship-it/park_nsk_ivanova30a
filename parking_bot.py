import telebot
from telebot import types
import sqlite3
import pandas as pd
import os

# ==========================================================
# НАСТРОЙКИ БОТА (ОБЯЗАТЕЛЬНО ЗАПОЛНИТЕ)
# ==========================================================
TOKEN = 'ВАШ_ТОКЕН_БОТА'
# Список ID администраторов через запятую в квадратных скобках
ADMIN_IDS = [] 
# ==========================================================

bot = telebot.TeleBot(TOKEN)
user_states = {}

def init_db():
    conn = sqlite3.connect('parking.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS residents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plate_number TEXT UNIQUE,
            phone_number TEXT
        )
    ''')
    conn.commit()
    conn.close()

def admin_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn_check = types.KeyboardButton("🔍 Проверить доступ")
    btn_add = types.KeyboardButton("➕ Добавить вручную")
    btn_del = types.KeyboardButton("🗑️ Удалить машину")
    btn_excel = types.KeyboardButton("📊 Выгрузить в Excel")
    markup.add(btn_check, btn_add, btn_del, btn_excel)
    return markup

def resident_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn_request = types.KeyboardButton("🚗 Отправить заявку на доступ")
    markup.add(btn_request)
    return markup

def cancel_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn_cancel = types.KeyboardButton("❌ Отмена")
    markup.add(btn_cancel)
    return markup

def approve_keyboard(plate, phone, user_chat_id):
    markup = types.InlineKeyboardMarkup()
    btn_yes = types.InlineKeyboardButton("✅ Одобрить", callback_data=f"app_yes|{plate}|{phone}|{user_chat_id}")
    btn_no = types.InlineKeyboardButton("❌ Отклонить", callback_data=f"app_no|{user_chat_id}")
    markup.add(btn_yes, btn_no)
    return markup

def is_admin(user_id):
    return user_id in ADMIN_IDS

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    user_states.pop(user_id, None)
    if is_admin(user_id):
        bot.send_message(message.chat.id, "⚙️ **Панель Администратора.**", reply_markup=admin_menu(), parse_mode='Markdown')
    else:
        bot.send_message(message.chat.id, "👋 **Бот парковки жильцов.**", reply_markup=resident_menu(), parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: True)
def callback_inline(call):
    if not is_admin(call.from_user.id): return
    data = call.data.split('|')
    action = data[0]

    if action == "app_yes":
        plate, phone, resident_chat_id = data[1], data[2], int(data[3])
        try:
            conn = sqlite3.connect('parking.db')
            cursor = conn.cursor()
            cursor.execute("INSERT INTO residents (plate_number, phone_number) VALUES (?, ?)", (plate, phone))
            conn.commit()
            conn.close()
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=f"✅ Заявка одобрена! Машина **{plate}** добавлена.", parse_mode='Markdown')
            bot.send_message(resident_chat_id, f"🎉 Ваша заявка одобрена! Машина **{plate}** в базе.", parse_mode='Markdown')
        except sqlite3.IntegrityError:
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=f"⚠️ Машина {plate} уже есть в базе.")
    elif action == "app_no":
        resident_chat_id = int(data[1])
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="❌ Заявка отклонена.")
        bot.send_message(resident_chat_id, "⚠️ Ваша заявка отклонена администратором.")

@bot.message_handler(content_types=['text'])
def handle_text(message):
    user_id = message.from_user.id
    text = message.text.strip()

    if text == "❌ Отмена":
        user_states.pop(user_id, None)
        reply = admin_menu() if is_admin(user_id) else resident_menu()
        bot.send_message(message.chat.id, "Действие отменено.", reply_markup=reply)
        return

    if not is_admin(user_id):
        if text == "🚗 Отправить заявку на доступ":
            user_states[user_id] = {'step': 'res_plate'}
            bot.send_message(message.chat.id, "Введите гос. номер машины (Х777ХХ99):", reply_markup=cancel_menu())
            return
        state = user_states.get(user_id)
        if state:
            if state['step'] == 'res_plate':
                user_states[user_id]['plate'] = text.upper()
                user_states[user_id]['step'] = 'res_phone'
                bot.send_message(message.chat.id, "Номер принят. Введите телефон:")
                return
            if state['step'] == 'res_phone':
                plate, phone = state['plate'], text
                user_states.pop(user_id, None)
                bot.send_message(message.chat.id, "⏳ Заявка отправлена администраторам.", reply_markup=resident_menu())
                for admin_id in ADMIN_IDS:
                    try: bot.send_message(admin_id, f"🔔 **Новая заявка!**\n🚗 Машина: {plate}\n📱 Телефон: {phone}", reply_markup=approve_keyboard(plate, phone, message.chat.id), parse_mode='Markdown')
                    except Exception: pass
                return
        return

    # Логика АДМИНИСТРАТОРА
    if text == "🔍 Проверить доступ":
        user_states[user_id] = {'step': 'chk_plate'}
        bot.send_message(message.chat.id, "Введите номер для проверки:", reply_markup=cancel_menu())
        return
    if text == "➕ Добавить вручную":
        user_states[user_id] = {'step': 'add_plate'}
        bot.send_message(message.chat.id, "Введите гос. номер:", reply_markup=cancel_menu())
        return
    if text == "🗑️ Удалить машину":
        user_states[user_id] = {'step': 'del_plate'}
        bot.send_message(message.chat.id, "Введите номер для УДАЛЕНИЯ:", reply_markup=cancel_menu())
        return
    if text == "📊 Выгрузить в Excel":
        try:
            conn = sqlite3.connect('parking.db')
            df = pd.read_sql_query("SELECT id, plate_number, phone_number FROM residents", conn)
            conn.close()
            if df.empty:
                bot.send_message(message.chat.id, "📭 База данных пуста.")
                return
            df.to_excel("parking.xlsx", index=False)
            with open("parking.xlsx", 'rb') as doc:
                bot.send_document(message.chat.id, doc, caption="📊 База данных парковки.")
            os.remove("parking.xlsx")
        except Exception:
            bot.send_message(message.chat.id, "❌ Ошибка генерации Excel.")
        return

    state = user_states.get(user_id)
    if state:
        step = state['step']
        if step == 'chk_plate':
            plate = text.upper()
            user_states.pop(user_id, None)
            conn = sqlite3.connect('parking.db')
            cursor = conn.cursor()
            cursor.execute("SELECT phone_number FROM residents WHERE plate_number = ?", (plate,))
            res = cursor.fetchone()
            conn.close()
            if res: bot.send_message(message.chat.id, f"🟢 **ДОСТУП РАЗРЕШЕН**\n📱 Телефон: {res[0]}", reply_markup=admin_menu(), parse_mode='Markdown')
            else: bot.send_message(message.chat.id, f"🔴 **ДОСТУП ЗАПРЕЩЕН**", reply_markup=admin_menu(), parse_mode='Markdown')
        elif step == 'del_plate':
            plate = text.upper()
            user_states.pop(user_id, None)
            conn = sqlite3.connect('parking.db')
            cursor = conn.cursor()
            cursor.execute("DELETE FROM residents WHERE plate_number = ?", (plate,))
            conn.commit()
            conn.close()
            bot.send_message(message.chat.id, f"🗑️ Номер {plate} удален.", reply_markup=admin_menu())
        elif step == 'add_plate':
            user_states[user_id]['plate'] = text.upper()
            user_states[user_id]['step'] = 'add_phone'
            bot.send_message(message.chat.id, "Номер принят. Введите телефон:")
        elif step == 'add_phone':
            plate, phone = state['plate'], text
            user_states.pop(user_id, None)
            try:
                conn = sqlite3.connect('parking.db')
                cursor = conn.cursor()
                cursor.execute("INSERT INTO residents (plate_number, phone_number) VALUES (?, ?)", (plate, phone))
                conn.commit()
                conn.close()
                bot.send_message(message.chat.id, f"✅ Добавлен: {plate}", reply_markup=admin_menu())
            except Exception:
                bot.send_message(message.chat.id, "⚠️ Ошибка записи.")

if __name__ == '__main__':
    init_db()
    print("Бот парковки запущен!")
    bot.polling(none_stop=True)

