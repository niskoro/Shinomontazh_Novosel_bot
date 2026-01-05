import asyncio
import json
import os
import logging
from dotenv import load_dotenv  # ← ДОБАВИТЬ

load_dotenv()  # ← ДОБАВИТЬ
from datetime import datetime, timedelta
from threading import Lock

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from aiogram.filters import Command

# ================= НАСТРОЙКИ =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 402068020
DATA_DIR = "/data"
DATA_FILE = os.path.join(DATA_DIR, "slots.json")

os.makedirs(DATA_DIR, exist_ok=True)

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не найден. Проверь файл .env")
ADMIN_ID = 402068020
DATA_FILE = "slots.json"

YANDEX_MAP_URL = "https://yandex.ru/maps?whatshere%5Bpoint%5D=29.913778445829795%2C59.779631849357564&whatshere%5Bzoom%5D=18.93999&ll=29.913778445829795%2C59.77963184899495&z=18.93999&si=ba34h54bqx94ftdxtzcmghjhyr"
PHONE_TEXT = "+7 921 441-77-88"

# ================= ПРОВЕРКА ТОКЕНА =================
if BOT_TOKEN == "ВСТАВЬ_ЗДЕСЬ_ТОКЕН":
    raise ValueError("Вставь токен бота в переменную BOT_TOKEN")

# ================= ЛОГИ =================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ================= BOT =================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ================= КОНСТАНТЫ =================
WEEKDAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
ALL_HOURS = [f"{h:02d}:00" for h in range(10, 22)]
DEFAULT_WEEKDAY_HOURS = ["18:00", "19:00", "20:00"]

PENDING_BOOKINGS = {}
file_lock = Lock()

# ================= УВЕДОМЛЕНИЯ АДМИНУ =================
async def notify_admin_new_booking(booking_data):
    """Отправляет админу уведомление о новой записи"""
    day_date = datetime.fromisoformat(booking_data["day"]).strftime("%d.%m")
    weekday = WEEKDAYS_RU[datetime.fromisoformat(booking_data["day"]).weekday()]
    
    message = (
        f"🆕 НОВАЯ ЗАПИСЬ!"
        f"👤 {booking_data['name']}"
        f"📅 {day_date} ({weekday})"
        f"⏰ {booking_data['hour']}"
        f"📞 {booking_data['phone']}"
        f"⚠️ Пожалуйста, проверьте записи в админ-панели"
    )
    
    try:
        await bot.send_message(ADMIN_ID, message)
        logger.info(f"Уведомление админу отправлено: {booking_data['name']}")
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления админу: {e}")

async def notify_admin_cancel_booking(booking_data):
    """Отправляет админу уведомление об отмене записи"""
    day_date = datetime.fromisoformat(booking_data["day"]).strftime("%d.%m")
    weekday = WEEKDAYS_RU[datetime.fromisoformat(booking_data["day"]).weekday()]
    
    message = (
        f"🗑️ ЗАПИСЬ ОТМЕНЕНА"
        f"👤 {booking_data['name']}"
        f"📅 {day_date} ({weekday})"
        f"⏰ {booking_data['hour']}"
        f"📞 {booking_data['phone']}"
        f"ℹ️ Клиент отменил запись самостоятельно"
    )
    
    try:
        await bot.send_message(ADMIN_ID, message)
        logger.info(f"Уведомление об отмене отправлено: {booking_data['name']}")
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления об отмене: {e}")

# ================= ХРАНЕНИЕ =================
def load_slots():
    try:
        with file_lock:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        logger.error(f"Ошибка чтения файла {DATA_FILE}: {e}")
        return {}

def save_slots(data):
    try:
        with file_lock:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка записи файла {DATA_FILE}: {e}")

def ensure_day(slots, day):
    date = datetime.fromisoformat(day).date()
    if day not in slots:
        slots[day] = {
            "open": DEFAULT_WEEKDAY_HOURS.copy() if date.weekday() < 5 else [],
            "booked": []
        }

