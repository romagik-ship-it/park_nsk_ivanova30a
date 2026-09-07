import os
import telebot
from telebot import types
import sqlite3
import pandas as pd
from dotenv import load_dotenv

load_dotenv()
T = os.getenv('BOT_TOKEN')
A = [int(x.strip()) for x in os.getenv('ADMIN_IDS', '').split(',') if x.strip()]

bot = telebot.TeleBot(T)
user_states = {}

def init_db():
    c = sqlite3.connect('parking.db')
    cur = c.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS residents (id INTEGER PRIMARY KEY AUTOINCREMENT, plate_number TEXT UNIQUE, phone_number TEXT, apartment_number TEXT)''')
    c.commit()
    c.close()

def admin_menu():
    m = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    m.add(types.KeyboardButton("🔍 Проверить доступ"), types.KeyboardButton("➕ Добавить вручную"), types.KeyboardButton("🗑️ Удалить машину"), types.KeyboardButton("📊 Выгрузить в Excel"))
    return m

def resident_menu():
    m = types.ReplyKeyboardMarkup(resize_keyboard=True)
    m.add(types.KeyboardButton("🚗 Отправить заявку на доступ"))
    return m

def cancel_menu():
    m = types.ReplyKeyboardMarkup(resize_keyboard=True)
    m.add(types.KeyboardButton("❌ Отмена"))
    return m

def approve_keyboard(p, ph, apt, uid):
    m = types.InlineKeyboardMarkup()
    m.add(types.InlineKeyboardButton("✅ Одобрить", callback_data=f"y|{p}|{ph}|{apt}|{uid}"), types.InlineKeyboardButton("❌ Отклонить", callback_data=f"n|{uid}"))
    return m

def is_admin(uid):
    return uid in A

@bot.message_handler(commands=['start'])
def send_welcome(msg):
    uid = msg.from_user.id
    user_states.pop(uid, None)
    if is_admin(uid):
        bot.send_message(msg.chat.id, "⚙️ Панель управления парковкой:", reply_markup=admin_menu())
    else:
        bot.send_message(msg.chat.id, "👋 Бот регистрации транспорта жильцов:", reply_markup=resident_menu())

@bot.callback_query_handler(func=lambda c: True)
def callback_inline(call):
    if not is_admin(call.from_user.id): return
    data = call.data.split('|')
    act = data[0]

    if act == "y":
        p, ph, apt, r_id = data[1], data[2], data[3], int(data[4])
        try:
            c = sqlite3.connect('parking.db')
            cur = c.cursor()
            cur.execute("INSERT INTO residents (plate_number, phone_number, apartment_number) VALUES (?, ?, ?)", (p, ph, apt))
            c.commit()
            c.close()
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=f"✅ Авто {p} внесено.")
            bot.send_message(r_id, f"🎉 Одобрено! Машина {p} в базе парковки.")
        except sqlite3.IntegrityError:
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=f"⚠️ {p} уже есть в базе.")
    elif act == "n":
        r_id = int(data[1])
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="❌ Заявка отклонена.")
        bot.send_message(r_id, "⚠️ Ваша заявка на парковку была отклонена.")

@bot.message_handler(content_types=['text'])
def handle_text(msg):
    uid = msg.from_user.id
    txt = msg.text.strip()

    if txt == "❌ Отмена":
        user_states.pop(uid, None)
        rep = admin_menu() if is_admin(uid) else resident_menu()
        bot.send_message(msg.chat.id, "Отмена.", reply_markup=rep)
        return

    if not is_admin(uid):
        if txt == "🚗 Отправить заявку на доступ":
            user_states[uid] = {'step': 'r_p'}
            bot.send_message(msg.chat.id, "Введите номер машины:", reply_markup=cancel_menu())
            return
        st = user_states.get(uid)
        if st:
            if st['step'] == 'r_p':
                user_states[uid]['p'] = txt.upper()
                user_states[uid]['step'] = 'r_ph'
                bot.send_message(msg.chat.id, "Введите номер телефона владельца:")
                return
            if st['step'] == 'r_ph':
                user_states[uid]['ph'] = txt
                user_states[uid]['step'] = 'r_apt'
                bot.send_message(msg.chat.id, "Введите номер квартиры:")
                return
            if st['step'] == 'r_apt':
                p, ph, apt = st['p'], st['ph'], txt
                user_states.pop(uid, None)
                bot.send_message(msg.chat.id, "⏳ Отправлено на проверку.", reply_markup=resident_menu())
                for a_id in A:
                    try: bot.send_message(a_id, f"🔔 Заявка!\n🚗 Авто: {p}\n📱 Тел: {ph}\n🏢 Кв: {apt}", reply_markup=approve_keyboard(p, ph, apt, msg.chat.id))
                    except Exception: pass
                return
        return

    if txt == "🔍 Проверить доступ":
        user_states[uid] = {'step': 'chk_p'}
        bot.send_message(msg.chat.id, "Введите номер авто или квартиры:", reply_markup=cancel_menu())
        return
    if txt == "➕ Добавить вручную":
        user_states[uid] = {'step': 'add_p'}
        bot.send_message(msg.chat.id, "Введите номер авто:", reply_markup=cancel_menu())
        return
    if txt == "🗑️ Удалить машину":
        user_states[uid] = {'step': 'del_p'}
        bot.send_message(msg.chat.id, "Введите гос. номер для удаления:", reply_markup=cancel_menu())
        return
    if txt == "📊 Выгрузить в Excel":
        try:
            c = sqlite3.connect('parking.db')
            df = pd.read_sql_query("SELECT id, plate_number, phone_number, apartment_number FROM residents", c)
            c.close()
            if df.empty:
                bot.send_message(msg.chat.id, "📭 База пуста.")
                return
            df.to_excel("parking.xlsx", index=False)
            with open("parking.xlsx", 'rb') as doc:
                bot.send_document(msg.chat.id, doc, caption="📊 База.")
            os.remove("parking.xlsx")
        except Exception:
            bot.send_message(msg.chat.id, "❌ Ошибка Excel.")
        return

    st = user_states.get(uid)
    if st:
        step = st['step']
        if step == 'chk_p':
            val = txt.upper()
            user_states.pop(uid, None)
            c = sqlite3.connect('parking.db')
            cur = c.cursor()
            cur.execute("SELECT phone_number, apartment_number FROM residents WHERE plate_number = ?", (val,))
            res = cur.fetchone()
            if res:
                c.close()
                bot.send_message(msg.chat.id, f"🟢 РАЗРЕШЕН\n🚗 Авто: {val}\n📱 Тел: {res[0]}\n🏢 Кв: {res[1]}", reply_markup=admin_menu())
            else:
                cur.execute("SELECT plate_number, phone_number FROM residents WHERE apartment_number = ?", (txt,))
                res_apt = cur.fetchall()
                c.close()
                if res_apt:
                    resp = f"🏢 Автомобили квартиры №{txt}:\n\n"
                    for row in res_apt:
                        resp += f"🚗: {row[0]} | 📱: {row[1]}\n"
                    bot.send_message(msg.chat.id, resp, reply_markup=admin_menu())
                else:
                    bot.send_message(msg.chat.id, "🔴 НЕ НАЙДЕНО", reply_markup=admin_menu())
        elif step == 'del_p':
            p = txt.upper()
            user_states.pop(uid, None)
            c = sqlite3.connect('parking.db')
            cur = c.cursor()
            cur.execute("DELETE FROM residents WHERE plate_number = ?", (p,))
            c.commit()
            c.close()
            bot.send_message(msg.chat.id, f"🗑️ Номер {p} удален из базы.", reply_markup=admin_menu())
        elif step == 'add_p':
            user_states[uid]['p'] = txt.upper()
            user_states[uid]['step'] = 'add_ph'
            bot.send_message(msg.chat.id, "Введите номер телефона:")
        elif step == 'add_ph':
            user_states[uid]['ph'] = txt
            user_states[uid]['step'] = 'add_apt'
            bot.send_message(msg.chat.id, "Введите номер квартиры:")
        elif step == 'add_apt':
            p, ph, apt = st['p'], st['ph'], txt
            user_states.pop(uid, None)
            try:
                c = sqlite3.connect('parking.db')
                cur = c.cursor()
                cur.execute("INSERT INTO residents (plate_number, phone_number, apartment_number) VALUES (?, ?, ?)", (p, ph, apt))
                c.commit()
                c.close()
                bot.send_message(msg.chat.id, f"✅ Добавлен {p} (кв. {apt})", reply_markup=admin_menu())
            except Exception:
                bot.send_message(msg.chat.id, "⚠️ Ошибка записи. Возможно, авто уже в базе.", reply_markup=admin_menu())

if __name__ == '__main__':
    init_db()
    bot.polling(none_stop=True)
