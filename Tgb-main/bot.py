import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import sqlite3
import logging

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Токен бота
BOT_TOKEN = "8250247525:AAFIixru3WzZGxdPoQ-e35PvegpPSGzzn7s"

# Инициализация бота
bot = telebot.TeleBot(BOT_TOKEN)

class Database:
    def __init__(self, db_path):
        self.db_path = db_path
        self.init_db()
    
    def init_db(self):
        """Инициализация базы данных"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Таблица заметок
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tags TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица связей между заметками
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS note_links (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    from_note_id INTEGER NOT NULL,
                    to_note_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (from_note_id) REFERENCES notes (id),
                    FOREIGN KEY (to_note_id) REFERENCES notes (id)
                )
            ''')
            
            conn.commit()
    
    def add_note(self, user_id, title, content, tags=None):
        """Добавление новой заметки"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO notes (user_id, title, content, tags)
                VALUES (?, ?, ?, ?)
            ''', (user_id, title, content, tags))
            conn.commit()
            return cursor.lastrowid
    
    def get_user_notes(self, user_id):
        """Получение всех заметок пользователя"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, title, content, tags, created_at 
                FROM notes 
                WHERE user_id = ? 
                ORDER BY created_at DESC
            ''', (user_id,))
            return cursor.fetchall()
    
    def get_note(self, note_id, user_id):
        """Получение конкретной заметки"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, user_id, title, content, tags, created_at 
                FROM notes 
                WHERE id = ? AND user_id = ?
            ''', (note_id, user_id))
            return cursor.fetchone()
    
    def search_notes(self, user_id, query):
        """Поиск заметок по заголовку, содержанию и тегам"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            search_pattern = f'%{query}%'
            cursor.execute('''
                SELECT id, title, content, tags 
                FROM notes 
                WHERE user_id = ? 
                AND (title LIKE ? OR content LIKE ? OR tags LIKE ?)
                ORDER BY created_at DESC
            ''', (user_id, search_pattern, search_pattern, search_pattern))
            return cursor.fetchall()
    
    def add_link(self, from_note_id, to_note_id):
        """Добавление связи между заметками"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO note_links (from_note_id, to_note_id)
                VALUES (?, ?)
            ''', (from_note_id, to_note_id))
            conn.commit()
    
    def get_linked_notes(self, note_id):
        """Получение связанных заметок"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT n.id, n.title 
                FROM notes n
                JOIN note_links nl ON n.id = nl.to_note_id
                WHERE nl.from_note_id = ?
                UNION
                SELECT n.id, n.title 
                FROM notes n
                JOIN note_links nl ON n.id = nl.from_note_id
                WHERE nl.to_note_id = ?
            ''', (note_id, note_id))
            return cursor.fetchall()
    
    def delete_note(self, note_id, user_id):
        """Удаление заметки"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # Сначала удаляем связи
            cursor.execute('''
                DELETE FROM note_links 
                WHERE from_note_id = ? OR to_note_id = ?
            ''', (note_id, note_id))
            # Затем удаляем заметку
            cursor.execute('''
                DELETE FROM notes 
                WHERE id = ? AND user_id = ?
            ''', (note_id, user_id))
            conn.commit()
            return cursor.rowcount > 0

# Инициализация базы данных
db = Database('zettelkasten.db')

# Словарь для хранения состояния пользователей
user_states = {}

def create_main_keyboard():
    """Создает основную клавиатуру с командами"""
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(
        KeyboardButton("📝 Новая заметка"),
        KeyboardButton("📚 Мои заметки"),
        KeyboardButton("🔍 Поиск"),
        KeyboardButton("ℹ️ Помощь"),
        KeyboardButton("⚡ Все команды")
    )
    return keyboard

def create_commands_keyboard():
    """Создает клавиатуру со всеми командами"""
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(
        KeyboardButton("/new"),
        KeyboardButton("/notes"), 
        KeyboardButton("/search"),
        KeyboardButton("/help"),
        KeyboardButton("📋 Главное меню")
    )
    return keyboard

def send_notes_list(chat_id, user_id, message_id=None):
    """Отправляет список заметок пользователя"""
    try:
        notes = db.get_user_notes(user_id)

        if not notes:
            text = "📭 У вас пока нет заметок.\nСоздайте первую через /new"
            if message_id:
                bot.edit_message_text(
                    text,
                    chat_id,
                    message_id,
                    reply_markup=create_main_keyboard()
                )
            else:
                bot.send_message(
                    chat_id,
                    text,
                    reply_markup=create_main_keyboard()
            )
            return

        keyboard = InlineKeyboardMarkup()
        for note in notes:
            note_id = note[0]
            title = note[1]
            created_at = note[4] if len(note) > 4 else note[2]  # Безопасное получение даты
            # Обрезаем длинный заголовок
            display_title = title[:30] + "..." if len(title) > 30 else title
            date_str = created_at[:10] if created_at else "???"
            keyboard.add(InlineKeyboardButton(
                f"📄 {display_title} ({date_str})",
                callback_data=f"view_note_{note_id}"
            ))

        text = f"📚 Ваши заметки ({len(notes)}):\n\nНажмите на заметку для просмотра и управления:"
        
        if message_id:
            bot.edit_message_text(
                text,
                chat_id,
                message_id,
                reply_markup=keyboard
            )
        else:
            bot.send_message(
                chat_id,
                text,
                reply_markup=keyboard
            )
            
    except Exception as e:
        logger.error(f"Ошибка при получении списка заметок: {e}")
        error_text = "❌ Произошла ошибка при получении списка заметок."
        if message_id:
            bot.edit_message_text(
                error_text,
                chat_id,
                message_id,
                reply_markup=create_main_keyboard()
            )
        else:
            bot.send_message(
                chat_id,
                error_text,
                reply_markup=create_main_keyboard()
            )

# Команды
@bot.message_handler(commands=['start'])
def start_command(message):
    """Обработчик команды /start"""
    welcome_text = """
🤖 Добро пожаловать в Zettelkasten Bot!

Zettelkasten — это система ведения заметок, где каждая идея связывается с другими.

💡 Используйте кнопки ниже для быстрого доступа к командам!

📚 Основные команды:
/new - Создать новую заметку
/notes - Показать все заметки
/search - Поиск по заметкам
/help - Помощь

💡 Принципы Zettelkasten:
• Атомарность: одна заметка = одна идея
• Связность: каждая заметка связана с другими
• Нелинейность: идеи образуют сеть
    """
    bot.send_message(
        message.chat.id, 
        welcome_text,
        reply_markup=create_main_keyboard()
    )

@bot.message_handler(commands=['help'])
def help_command(message):
    """Обработчик команды /help"""
    help_text = """
📖 Помощь по Zettelkasten Bot:

🔹 Основные команды:
/new - Создать новую заметку
/notes - Список всех заметок
/search <запрос> - Поиск по заметкам

🔹 Как работать с заметками:
1. Создавайте атомарные заметки (одна идея = одна заметка)
2. Связывайте связанные заметки между собой
3. Используйте теги для категоризации
4. Регулярно пересматривайте и связывайте старые заметки

🔹 Управление заметкой:
При просмотре заметки доступны кнопки:
• 🔗 Связать - создать связь с другой заметкой
• 🗑️ Удалить - удалить заметку
• 📋 Назад - вернуться к списку

💡 Используйте кнопки для быстрого доступа к командам!
    """
    bot.send_message(
        message.chat.id, 
        help_text,
        reply_markup=create_main_keyboard()
    )

@bot.message_handler(commands=['new'])
def new_note_command(message):
    """Начало создания новой заметки"""
    user_states[message.chat.id] = {'state': 'waiting_title'}
    bot.send_message(
        message.chat.id,
        "📝 Создание новой заметки\n\nВведите заголовок заметки:",
        reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton("❌ Отмена"))
    )

@bot.message_handler(commands=['notes'])
def list_notes_command(message):
    """Показать список заметок пользователя"""
    send_notes_list(message.chat.id, message.from_user.id)

# Обработчики кнопок главного меню
@bot.message_handler(func=lambda message: message.text in ["📝 Новая заметка", "📚 Мои заметки", "🔍 Поиск", "ℹ️ Помощь", "⚡ Все команды", "📋 Главное меню", "❌ Отмена"])
def handle_main_menu_buttons(message):
    """Обработчик кнопок главного меню"""
    if message.text == "📝 Новая заметка":
        new_note_command(message)
    elif message.text == "📚 Мои заметки":
        list_notes_command(message)
    elif message.text == "🔍 Поиск":
        bot.send_message(
            message.chat.id,
            "🔍 Введите запрос для поиска:",
            reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton("📋 Главное меню"))
        )
    elif message.text == "ℹ️ Помощь":
        help_command(message)
    elif message.text == "⚡ Все команды":
        bot.send_message(
            message.chat.id,
            "⚡ Все доступные команды:\n\n"
            "📝 /new - Создать новую заметку\n"
            "📚 /notes - Показать все заметки\n"
            "🔍 /search - Поиск по заметкам\n"
            "ℹ️ /help - Помощь и инструкции\n"
            "🏠 /start - Главное меню",
            reply_markup=create_commands_keyboard()
        )
    elif message.text == "📋 Главное меню":
        bot.send_message(
            message.chat.id,
            "🏠 Главное меню",
            reply_markup=create_main_keyboard()
        )
    elif message.text == "❌ Отмена":
        if message.chat.id in user_states:
            del user_states[message.chat.id]
        bot.send_message(
            message.chat.id,
            "❌ Действие отменено.",
            reply_markup=create_main_keyboard()
        )

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    """Обработчик нажатий на inline кнопки"""
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    data = call.data

    try:
        if data.startswith("view_note_"):
            note_id = int(data.split("_")[2])
            show_note_detail(chat_id, message_id, note_id, user_id)

        elif data.startswith("link_note_"):
            note_id = int(data.split("_")[2])
            start_linking(chat_id, message_id, note_id, user_id)

        elif data.startswith("create_link_"):
            parts = data.split("_")
            from_note_id = int(parts[2])
            to_note_id = int(parts[3])
            db.add_link(from_note_id, to_note_id)
            bot.edit_message_text(
                "✅ Заметки успешно связаны!",
                chat_id,
                message_id
            )

        elif data.startswith("delete_note_"):
            note_id = int(data.split("_")[2])
            if db.delete_note(note_id, user_id):
                bot.edit_message_text(
                    "🗑️ Заметка успешно удалена!",
                    chat_id,
                    message_id
                )
            else:
                bot.edit_message_text(
                    "❌ Не удалось удалить заметку.",
                    chat_id,
                    message_id
                )

        elif data == "back_to_notes":
            # ИСПРАВЛЕНИЕ: Правильный вызов функции для возврата к списку
            send_notes_list(chat_id, user_id, message_id)
            
    except Exception as e:
        logger.error(f"Ошибка в обработчике кнопок: {e}")
        bot.answer_callback_query(call.id, "❌ Произошла ошибка при обработке запроса.")

def show_note_detail(chat_id, message_id, note_id, user_id):
    """Показать детали заметки с кнопками действий"""
    try:
        note = db.get_note(note_id, user_id)

        if not note:
            bot.edit_message_text(
                "❌ Заметка не найдена.",
                chat_id,
                message_id
            )
            return

        # Правильная распаковка данных
        note_id = note[0]
        title = note[2]
        content = note[3]
        tags = note[4]
        created_at = note[5]

        # Получаем связанные заметки
        linked_notes = db.get_linked_notes(note_id)

        text = f"""📄 <b>{title}</b>

{content}

🏷️ <b>Теги:</b> {tags if tags else "нет"}
📅 <b>Создана:</b> {created_at[:16]}
🔗 <b>Связанные заметки:</b> {len(linked_notes)}"""

        # Добавляем информацию о связанных заметках
        if linked_notes:
            text += "\n\n<b>Связи:</b>\n"
            for linked_note in linked_notes:
                linked_title = linked_note[1]
                text += f"• {linked_title}\n"

        keyboard = InlineKeyboardMarkup()
        keyboard.row(
            InlineKeyboardButton("🔗 Связать", callback_data=f"link_note_{note_id}"),
            InlineKeyboardButton("🗑️ Удалить", callback_data=f"delete_note_{note_id}")
        )
        keyboard.row(InlineKeyboardButton("📋 Назад к списку", callback_data="back_to_notes"))

        bot.edit_message_text(
            text,
            chat_id,
            message_id,
            reply_markup=keyboard,
            parse_mode='HTML'
        )
        
    except Exception as e:
        logger.error(f"Ошибка при показе деталей заметки: {e}")
        bot.edit_message_text(
            "❌ Произошла ошибка при загрузке заметки.",
            chat_id,
            message_id
        )

def start_linking(chat_id, message_id, from_note_id, user_id):
    """Начать процесс связывания заметок"""
    try:
        notes = db.get_user_notes(user_id)

        if len(notes) < 2:
            bot.edit_message_text(
                "❌ У вас недостаточно заметок для связывания.",
                chat_id,
                message_id
            )
            return

        keyboard = InlineKeyboardMarkup()
        for note in notes:
            note_id = note[0]
            title = note[1]
            if note_id != from_note_id:
                display_title = title[:30] + "..." if len(title) > 30 else title
                keyboard.add(InlineKeyboardButton(
                    f"🔗 {display_title}",
                    callback_data=f"create_link_{from_note_id}_{note_id}"
                ))

        # Добавляем кнопку отмены
        keyboard.add(InlineKeyboardButton("❌ Отмена", callback_data=f"view_note_{from_note_id}"))

        bot.edit_message_text(
            "Выберите заметку для связывания:",
            chat_id,
            message_id,
            reply_markup=keyboard
        )
        
    except Exception as e:
        logger.error(f"Ошибка при начале связывания: {e}")
        bot.edit_message_text(
            "❌ Произошла ошибка при начале связывания заметок.",
            chat_id,
            message_id
        )

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    """Обработчик всех текстовых сообщений"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Проверяем состояние пользователя
    if chat_id in user_states:
        state = user_states[chat_id]['state']
        
        if state == 'waiting_title':
            # Сохраняем заголовок и запрашиваем содержание
            user_states[chat_id] = {
                'state': 'waiting_content',
                'title': message.text
            }
            bot.send_message(
                chat_id, 
                "✍️ Теперь введите содержание заметки:",
                reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton("❌ Отмена"))
            )
            
        elif state == 'waiting_content':
            # Сохраняем содержание и запрашиваем теги
            user_states[chat_id] = {
                'state': 'waiting_tags',
                'title': user_states[chat_id]['title'],
                'content': message.text
            }
            bot.send_message(
                chat_id,
                "🏷️ Введите теги через запятую (необязательно):\nПример: программирование, python, алгоритмы",
                reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton("❌ Отмена"))
            )
            
        elif state == 'waiting_tags':
            # Сохраняем заметку в базу
            try:
                tags = message.text.strip()
                note_id = db.add_note(
                    user_id=user_id,
                    title=user_states[chat_id]['title'],
                    content=user_states[chat_id]['content'],
                    tags=tags if tags else None
                )
                
                # Очищаем состояние
                del user_states[chat_id]
                
                bot.send_message(
                    chat_id,
                    f"✅ Заметка успешно создана! (ID: {note_id})\n\n"
                    f"Теперь вы можете:\n"
                    f"• Просмотреть все заметки: /notes\n"
                    f"• Связать эту заметку с другими\n"
                    f"• Создать следующую: /new",
                    reply_markup=create_main_keyboard()
                )
                
            except Exception as e:
                logger.error(f"Ошибка при создании заметки: {e}")
                del user_states[chat_id]
                bot.send_message(
                    chat_id,
                    "❌ Произошла ошибка при создании заметки. Попробуйте снова.",
                    reply_markup=create_main_keyboard()
                )
    else:
        # Если нет активного состояния, показываем справку
        bot.send_message(
            chat_id,
            "🤖 Используйте кнопки для работы с ботом!",
            reply_markup=create_main_keyboard()
        )

if __name__ == "__main__":
    logger.info("🤖 Zettelkasten Bot запущен...")
    print("Бот запущен. Нажмите Ctrl+C для остановки.")
    bot.infinity_polling()