def user_has_booking(slots, day, user_id):
    for r in slots.get(day, {}).get("booked", []):
        if r.get("user_id") == user_id:
            return True
    return False

def get_user_bookings(slots, user_id):
    """Возвращает список записей пользователя"""
    bookings = []
    for day in slots:
        for booking in slots[day]["booked"]:
            if booking.get("user_id") == user_id:
                bookings.append({
                    "day": day,
                    "hour": booking["hour"],
                    "phone": booking["phone"],
                    "name": booking["name"]
                })
    return bookings

# ================= КЛАВИАТУРЫ =================
def main_keyboard(user_id):
    kb = [
        [KeyboardButton(text="🛞 Записаться"), KeyboardButton(text="❌ Отмена записи")],
        [KeyboardButton(text="💰 Цены")],
        [KeyboardButton(text="📍 Адрес"), KeyboardButton(text="📞 Связь")]
    ]
    if user_id == ADMIN_ID:
        kb.append([KeyboardButton(text="⚙️ Администрирование")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

admin_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🕒 Управление слотами")],
        [KeyboardButton(text="📅 Посмотреть записи")],
        [KeyboardButton(text="⬅️ Назад")]
    ],
    resize_keyboard=True
)

phone_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📞 Отправить номер", request_contact=True)],
        [KeyboardButton(text="❌ Отмена")]
    ],
    resize_keyboard=True,
    one_time_keyboard=True
)

# ================= START =================
@dp.message(Command("start"))
async def start(message: Message):
    await message.answer(
        "📅 Для записи на шиномонтаж, выберите удобный для вас день и время.\n"
        "🕒 Ориентировочное время работы с одним автомобилем один час.\n"
        "🛞 Работаю не на скорость.",
        reply_markup=main_keyboard(message.from_user.id)
    )

# ================= ИНФОРМАЦИЯ =================
@dp.message(F.text == "💰 Цены")
async def prices(message: Message):
    await message.answer(
        "💰 Стоимость сезонной переобувки 4х колес:\n"
        "🛞 R13 — 1900 ₽\n"
        "🛞 R14 — 2100 ₽\n"
        "🛞 R15 — 2300 ₽\n"
        "🛞 R16 — 2500 ₽\n"
        "🛞 R17 — 2900 ₽\n"
        "🛞 R18 — 3100 ₽\n"
        "🛞 R19 — 3500 ₽\n"
        "🛞 R20 — 4100 ₽\n"
    )

@dp.message(F.text == "📞 Связь")
async def contact(message: Message):
    await message.answer(
        "📞 Телефон: +7 921 441-77-88\n"
        "Telegram: @Skorodumoff"
    )

@dp.message(F.text == "📍 Адрес")
async def address(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗺 Открыть Яндекс.Карты", url=YANDEX_MAP_URL)]
    ])
    await message.answer(
        "📍 Адрес: СНТ Новосёл, 4-я Садовая, 57",
        reply_markup=kb
    )

# ================= МОИ ЗАПИСИ =================
@dp.message(F.text == "❌ Отмена записи")
async def my_bookings(message: Message):
    user_id = message.from_user.id
    slots = load_slots()
    bookings = get_user_bookings(slots, user_id)
    
    if not bookings:
        await message.answer(
            "📅 У вас нет активных записей.",
            reply_markup=main_keyboard(user_id)
        )
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for booking in bookings:
        day_date = datetime.fromisoformat(booking["day"]).strftime("%d.%m")
        weekday = WEEKDAYS_RU[datetime.fromisoformat(booking["day"]).weekday()]
        kb.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"⏰ {booking['hour']} ({day_date} {weekday}) ❌",
                callback_data=f"cancel|{booking['day']}|{booking['hour']}"
            )
        ])
    
    text = "📅 Подтвердите отмену 👇:"
    for booking in bookings:
        day_date = datetime.fromisoformat(booking["day"]).strftime("%d.%m")
        text += f"• {booking['hour']} ({day_date})"
    
    kb.inline_keyboard.append([
        InlineKeyboardButton(
            text="↩️ Назад",
            callback_data="back_to_main"
        )
    ])
    
    await message.answer(text, reply_markup=kb)

