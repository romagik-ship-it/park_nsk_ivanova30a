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

# Настройка пути строго по инструкции BotHost
DATA_DIR = os.getenv('DATA_DIR', '/app/data')
DB_PATH = os.path.join(DATA_DIR, 'parking.db')

def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    cur = c.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS residents (id INTEGER PRIMARY KEY AUTOINCREMENT, plate_number TEXT UNIQUE, phone_number TEXT, apartment_number TEXT)''')
    c.commit()
    c.close()

def admin_menu():
    m = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    m.add(types.KeyboardButton("🔍 Проверить доступ"), types.KeyboardButton("➕ Добавить вручную"), types.KeyboardButton("🗑️ Удалить машину"), types.KeyboardButton("📊 Выгрузить базу"))
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

def import_keyboard(file_id):
    m = types.InlineKeyboardMarkup()
    m.add(
        types.InlineKeyboardButton("🔄 Обнулить базу и записать", callback_data=f"imp_clear|{file_id}"),
        types.InlineKeyboardButton("➕ Добавить новые записи", callback_data=f"imp_append|{file_id}")
    )
    return m

def is_admin(uid):
    return uid in A

@bot.message_handler(commands=['start'])
def send_welcome(msg):
    uid = msg.from_user.id
    user_states.pop(uid, None)
    if is_admin(uid):
        bot.send_message(msg.chat.id, "⚙️ Панель управления парковкой.\nВы можете прислать CSV-файл для загрузки.", reply_markup=admin_menu())
    else:
        bot.send_message(msg.chat.id, "👋 Бот регистрации транспорта жильцов:", reply_markup=resident_menu())

@bot.callback_query_handler(func=lambda c: True)
def callback_inline(call):
    if not is_admin(call.from_user.id): return
    data = call.data.split('|')
    act = data

    if act == "y":
        p, ph, apt, r_id = data, data, data, int(data)
        try:
            c = sqlite3.connect(DB_PATH)
            cur = c.cursor()
            cur.execute("INSERT INTO residents (plate_number, phone_number, apartment_number) VALUES (?, ?, ?)", (p, ph, apt))
            c.commit()
            c.close()
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=f"✅ Авто {p} внесено.")
            bot.send_message(r_id, f"🎉 Одобрено! Машина {p} в базе парковки.")
        except sqlite3.IntegrityError:
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=f"⚠️ {p} уже есть в базе.")
    elif act == "n":
        r_id = int(data)
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="❌ Заявка отклонена.")
        bot.send_message(r_id, "⚠️ Ваша заявка на парковку была отклонена.")

    elif act in ["imp_clear", "imp_append"]:
        file_id = data
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="⏳ Начинаю импорт данных...")
        try:
            file_info = bot.get_file(file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            temp_filename = os.path.join(DATA_DIR, f"import_{call.from_user.id}.csv")
            with open(temp_filename, 'wb') as f:
                f.write(downloaded_file)
            
            df = pd.read_csv(temp_filename, dtype=str, encoding='utf-8-sig')
            os.remove(temp_filename)
            
            c = sqlite3.connect(DB_PATH)
            cur = c.cursor()
            if act == "imp_clear":
                cur.execute("DELETE FROM residents")
            
            added_count = 0
            errors_count = 0
            
            for _, row in df.iterrows():
                plate = str(row.get("Номер", "")).strip().upper()
                phone = str(row.get("Телефон", "")).strip()
                apt = str(row.get("Квартира", "")).strip()
                
                if not plate or plate == "NAN" or plate == "":
                    continue
                if phone == "NAN": phone = ""
                if apt == "NAN": apt = ""
                
                try:
                    cur.execute("INSERT INTO residents (plate_number, phone_number, apartment_number) VALUES (?, ?, ?)", (plate, phone, apt))
                    added_count += 1
                except sqlite3.IntegrityError:
                    errors_count += 1
            
            c.commit()
            c.close()
            
            msg_text = f"📊 **Импорт успешно выполнен!**\n\n"
            if act == "imp_clear":
                msg_text += "🔄 База была полностью очищена перед записью.\n"
            msg_text += f"✅ Записано автомобилей: {added_count}\n"
            if act == "imp_append":
                msg_text += f"⚠️ Пропущено дубликатов (уже были в базе): {errors_count}"
            bot.send_message(call.message.chat.id, msg_text, parse_mode='Markdown', reply_markup=admin_menu())
        except Exception as e:
            bot.send_message(call.message.chat.id, f"❌ Ошибка обработки: {str(e)}")

@bot.message_handler(content_types=['document'])
def handle_document(msg):
    uid = msg.from_user.id
    if not is_admin(uid): return
    if msg.document.file_name.endswith('.csv'):
        try:
            file_info = bot.get_file(msg.document.file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            temp_check = os.path.join(DATA_DIR, f"check_{uid}.csv")
            with open(temp_check, 'wb') as f:
                f.write(downloaded_file)
            df = pd.read_csv(temp_check, encoding='utf-8-sig')
            os.remove(temp_check)
            
            df.columns = [str(c).strip().capitalize() for c in df.columns]
            required_cols = ["Номер", "Телефон", "Квартира"]
            
            if not all(col in df.columns for col in required_cols):
                bot.send_message(msg.chat.id, "❌ В файле должны быть колонки: 'Номер', 'Телефон', 'Квартира'.")
                return
            bot.send_message(msg.chat.id, "📋 Файл принят. Что необходимо сделать с базой данных?", reply_markup=import_keyboard(msg.document.file_id))
        except Exception as e:
            bot.send_message(msg.chat.id, f"❌ Не удалось прочитать файл: {str(e)}")
    else:
        bot.send_message(msg.chat.id, "❌ Бот принимает файлы базы только в формате .csv")

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
    if txt == "📊 Выгрузить базу":
        try:
            c = sqlite3.connect(DB_PATH)
            df = pd.read_sql_query("SELECT id AS '№', plate_number AS 'Номер', phone_number AS 'Телефон', apartment_number AS 'Квартира' FROM residents", c)
            c.close()
            if df.empty:
                bot.send_message(msg.chat.id, "📭 База пуста.")
                return
            
            file_name = os.path.join(DATA_DIR, "parking_base.csv")
            df.to_csv(file_name, index=False, encoding='utf-8-sig')
            with open(file_name, 'rb') as doc:
                bot.send_document(msg.chat.id, doc, caption="📊 База данных парковки.")
            os.remove(file_name)
        except Exception as e:
            bot.send_message(msg.chat.id, f"❌ Ошибка выгрузки: {str(e)}")
        return

    st = user_states.get(uid)
    if st:
        step = st['step']
        if step == 'chk_p':
            val = txt.upper()
            user_states.pop(uid, None)
            c = sqlite3.connect(DB_PATH)
            cur = c.cursor()
            cur.execute("SELECT phone_number, apartment_number FROM residents WHERE plate_number = ?", (val,))
            res = cur.fetchone()
            if res:
                c.close()
                phone_val, apt_val = res
                bot.send_message(
                    msg.chat.id, 
                    f"🟢 **ДОСТУП РАЗРЕШЕН**\n\n"
                    f"🚗 Авто: {val}\n"
                    f"📱 Тел: {phone_val}\n"
                    f"🏢 Кв: {apt_val}", 
                    reply_markup=admin_menu(),
                    parse_mode='Markdown'
                )
            else:
                cur.execute("SELECT plate_number, phone_number FROM residents WHERE apartment_number = ?", (txt,))
                res_apt = cur.fetchall()
                c.close()
                if res_apt:
                    resp = f"🏢 **Автомобили квартиры №{txt}:**\n\n"
                    for row in res_apt:
                        p_row, ph_row = row
                        resp += f"🚗 Авто: `{p_row}` | 📱 Тел: {ph_row}\n"
                    bot.send_message(msg.chat.id, resp, reply_markup=admin_menu(), parse_mode='Markdown')
                else:
                    bot.send_message(msg.chat.id, "🔴 **ДОСТУП ЗАПРЕЩЕН / НЕ НАЙДЕНО**", reply_markup=admin_menu(), parse_mode='Markdown')
        elif step == 'del_p':
            p = txt.upper()
            user_states.pop(uid, None)
            c = sqlite3.connect(DB_PATH)
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
                c = sqlite3.connect(DB_PATH)
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

