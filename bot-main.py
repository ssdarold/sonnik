# -*- coding: utf-8 -*-
import openai
import asyncio
from aiogram import Bot, types
from aiogram.dispatcher import Dispatcher
from aiogram.dispatcher.middlewares import BaseMiddleware
from aiogram.dispatcher.filters import Command
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.storage import FSMContextProxy
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils import executor
import sqlite3
import datetime
import pytz
from yookassa import Configuration, Payment
import time
import uuid
import requests

# Устанавливаем нужную временную зону
local_timezone = pytz.timezone('Europe/Moscow')

openai.api_key = ""
model_engine = "text-davinci-003"

YUKASSA_SECRET_KEY = ""
YUKASSA_SHOP_ID = ""


# Инициализация бота
bot = Bot(token="", proxy="http://proxy.server:3128")
dp = Dispatcher(bot, storage=MemoryStorage())
dp.middleware.setup(LoggingMiddleware())




# ================ Кнопки для главного меню ==============

buy_button = types.InlineKeyboardButton(text="Купить запросы", callback_data="buy_limits")
get_dream_button = types.InlineKeyboardButton(text="Истолковать сон", callback_data="get_dream")
get_limits_button = types.InlineKeyboardButton(text="Остаток запросов", callback_data="get_limits")
set_alarm_button = types.InlineKeyboardButton(text="Будильник", callback_data="set_alarm")
send_review_button = types.InlineKeyboardButton(text="Оставить отзыв", callback_data="send_review")

# ================ Конец кнопок для главного меню ==============


# ================ Кнопки для возврата в главного меню ==============

cancel_button = types.InlineKeyboardButton("Вернуться в главное меню", callback_data="cancel")

# ================ Конец кнопки для возврата в главного меню ==============


# ================ Кнопки промо-кода ==============

promocode_button = types.InlineKeyboardButton("Ввести промо-код", callback_data="promocode")
promocode_restart_button = types.InlineKeyboardButton("Попробовать ещё раз", callback_data="promocode")

# ================ Конец кнопок промо-кода ==============


#Функция активации промо-кода
def getPromocode(user_id, codeName):
    # Подключаемся к базе данных
    conn = sqlite3.connect("check_dream.db")
    cursor = conn.cursor()

    # Создаем клавиатуру
    promoCodeMarkup = types.InlineKeyboardMarkup()

    # Проверяем наличие промо-кода в таблице main_promocode
    cursor.execute("SELECT * FROM main_promocode WHERE codeName=?", (codeName,))
    promo_row = cursor.fetchone()

    if promo_row is None:
        # Промо-код не найден
        response = "Введенный промо-код не найден"
        promoCodeMarkup.add(promocode_restart_button)
        promoCodeMarkup.add(cancel_button)

    else:
        # Проверяем статус активации промо-кода
        isActive = promo_row[3]
        if isActive:
            # Промо-код уже активирован
            response = f"Указанный промо-код <b>{codeName}</b> уже активирован. Повторное использование промо-кодов недопустимо"
            promoCodeMarkup.add(promocode_restart_button)
            promoCodeMarkup.add(cancel_button)
        else:
            # Активируем промо-код и обновляем количество доступных запросов
            limits = promo_row[2]
            cursor.execute("UPDATE main_promocode SET isActive = 1, userID=? WHERE codeName=?", (user_id, codeName,))
            conn.commit()

            # Проверяем наличие пользователя в таблице limits
            cursor.execute("SELECT * FROM limits WHERE user_id=?", (user_id,))
            user_limits = cursor.fetchone()

            if user_limits is None:
                # Создаем запись о пользователе в таблице limits
                cursor.execute("INSERT INTO limits (user_id, promo_limits) VALUES (?, ?)", (user_id, limits))
                conn.commit()

                response = f"Промо-код <b>{codeName}</b> активирован. Количество доступных запросов - <b>{limits}</b>"
                promoCodeMarkup.add(get_dream_button)
                promoCodeMarkup.add(cancel_button)
            else:
                # Обновляем количество доступных запросов пользователя
                promo_limits = user_limits[5] + limits
                cursor.execute("UPDATE limits SET promo_limits=? WHERE user_id=?", (promo_limits, user_id))
                conn.commit()

                response = f"Промо-код <b>{codeName}</b> активирован. Количество доступных запросов - <b>{promo_limits}</b>"

    # Закрываем соединение с базой данных
    conn.close()

    return bot.send_message(user_id, response, reply_markup=promoCodeMarkup, parse_mode="HTML")