# ================= ЗАПИСЬ =================
@dp.message(F.text == "🛞 Записаться")
async def choose_day(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    today = datetime.now().date()

    for i in range(14):
        d = today + timedelta(days=i)
        kb.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"{d.strftime('%d.%m')} ({WEEKDAYS_RU[d.weekday()]})",
                callback_data=f"day|{d.isoformat()}"
            )
        ])

    await message.answer("Выберите день:", reply_markup=kb)

@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    await callback.message.answer(
        "Главное меню",
        reply_markup=main_keyboard(callback.from_user.id)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("day|"))
async def choose_time(callback: CallbackQuery):
    day = callback.data.split("|")[1]
    user_id = callback.from_user.id

    slots = load_slots()
    ensure_day(slots, day)
    save_slots(slots)

    if user_has_booking(slots, day, user_id):
        await callback.message.answer(
            "⛔ Вы уже записаны на этот день."
            "Можно записаться только один раз.",
            reply_markup=main_keyboard(user_id)
        )
        await callback.answer()
        return

    booked = [r["hour"] for r in slots[day]["booked"]]

    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for hour in sorted(slots[day]["open"]):
        if hour not in booked:
            kb.inline_keyboard.append([
                InlineKeyboardButton(
                    text=hour,
                    callback_data=f"time|{day}|{hour}"
                )
            ])

    await callback.message.answer(
        "Выберите время:" if kb.inline_keyboard else "⛔ Свободных слотов нет.",
        reply_markup=kb if kb.inline_keyboard else None
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("time|"))
async def choose_phone(callback: CallbackQuery):
    _, day, hour = callback.data.split("|")
    PENDING_BOOKINGS[callback.from_user.id] = {"day": day, "hour": hour}
    await callback.message.answer(
        "Для подтверждения записи отправьте ваш номер телефона кнопкой ниже 👇",
        reply_markup=phone_kb
    )
    await callback.answer()

@dp.message(F.text == "❌ Отмена")
async def cancel_phone_input(message: Message):
    """Отмена ввода телефона"""
    PENDING_BOOKINGS.pop(message.from_user.id, None)
    await message.answer(
        "❌ Запись отменена",
        reply_markup=main_keyboard(message.from_user.id)
    )

@dp.message(F.text, lambda m: m.from_user.id in PENDING_BOOKINGS and m.text != "❌ Отмена")
async def block_text_phone_input(message: Message):
    """Блокировка текста, кроме отмены"""
    await message.answer(
        "⛔ Пожалуйста, отправьте номер телефона кнопкой ниже 👇",
        reply_markup=phone_kb
    )

@dp.message(F.contact)
async def save_booking(message: Message):
    data = PENDING_BOOKINGS.pop(message.from_user.id, None)
    if not data:
        return

    slots = load_slots()
    ensure_day(slots, data["day"])

    if user_has_booking(slots, data["day"], message.from_user.id):
        await message.answer(
            "⛔ Вы уже записаны на этот день.",
            reply_markup=main_keyboard(message.from_user.id)
        )
        return

    # Создаем данные для записи и уведомления
    booking_data = {
        "hour": data["hour"],
        "user_id": message.from_user.id,
        "phone": message.contact.phone_number,
        "name": message.from_user.first_name or "Неизвестно",
        "day": data["day"]
    }
    
    # Сохраняем запись
    slots[data["day"]]["booked"].append(booking_data)
    save_slots(slots)

    # Отправляем подтверждение клиенту
    await message.answer(
        f"✅ Запись подтверждена"
        f"👤 {message.from_user.first_name}"
        f"📅 {data['day']}"
        f"⏰ {data['hour']}",
        reply_markup=main_keyboard(message.from_user.id)
    )
    
    # Уведомляем админа (асинхронно)
    asyncio.create_task(notify_admin_new_booking(booking_data))