# Фоновая функция отправки уведомлений
async def send_hello_to_user():

    # Получаем текущее время в формате ЧЧ:ММ
    now = datetime.datetime.now(local_timezone)
    nowTime = now.strftime("%H:%M")

    # Подключаемся к базе данных
    conn = sqlite3.connect('check_dream.db')
    cursor = conn.cursor()

    # Получаем записи из таблицы notifications с текущим временем
    cursor.execute("SELECT user_id, notification_type FROM notifications WHERE time = ?", (nowTime,))
    rows = cursor.fetchall()

    # Закрываем соединение с базой данных
    conn.close()

    get_dream_markup = types.InlineKeyboardMarkup()
    get_dream_button = types.InlineKeyboardButton(text="Истолковать сон", callback_data="get_dream")
    get_dream_markup.add(get_dream_button)

    for user_id, notification_type in rows:
        if notification_type == 'morning':
            message = "🌕 Солнце уже взашло! Расскажи, что принесла тебе эта ночь? "
            await bot.send_message(user_id, message, reply_markup=get_dream_markup)
        elif notification_type == 'evening':
            message = "🌑 Доброй ночи и волшебных снов. Пусть звезды будут твоими проводниками в мире сновидений."
            await bot.send_message(user_id, message, reply_markup=get_dream_markup)


# Функция для проверки и уменьшения лимитов запросов пользователя
async def process_user_limits(user_id):
    # Подключение к базе данных
    conn = sqlite3.connect('check_dream.db')
    cursor = conn.cursor()

    # Проверяем наличие записи в базе для данного пользователя
    cursor.execute("SELECT * FROM limits WHERE user_id = ?", (user_id,))
    existing_row = cursor.fetchone()

    if existing_row:
        # Если запись уже существует, сначала проверяем promo_limits
        promo_limits = existing_row[5]
        if promo_limits > 0:
            # Уменьшаем количество promo_limits на 1
            cursor.execute("UPDATE limits SET promo_limits = ? WHERE user_id = ?", (promo_limits - 1, user_id))

        else:
            # Если promo_limits пуст, проверяем количество свободных лимитов
            free_limits = existing_row[2]
            if free_limits > 0:
                # Уменьшаем количество свободных лимитов на 1
                cursor.execute("UPDATE limits SET free_limits = ? WHERE user_id = ?", (free_limits - 1, user_id))

            else:
                # Если свободных лимитов нет, проверяем количество платных лимитов
                payed_limits = existing_row[3]
                if payed_limits > 0:
                    # Уменьшаем количество платных лимитов на 1
                    cursor.execute("UPDATE limits SET payed_limits = ? WHERE user_id = ?", (payed_limits - 1, user_id))
                else:
                    end_limits_markup = types.InlineKeyboardMarkup()
                    end_limits_markup.add(buy_button)

                    # Если нет свободных и платных лимитов, предлагаем купить новые
                    await bot.send_message(user_id, "У вас закончились лимиты запросов, но вы всегда можете приобрести новые.", reply_markup=end_limits_markup)
                    conn.close()
                    return False

    else:
        # Если записи нет, добавляем новую запись
        current_date = datetime.datetime.now().date()
        cursor.execute("INSERT INTO limits (user_id, free_limits, payed_limits, first_input_date) VALUES (?, ?, ?, ?)",
               (user_id, 2, 0, current_date))

    # Сохранение изменений и закрытие соединения
    conn.commit()
    conn.close()

    return True

# Состояние для ожидания ввода времени утреннего уведомления
class TimeInput(StatesGroup):
    waiting_for_time = State()

# Состояние для ожидания ввода времени вечернего уведомления
class EveningTimeInput(StatesGroup):
    waiting_for_time = State()

# Состояние для ожидания ввода сообщения с описанием сна
class MainMessageInput(StatesGroup):
    waiting_for_dream = State()

# Состояние для ожидания ввода отзыва
class ReviewInput(StatesGroup):
    waiting_for_review = State()


# Состояние для ожидания ввода отзыва
class ConfirmAction(StatesGroup):
    waiting_for_confirm = State()


# Состояние для ожидания ввода промо-кода
class PromoCodeInput(StatesGroup):
    waiting_for_code = State()



#MiddleWare для остановки состояний
class FinishStateMiddleware(BaseMiddleware):
    async def on_pre_process_message(self, message: types.Message, data: dict):
        if message.is_command():
            state = dp.current_state(chat=message.from_user.id, user=message.from_user.id)
            async with state.proxy() as proxy:
                if proxy.state:
                    await state.finish()

#Регистрация middleware
dp.middleware.setup(FinishStateMiddleware())

# Функция для проверки существования включенных уведомлений у пользователя
def check_notifications_exist(user_id):
    conn = sqlite3.connect('check_dream.db')
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM notifications WHERE user_id = ?", (user_id,))
    existing_rows = cursor.fetchall()

    conn.close()

    return len(existing_rows) > 0


# Функция для получения данных об установленном будильнике
def get_notification_times(user_id):
    conn = sqlite3.connect("check_dream.db")
    cursor = conn.cursor()

    cursor.execute("SELECT time FROM notifications WHERE user_id = ? AND notification_type = 'morning'", (user_id,))
    morning_time = cursor.fetchone()

    cursor.execute("SELECT time FROM notifications WHERE user_id = ? AND notification_type = 'evening'", (user_id,))
    evening_time = cursor.fetchone()

    conn.close()

    return [morning_time[0], evening_time[0]] if morning_time and evening_time else []


# Функция для сохранения уведомлений в базу данных
def save_notifications(userId, time_input, notification_type):
    # Подключение к базе данных
        conn = sqlite3.connect('check_dream.db')
        cursor = conn.cursor()

        # Проверяем наличие записи в базе для данного пользователя и типа уведомления
        cursor.execute("SELECT * FROM notifications WHERE user_id = ? AND notification_type = ?", (userId,notification_type,))
        existing_row = cursor.fetchone()

        if existing_row:
            # Если запись уже существует, обновляем её
            update_query = "UPDATE notifications SET time = ? WHERE user_id = ? AND notification_type = ?"
            cursor.execute(update_query, (time_input, userId, notification_type))
        else:
            # Если записи нет, добавляем новую
            insert_query = "INSERT INTO notifications (user_id, notification_type, time) VALUES (?, ?, ?)"
            cursor.execute(insert_query, (userId, notification_type, time_input))

        # Сохранение изменений и закрытие соединения
        conn.commit()
        conn.close()

# Inline-кнопки для подтверждения удаления
confirm_kb = types.InlineKeyboardMarkup(row_width=2)
confirm_yes_btn = types.InlineKeyboardButton(text="Да", callback_data="confirm_yes")
confirm_no_btn = types.InlineKeyboardButton(text="Нет", callback_data="confirm_no")
confirm_kb.add(confirm_yes_btn, confirm_no_btn)

# Inline-кнопки после удаления
after_delete_kb = types.InlineKeyboardMarkup(row_width=2)
set_alarm_btn = types.InlineKeyboardButton(text="Задать будильник", callback_data="set_alarm")
after_delete_kb.add(set_alarm_btn, cancel_button)


# Обработчик для прмо-кода
@dp.callback_query_handler(lambda callback_query: callback_query.data == "promocode")
async def set_code(callback_query: types.CallbackQuery):
    wait_promocode_markup = types.InlineKeyboardMarkup().add(cancel_button)
    await callback_query.message.answer("Введите промокод:", reply_markup=wait_promocode_markup)
    await PromoCodeInput.waiting_for_code.set() # Устанавливаем состояние ожидания ввода отзыва

# Обработчик текстового сообщения после команды /set_review
@dp.message_handler(state=PromoCodeInput.waiting_for_code, content_types=types.ContentTypes.TEXT)
async def process_promocode(message: types.Message, state: FSMContext):
    #Вызов функции активации промо-кода
    await getPromocode(message.from_user.id, message.text)

    await state.finish()