# ================= ОТМЕНА ЗАПИСИ =================
@dp.callback_query(F.data.startswith("cancel|"))
async def cancel_booking(callback: CallbackQuery):
    _, day, hour = callback.data.split("|")
    user_id = callback.from_user.id
    
    slots = load_slots()
    ensure_day(slots, day)
    
    # Находим отменяемую запись
    booking_to_cancel = None
    for booking in slots[day]["booked"]:
        if booking.get("user_id") == user_id and booking["hour"] == hour:
            booking_to_cancel = booking
            break
    
    if not booking_to_cancel:
        await callback.message.answer(
            "❌ Запись не найдена.",
            reply_markup=main_keyboard(user_id)
        )
        await callback.answer()
        return
    
    # Удаляем запись
    slots[day]["booked"] = [
        booking for booking in slots[day]["booked"]
        if not (booking.get("user_id") == user_id and booking["hour"] == hour)
    ]
    
    save_slots(slots)
    
    # Уведомляем клиента
    day_date = datetime.fromisoformat(day).strftime("%d.%m")
    weekday = WEEKDAYS_RU[datetime.fromisoformat(day).weekday()]
    
    await callback.message.answer(
        f"✅ Запись отменена!"
        f"📅 {day_date} ({weekday})"
        f"⏰ {hour}",
        reply_markup=main_keyboard(user_id)
    )
    
    # Уведомляем админа (асинхронно)
    asyncio.create_task(notify_admin_cancel_booking(booking_to_cancel))
    
    await callback.answer("Запись отменена")

# ================= АДМИНКА =================
@dp.message(F.text == "⚙️ Администрирование")
async def admin_menu(message: Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("⚙️ Администрирование", reply_markup=admin_kb)

@dp.message(F.text == "🕒 Управление слотами")
async def admin_choose_day(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[])
    today = datetime.now().date()

    for i in range(14):
        d = today + timedelta(days=i)
        kb.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"{d.strftime('%d.%m')} ({WEEKDAYS_RU[d.weekday()]})",
                callback_data=f"admin_day|{d.isoformat()}"
            )
        ])

    await message.answer("Выберите день:", reply_markup=kb)

@dp.callback_query(F.data.startswith("admin_day|"))
async def admin_choose_hour(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return

    day = callback.data.split("|")[1]
    slots = load_slots()
    ensure_day(slots, day)
    save_slots(slots)

    kb = InlineKeyboardMarkup(inline_keyboard=[])

    for hour in ALL_HOURS:
        mark = "✅" if hour in slots[day]["open"] else "❌"
        kb.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"{mark} {hour}",
                callback_data=f"toggle|{day}|{hour}"
            )
        ])

    await callback.message.answer("Открыть / закрыть слоты:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("toggle|"))
async def toggle_slot(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return

    _, day, hour = callback.data.split("|")
    slots = load_slots()
    ensure_day(slots, day)

    if hour in slots[day]["open"]:
        slots[day]["open"].remove(hour)
    else:
        slots[day]["open"].append(hour)
        slots[day]["open"].sort()

    save_slots(slots)
    await admin_choose_hour(callback)
    await callback.answer()

@dp.message(F.text == "📅 Посмотреть записи")
async def view_bookings(message: Message):
    slots = load_slots()
    text = "📅 Записи:\n"
    empty = True

    for day in sorted(slots.keys()):
        if slots[day]["booked"]:
            empty = False
            text += f"{day}:"
            for r in slots[day]["booked"]:
                text += f" ⏰ {r['hour']} | 📞 {r['phone']}\n"
            text += ""

    await message.answer(text if not empty else "Записей пока нет.")

@dp.message(F.text == "⬅️ Назад")
async def back(message: Message):
    await message.answer("Главное меню", reply_markup=main_keyboard(message.from_user.id))

# ================= RUN =================
async def main():
    logger.info("БОТ ЗАПУЩЕН")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