# Обработчик для диалога удаления будильников
@dp.callback_query_handler(lambda callback_query: callback_query.data == "del_notifications")
async def delete_notifications(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.message.answer("Вы уверены, что хотите удалить все уведомления от будильника?", reply_markup=confirm_kb)
    await ConfirmAction.waiting_for_confirm.set()
    await callback_query.answer()


# Обработчик для логики удаления будильника
@dp.callback_query_handler(lambda callback_query: callback_query.data in ["confirm_yes", "confirm_no"], state=ConfirmAction.waiting_for_confirm)
async def process_confirmation(callback_query: types.CallbackQuery, state: FSMContext):
    async with state.proxy() as data:
        if callback_query.data == "confirm_yes":
            # Подключение к базе данных
            conn = sqlite3.connect('check_dream.db')
            cursor = conn.cursor()

            # Удаление уведомлений для текущего пользователя
            user_id = callback_query.from_user.id
            cursor.execute("DELETE FROM notifications WHERE user_id = ?", (user_id,))
            conn.commit()
            conn.close()

            await callback_query.message.answer("Все будильники для вас удалены. Вы всегда можете создать новый, нажав на кнопку ниже.", reply_markup=after_delete_kb)
        elif callback_query.data == "confirm_no":
            await callback_query.message.delete()

    await state.finish()

# Обработчик для отзывов
@dp.callback_query_handler(lambda callback_query: callback_query.data == "send_review")
async def set_review(callback_query: types.CallbackQuery):
    review_markup = types.InlineKeyboardMarkup().add(cancel_button)
    await callback_query.message.answer("Нам важно ваше мнение. Напишите пожалуйста отзыв о нашем боте", reply_markup=review_markup)
    await ReviewInput.waiting_for_review.set() # Устанавливаем состояние ожидания ввода отзыва

# Обработчик текстового сообщения после команды /set_review
@dp.message_handler(state=ReviewInput.waiting_for_review, content_types=types.ContentTypes.TEXT)
async def process_review(message: types.Message, state: FSMContext):
    review_text = message.text
    result_review_markup = types.InlineKeyboardMarkup().add(cancel_button)
    # Отправляем отзыв методом POST
    try:
        response = requests.post("http://moy-drug.ru/return_handler.php", data={"text": review_text})
        if response.status_code == 200:
            await message.answer("Спасибо за ваш отзыв! Он был отправлен нашей команде.", reply_markup=result_review_markup)
        else:
            await message.answer("Произошла ошибка при отправке отзыва. Попробуйте позже.", reply_markup=result_review_markup)
    except Exception as e:
        print(e)
        await message.answer("Произошла ошибка при отправке отзыва. Попробуйте позже.", reply_markup=result_review_markup)

    await state.finish()

# Обработчик будильника
@dp.callback_query_handler(lambda callback_query: callback_query.data == "set_alarm")
async def cmd_set_morning(query: types.CallbackQuery):

    # markup для случая, когда будильник установлен
    alarm_markup = types.InlineKeyboardMarkup(row_width=2)
    next_button = types.InlineKeyboardButton("Изменить настройки", callback_data="alarm_next")
    delete_alarm_button = types.InlineKeyboardButton("Удалить будильник", callback_data="del_notifications")
    alarm_markup.add(next_button)
    alarm_markup.add(delete_alarm_button)
    alarm_markup.add(cancel_button)

    # markup для случая, когда будильник НЕ установлен
    no_alarm_markup = types.InlineKeyboardMarkup(row_width=2)
    no_next_button = types.InlineKeyboardButton("Далее", callback_data="alarm_next")
    no_alarm_markup.add(no_next_button)
    no_alarm_markup.add(cancel_button)

    if check_notifications_exist(query.from_user.id):

        # Отправляем сообщение на случай, когда будильник уже установлен у пользователя
        await query.message.answer(f"⏰ У тебя уже установлен будильник. Я буду писать тебе каждое утро в <b>{get_notification_times(query.from_user.id)[0]}</b> и каждый вечер в <b>{get_notification_times(query.from_user.id)[1]}</b>", reply_markup=alarm_markup, parse_mode="HTML")

    else:
        # Отправляем сообщение на случай, когда будильник НЕ установлен у пользователя
        await query.message.answer("⏰ Пожелаю тебе приятных снов и доброго утра", reply_markup=no_alarm_markup)

@dp.callback_query_handler(lambda callback_query: callback_query.data == "alarm_next")
async def cmd_start(callback_query: types.CallbackQuery):
    await callback_query.message.answer("""🌌 Во сколько ты обычно засыпаешь? Укажи в формате ЧЧ:ММ (например 22:30) """)
    await EveningTimeInput.waiting_for_time.set()  # Устанавливаем состояние ожидания имени

# Обработчик на случай, когда данные провалидированы успешно для вечернего уведомления
@dp.message_handler(lambda message: validate_time(message.text.strip()), state=EveningTimeInput.waiting_for_time)
async def process_evening_valid(message: types.Message, state: FSMContext):
    evening_time_input = message.text.strip()
    userId = message.from_user.id
    save_notifications(userId, evening_time_input, "evening")

    # Записываем в data состояния то, что прислал юзер
    async with state.proxy() as data:
        data['evening_time_input'] = evening_time_input

    await message.answer("""🌅 А во сколько обычно просыпаешься? Укажи в формате ЧЧ:ММ (например 8:30)""")
    await TimeInput.waiting_for_time.set()   # Устанавливаем состояние ожидания возраста

# Обработчик на случай, когда данные не прошли валидацию для вечернего уведомления
@dp.message_handler(lambda message: not validate_time(message.text.strip()), state=EveningTimeInput.waiting_for_time)
async def process_evening_invalid(message: types.Message):
    cancel_markup = types.InlineKeyboardMarkup(row_width=2)
    cancel_markup.add(cancel_button)
    await message.answer("Неверный формат времени. Пожалуйста, введите время в формате ЧЧ:ММ (например, 20:00).", reply_markup=cancel_markup)


# Обработчик на случай, когда данные провалидированы успешно для утреннего уведомления
@dp.message_handler(lambda message: validate_time(message.text.strip()), state=TimeInput.waiting_for_time)
async def process_morning_valid(message: types.Message, state: FSMContext):
    morning_time_input = message.text.strip()
    userId = message.from_user.id
    save_notifications(userId, morning_time_input, "morning")

    # Записываем в data состояния то, что прислал юзер
    async with state.proxy() as data:
        data['morning_time_input'] = morning_time_input

        # Извлекаем данные из состояния
        morning_time_input = data['morning_time_input']
        evening_time_input = data['evening_time_input']

        next_button = types.InlineKeyboardButton("Изменить настройки", callback_data="alarm_next")

        alarm_success_markup = types.InlineKeyboardMarkup()
        alarm_success_markup.add(next_button)
        alarm_success_markup.add(cancel_button)

        await message.answer(f"🔔 Твой будильник готов.  Я буду твоим напоминанием утром в <b>{morning_time_input}</b> и вечером в <b>{evening_time_input}</b>", reply_markup=alarm_success_markup, parse_mode="HTML")

    # Завершаем состояние
    await state.finish()

# Обработчик на случай, когда данные не прошли валидацию для утреннего уведомления
@dp.message_handler(lambda message: not validate_time(message.text.strip()), state=TimeInput.waiting_for_time)
async def process_morning_invalid(message: types.Message):
    cancel_markup = types.InlineKeyboardMarkup(row_width=2)
    cancel_markup.add(cancel_button)
    await message.answer("Неверный формат времени. Пожалуйста, введите время в формате ЧЧ:ММ (например, 10:00).", reply_markup=cancel_markup)


# Функция для возврата в главное меню и сброса состояния
@dp.callback_query_handler(lambda query: query.data == "cancel", state="*")
async def cancel_state(query: types.CallbackQuery, state: FSMContext):
    await state.finish()
    main_menu_kb = types.InlineKeyboardMarkup(row_width=2)
    main_menu_kb.add(
        get_dream_button, buy_button, get_limits_button, set_alarm_button, send_review_button
    )
    await query.message.answer("Главное меню", reply_markup=main_menu_kb)
    await query.answer()  # Отправляем пустой ответ, чтобы убрать "часики" с кнопки


# Функция для возврата в главное меню и отмены оплаты
@dp.callback_query_handler(lambda query: query.data == "cancel_payment", state="*")
async def cancel_state(query: types.CallbackQuery, state: FSMContext):
    await state.finish()

    global active_tasks
    # Остановка активной задачи, если она существует
    for task in active_tasks:
        task.cancel()
    active_tasks.clear()

    main_menu_kb = types.InlineKeyboardMarkup(row_width=2)
    main_menu_kb.add(
        get_dream_button, buy_button, get_limits_button, set_alarm_button, send_review_button
    )
    await query.message.answer("Главное меню", reply_markup=main_menu_kb)
    await query.answer()  # Отправляем пустой ответ, чтобы убрать "часики" с кнопки



# Обработчик команды /start
@dp.message_handler(commands=['start'])
async def send_welcome(message: types.Message):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        get_dream_button, buy_button, get_limits_button, set_alarm_button, send_review_button
    )

    await message.reply("""🌙 Добро пожаловать в мир сновидений! 🌙

Ты на пороге таинственной вселенной. Расскажи мне о своем сне, и я, Сонник, помогу раскрыть его смысл.

Не упускай детали — они важны. Подробнее в разделе /help""", reply_markup=kb)



# Обработчик команды /help
@dp.message_handler(commands=['help'])
async def send_welcome(message: types.Message):

    cancel_markup = types.InlineKeyboardMarkup().add(cancel_button)

    await message.reply("""✨ <b>Путеводитель по миру сновидений</b>

В этой вселенной снов каждая деталь имеет значение, пожалуйста, следуй этим рекомендациям:

<b>Подробность</b>: Постарайся вспомнить все

<b>Эмоции</b>: Чувствовал ли ты грусть, радость? А может страх?

<b>Последовательность</b>: Постарайся вспомнить сон в хронологическом порядке

<b>Символы</b>: Не забудь про выделяющиеся символы или предметы, если они были


💎 <b>Преимущества Сонника</b>

Основан на знаниях профессиональных сомнологов

Точность и детальность самых сложных и запутанных снов

Учет индвидуальности пользователя и его предыдущих сновидений

Прямая расшифровка без подтекста и двусмысленности



🪄 <b>3 бесплатных запроса каждый месяц</b>""", parse_mode='HTML', reply_markup=cancel_markup)


# Функция для обновления значения payed_limits в базе данных после успешной оплаты
async def update_payed_limits(user_id, package_price):
    # Подключение к базе данных
    conn = sqlite3.connect('check_dream.db')
    cursor = conn.cursor()

    # Получаем текущее значение payed_limits
    cursor.execute("SELECT payed_limits FROM limits WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()

    if row:
        payed_limits = row[0]
        # Увеличиваем значение payed_limits на количество запросов в пакете
        cursor.execute("UPDATE limits SET payed_limits = ? WHERE user_id = ?", (int(payed_limits) + int(package_price), user_id))
        # Сохраняем изменения
        conn.commit()

    # Закрываем соединение с базой данных
    conn.close()

def create_yukassa_payment(amount, description, user_id, package_title):
    Configuration.account_id = YUKASSA_SHOP_ID
    Configuration.secret_key = YUKASSA_SECRET_KEY

    payment = Payment.create({
        "amount": {
            "value": str(amount),
            "currency": "RUB"
        },
        "confirmation": {
            "type": "redirect",
            "return_url": "https://kirillporyadin88.pythonanywhere.com",  # URL для перехода после оплаты
        },
        "capture": True,
        "description": description,
        "metadata": {
            "user_id": user_id,
            "package_title": package_title,
        },
    }, uuid.uuid4())

    return payment


@dp.callback_query_handler(lambda callback_query: callback_query.data == "get_limits")
async def get_limits(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id

    # Подключение к SQLite базе данных
    db_connection = sqlite3.connect("check_dream.db")
    cursor = db_connection.cursor()

    # Запрос для получения значений столбцов promo_limits, free_limits и payed_limits
    query = f"SELECT promo_limits, free_limits, payed_limits FROM limits WHERE user_id = ?;"

    try:
        # Выполнение запроса к базе данных
        cursor.execute(query, (user_id,))
        result = cursor.fetchone()

        if result:
            promo_limits = result[0]
            free_limits = result[1]
            payed_limits = result[2]

            limits_markup = types.InlineKeyboardMarkup(row=1)
            limits_markup.add(buy_button)
            limits_markup.add(cancel_button)

            # Проверяем наличие promo_limits
            if promo_limits > 0:
                # Если есть promo_limits, выводим их
                await callback_query.message.answer(f"На данный момент у вас:\n\n🌟 Промо-запросов - {promo_limits}\n\n🌟 Бесплатных запросов - {free_limits}\n\n💰 Оплаченных запросов - {payed_limits}", reply_markup=limits_markup)
            else:
                # Выводим только бесплатные и оплаченные
                await callback_query.message.answer(f"На данный момент у вас:\n\n🌟 Бесплатных запросов - {free_limits}\n\n💰 Оплаченных запросов - {payed_limits}", reply_markup=limits_markup)

            await callback_query.answer()
        else:
            await callback_query.message.answer("Информация о запросах не найдена.")
            await callback_query.answer()
    except Exception as e:
        await callback_query.message.answer("Произошла ошибка при получении информации о запросах.")


    # Закрытие соединения с базой данных
    cursor.close()
    db_connection.close()


# Словарь для хранения ссылок на оплату для каждого пользователя
payment_links = {}

@dp.callback_query_handler(lambda callback_query: callback_query.data == "buy_limits")
async def start_buy_limits(callback_query: types.CallbackQuery):
    keyboard_markup = types.InlineKeyboardMarkup(row_width=2)
    packages = [
        {"title": "1 запрос", "price": 29},
        {"title": "5 запросов", "price": 99},
        {"title": "15 запросов", "price": 199},
        {"title": "30 запросов", "price": 299},
    ]

    buttons = []

    for package in packages:
        callback_data = f"buy_{package['title']}_{package['price']}"
        button_text = package['title']
        button = types.InlineKeyboardButton(button_text, callback_data=callback_data)
        buttons.append(button)


    keyboard_markup.add(*buttons)
    keyboard_markup.add(promocode_button)
    keyboard_markup.add(cancel_button)

    await callback_query.message.answer("Выберите пакет запросов:", reply_markup=keyboard_markup)
    await callback_query.answer()


payment_buttons = []
# Список для хранения активных фоновых задач
active_tasks = []

@dp.callback_query_handler(lambda callback_query: callback_query.data.startswith("buy_"))
async def process_buy_callback(callback_query: types.CallbackQuery):

    # Удаляем старую ссылку на оплату, если она существует
    global payment_buttons
    if payment_buttons:
        payment_message = payment_buttons.pop()
        await bot.delete_message(chat_id=callback_query.from_user.id, message_id=payment_message)

    global active_tasks
    # Остановка активной задачи, если она существует
    for task in active_tasks:
        task.cancel()
    active_tasks.clear()


    package_data = callback_query.data.split("_")
    if len(package_data) == 3:
        package_title = package_data[1]
        package_price = int(package_data[2])

        # Создаем ссылку на оплату
        payment_response = create_yukassa_payment(package_price, f"Покупка {package_title}", callback_query.from_user.id, package_title)

        if payment_response.id:
            payment_links[callback_query.from_user.id] = payment_response.confirmation.confirmation_url

            # Генерирование inline-кнопки для оплаты
            button_text = f"Оплатить {package_title} за {package_price}р."
            payment_button = types.InlineKeyboardButton(button_text, url=payment_links[callback_query.from_user.id])
            payment_markup = types.InlineKeyboardMarkup()
            payment_markup.add(payment_button)
            payment_markup.add(cancel_button)

            payment_message = await bot.send_message(callback_query.from_user.id, "Нажмите кнопку ниже, чтобы перейти к оплате:", reply_markup=payment_markup)
            payment_message_id = payment_message.message_id
            payment_buttons.append(payment_message_id)

            # Запуск фоновой задачи для обработки платежа
            async def background_payment_task(user_id, package_title, payment_response):
                while True:
                    # Получаем информацию о платеже
                    payment_info = Payment.find_one(payment_response.id)

                    if payment_info.status == 'succeeded':
                        metadata = payment_info.metadata
                        user_id = metadata.get('user_id')
                        package_title = metadata.get('package_title')

                        await bot.send_message(user_id, f"Поздравляем! Ваш баланс пополнился на {package_title}.")

                        fin_limits = package_title.split()[0]
                        await update_payed_limits(user_id, fin_limits)
                        break
                    elif payment_info.status == 'canceled':
                        await bot.send_message(callback_query.from_user.id, f"Платеж отменен.")
                        break
                    elif payment_info.status == 'waiting_for_capture':
                        idempotence_key = str(uuid.uuid4())
                        response = Payment.capture(
                            payment_response.id,
                            {
                                "amount": {
                                    "value": f"{package_price}.00",
                                    "currency": "RUB"
                                }
                            },
                            idempotence_key)
                    else:
                        await asyncio.sleep(1)  # Добавьте паузу, чтобы не блокировать цикл

            payment_task = asyncio.create_task(background_payment_task(callback_query.from_user.id, package_title, payment_response))
            active_tasks.append(payment_task)



# Обработчик команды /get_dream
@dp.callback_query_handler(lambda callback_query: callback_query.data == "get_dream")
async def cmd_set_main(callback_query: types.CallbackQuery, state: FSMContext):
    cancel_markup = types.InlineKeyboardMarkup().add(cancel_button)
    await bot.send_message(callback_query.from_user.id, "✨ Открой мне свои ночные видения, и я осветлю их смысл", reply_markup=cancel_markup)
    await MainMessageInput.waiting_for_dream.set() #Устанавливаем состояние ожидания ввода описания для сна


# Обработчик ввода описания для сна
@dp.message_handler(state=MainMessageInput.waiting_for_dream, content_types=types.ContentTypes.TEXT)
async def process_message_input(message: types.Message, state: FSMContext):
    user_id = message.from_user.id

    # Проверяем лимиты пользователя
    if not await process_user_limits(user_id):
        return

    prompt = f'Помоги истолковать сон. Сегодня мне приснилось {message.text} К чему снится этот сон? Если мой вопрос не связан с темой толкования снов или на него нельзя дать ответ в этом контексте, то напиши, что не можешь дать ответ на этот вопрос. Если мой вопрос связан с темой сновидений, пожалуйста, напиши развернутую трактовку этого сна. Трактовки должны быть наполнены смыслом и написаны развернуто. Не пиши запутано, не используй двусмысленные формулировки, логические повторения, а также тавтологии в своих трактовках снов. Пиши всегда четко и по делу. Никогда не повторяй одни и те же слова в своих толкованиях. Если нужно повторить слово, используй синоним вместо того же слова.'

    # Отправляем уведомление о том, что бот начал печатать ответ
    await bot.send_chat_action(message.chat.id, "typing")


    response = chat_with_me(prompt)

    # Получаем количество оставшихся лимитов после обработки запроса
    left_limits = await get_user_limits(user_id)

    cancel_markup = types.InlineKeyboardMarkup().add(cancel_button)
    await bot.send_message(user_id, f"{response}\n\nОсталось запросов: {left_limits}", reply_markup=cancel_markup)




def chat_with_me(prompt):
    # Отправляем запрос на API
    response = openai.Completion.create(
        engine=model_engine,
        prompt=prompt,
        temperature=0.6,
        max_tokens=2048,
        top_p=1,
        frequency_penalty=0,
        presence_penalty=0
    )

    # Проверяем наличие ошибок
    if response.choices[0].text.startswith("ERROR:"):
        return "Извините, произошла ошибка при обработке запроса."

    # Получаем ответ от API и возвращаем его
    return response.choices[0].text.strip()


# Вспомогательная функция для получения количества оставшихся лимитов
async def get_user_limits(user_id):
    # Подключение к базе данных
    conn = sqlite3.connect('check_dream.db')
    cursor = conn.cursor()

    # Получаем запись из таблицы limits для данного пользователя
    cursor.execute("SELECT free_limits, payed_limits FROM limits WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()

    # Сохранение изменений и закрытие соединения
    conn.close()

    if row:
        # Возвращаем количество свободных лимитов, если они есть, иначе - количество платных лимитов
        return row[0] if row[0] > 0 else row[1]
    else:
        # Если записи нет, возвращаем None
        return None


# Вспомогательная функция для проверки правильности формата времени
def validate_time(input_str):
    try:
        hours, minutes = map(int, input_str.split(":"))
        if 0 <= hours <= 23 and 0 <= minutes <= 59:
            return True
        else:
            return False
    except ValueError:
        return False


# Функция для планирования уведомлений
async def schedule_hello():
    while True:
        await send_hello_to_user()
        await asyncio.sleep(60)


# Подключение к базе данных
conn = sqlite3.connect('check_dream.db')
cursor = conn.cursor()

# Функция для отправки сообщения и обновления данных
async def send_message_and_update(user_id):
    # Увеличение значения free_limits на 2
    cursor.execute("UPDATE limits SET free_limits = free_limits + 2 WHERE user_id = ?", (user_id,))
    conn.commit()

    # Отправка сообщения пользователю
    message_text = "Поздравляю! Твой баланс пополнился на 3 бесплатных запроса!"
    inline_button = types.InlineKeyboardButton("Истолковать сон", callback_data="get_dream")
    markup = types.InlineKeyboardMarkup().add(inline_button)
    await bot.send_message(user_id, message_text, reply_markup=markup)

# Функция для фоновой задачи по начислению бесплатных запросов каждый месяц
async def schedule_free_monthly_limits():
    while True:
        today = datetime.date.today()
        thirty_days_ago = today - datetime.timedelta(days=30)

        # Поиск записей в базе данных
        cursor.execute("SELECT DISTINCT user_id FROM limits WHERE first_input_date = ? AND free_limits <= 3",
                       (thirty_days_ago,))
        user_ids = cursor.fetchall()

        for user_id in user_ids:
            user_id = user_id[0]
            await send_message_and_update(user_id)

        await asyncio.sleep(86400)  # Ожидание 24 часа (в секундах)

loop = asyncio.get_event_loop()
loop.create_task(schedule_hello())
loop.create_task(schedule_free_monthly_limits())

# Запуск бота
if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
