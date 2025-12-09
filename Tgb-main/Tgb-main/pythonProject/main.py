import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import sqlite3
import logging
from collections import defaultdict, deque
import tempfile
import os
import io
import matplotlib
matplotlib.use('Agg')  # Для работы без GUI
import matplotlib.pyplot as plt
import networkx as nx
import matplotlib.font_manager as fm

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

# Остальной код Database класса остается без изменений...
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

    def get_all_notes_graph(self, user_id):
        """Получение всех заметок и их связей для построения графа"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Получаем все заметки пользователя
            cursor.execute('''
                SELECT id, title FROM notes WHERE user_id = ?
            ''', (user_id,))
            notes = {row[0]: row[1] for row in cursor.fetchall()}

            # Получаем все связи между заметками
            cursor.execute('''
                SELECT from_note_id, to_note_id FROM note_links
                WHERE from_note_id IN (SELECT id FROM notes WHERE user_id = ?)
                AND to_note_id IN (SELECT id FROM notes WHERE user_id = ?)
            ''', (user_id, user_id))

            graph = defaultdict(list)
            for from_id, to_id in cursor.fetchall():
                if from_id in notes and to_id in notes:
                    graph[from_id].append(to_id)
                    graph[to_id].append(from_id)  # Для неориентированного графа

            return notes, graph

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
        KeyboardButton("🌳 Дерево заметок"),
        KeyboardButton("🖼️ Граф заметок"),
        KeyboardButton("ℹ️ Помощь")
    )
    return keyboard

def create_visualization_keyboard():
    """Создает клавиатуру для визуализации"""
    keyboard = InlineKeyboardMarkup()
    keyboard.row(
        InlineKeyboardButton("📊 Текстовое дерево", callback_data="text_tree"),
        InlineKeyboardButton("🖼️ Граф (изображение)", callback_data="image_graph")
    )
    return keyboard

def create_commands_keyboard():
    """Создает клавиатуру со всеми командами"""
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(
        KeyboardButton("/new"),
        KeyboardButton("/notes"),
        KeyboardButton("/search"),
        KeyboardButton("/tree"),
        KeyboardButton("/graph"),
        KeyboardButton("/help"),
        KeyboardButton("📋 Главное меню")
    )
    return keyboard

def create_graph_visualization_matplotlib(notes, graph):
    """Создает визуализацию графа с помощью matplotlib и networkx"""
    try:
        # Создаем граф
        G = nx.Graph()
        
        # Добавляем узлы
        for note_id, title in notes.items():
            short_title = title[:15] + '...' if len(title) > 15 else title
            G.add_node(note_id, label=f"{note_id}: {short_title}")
        
        # Добавляем ребра
        added_edges = set()
        for from_id, to_ids in graph.items():
            for to_id in to_ids:
                edge = tuple(sorted([from_id, to_id]))
                if edge not in added_edges:
                    G.add_edge(from_id, to_id)
                    added_edges.add(edge)
        
        # Настраиваем визуализацию
        plt.figure(figsize=(12, 8))
        
        # Используем spring layout для автоматического расположения
        pos = nx.spring_layout(G, k=1, iterations=50)
        
        # Рисуем граф
        nx.draw_networkx_nodes(G, pos, node_color='lightblue', 
                              node_size=800, alpha=0.9)
        nx.draw_networkx_edges(G, pos, edge_color='gray', 
                              alpha=0.6, width=2)
        
        # Подписи узлов
        labels = {node: f"{node}" for node in G.nodes()}
        nx.draw_networkx_labels(G, pos, labels, font_size=8, font_weight='bold')
        
        # Легенда с названиями заметок
        legend_text = "Легенда:\n" + "\n".join([f"{k}: {v[:20]}..." if len(v) > 20 else f"{k}: {v}" 
                                              for k, v in list(notes.items())[:10]])
        
        plt.figtext(0.02, 0.02, legend_text, fontsize=8, 
                   bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8))
        
        plt.title("Граф заметок Zettelkasten", fontsize=14, pad=20)
        plt.axis('off')
        plt.tight_layout()
        
        # Сохраняем в байты
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        buf.seek(0)
        plt.close()
        
        return buf
        
    except Exception as e:
        logger.error(f"Ошибка при создании графа matplotlib: {e}")
        return None

def create_simple_text_graph(notes, graph):
    """Создает простую текстовую визуализацию графа"""
    if not graph:
        return "🔗 Связи между заметками отсутствуют."
    
    result = "🕸️ Текстовая карта связей:\n\n"
    
    for note_id, title in notes.items():
        connections = graph.get(note_id, [])
        if connections:
            short_title = title[:20] + "..." if len(title) > 20 else title
            result += f"📄 {note_id}: {short_title}\n"
            result += "   ↳ Связан с: "
            connected_titles = []
            for conn_id in connections:
                conn_title = notes.get(conn_id, "?")
                short_conn_title = conn_title[:15] + "..." if len(conn_title) > 15 else conn_title
                connected_titles.append(f"{conn_id}: {short_conn_title}")
            
            result += ", ".join(connected_titles) + "\n\n"
    
    return result

def save_graph_to_bytes(graph_bytes):
    """Возвращает байты графа"""
    return graph_bytes.getvalue() if graph_bytes else None

# Остальные функции (build_notes_tree, send_notes_list и т.д.) остаются без изменений...
def build_notes_tree(notes, graph):
    """Построение текстового представления дерева заметок"""
    visited = set()
    trees = []

    # Находим корневые узлы (заметки без входящих связей или с минимальным количеством связей)
    for note_id in notes:
        if note_id not in visited:
            tree_text = build_tree_from_root(note_id, notes, graph, visited)
            if tree_text:
                trees.append(tree_text)

    if not trees:
        return "🔗 Связи между заметками отсутствуют."

    return "\n\n".join(trees)

def build_tree_from_root(root_id, notes, graph, visited, level=0, prefix=""):
    """Рекурсивное построение дерева из корневого узла"""
    if root_id in visited:
        return ""

    visited.add(root_id)
    note_title = notes[root_id]

    # Обрезаем длинные названия
    display_title = note_title[:25] + "..." if len(note_title) > 25 else note_title

    if level == 0:
        line = f"📄 {display_title}"
    else:
        line = prefix + "├── " + display_title

    children = [child_id for child_id in graph[root_id] if child_id not in visited]

    result = [line]

    for i, child_id in enumerate(children):
        is_last = i == len(children) - 1
        new_prefix = prefix + ("    " if level > 0 else "") + ("└── " if is_last else "├── ")
        child_tree = build_tree_from_root(
            child_id, notes, graph, visited, level + 1,
            prefix + ("    " if level > 0 else "") + ("    " if is_last else "│   ")
        )
        if child_tree:
            result.append(child_tree)

    return "\n".join(result)

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
            created_at = note[4] if len(note) > 4 else note[2]
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

def split_long_message(text, max_length=4000):
    """Разбивает длинное сообщение на части"""
    parts = []
    while len(text) > max_length:
        split_pos = text.rfind('\n', 0, max_length)
        if split_pos == -1:
            split_pos = max_length
        parts.append(text[:split_pos])
        text = text[split_pos:].lstrip()
    parts.append(text)
    return parts

# Команды бота остаются без изменений...
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
/tree - Текстовое дерево заметок
/graph - Граф заметок (изображение)
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
/tree - Текстовое дерево связей
/graph - Визуальный граф заметок

🔹 Визуализация:
• 📊 Текстовое дерево - для быстрого просмотра
• 🖼️ Граф - изображение сети заметок

🔹 Как работать с заметками:
1. Создавайте атомарные заметки (одна идея = одна заметка)
2. Связывайте связанные заметки между собой
3. Используйте теги для категоризации
4. Просматривайте граф для поиска новых идей

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

@bot.message_handler(commands=['tree'])
def tree_command(message):
    """Обработчик команды /tree для текстового дерева"""
    try:
        user_id = message.from_user.id
        notes, graph = db.get_all_notes_graph(user_id)

        if not notes:
            bot.send_message(
                message.chat.id,
                "📭 У вас пока нет заметок для построения дерева.",
                reply_markup=create_main_keyboard()
            )
            return

        # Построение дерева в виде текста
        tree_text = build_notes_tree(notes, graph)

        if len(tree_text) > 4000:
            # Если дерево слишком большое, разбиваем на части
            parts = split_long_message(tree_text)
            for i, part in enumerate(parts):
                prefix = f"📊 Дерево заметок (часть {i + 1}/{len(parts)}):\n\n"
                bot.send_message(
                    message.chat.id,
                    prefix + part,
                    parse_mode='HTML',
                    reply_markup=create_main_keyboard() if i == len(parts) - 1 else None
                )
        else:
            bot.send_message(
                message.chat.id,
                f"📊 Дерево заметок:\n\n{tree_text}",
                reply_markup=create_main_keyboard()
            )

    except Exception as e:
        logger.error(f"Ошибка при построении дерева заметок: {e}")
        bot.send_message(
            message.chat.id,
            "❌ Произошла ошибка при построении дерева заметок.",
            reply_markup=create_main_keyboard()
        )

@bot.message_handler(commands=['graph'])
def graph_command(message):
    """Обработчик команды /graph для визуализации графа"""
    try:
        user_id = message.from_user.id
        notes, graph = db.get_all_notes_graph(user_id)

        if not notes:
            bot.send_message(
                message.chat.id,
                "📭 У вас пока нет заметок для построения графа.",
                reply_markup=create_main_keyboard()
            )
            return

        if len(notes) == 1:
            bot.send_message(
                message.chat.id,
                "ℹ️ У вас только одна заметка. Создайте еще заметки и свяжите их для построения графа.",
                reply_markup=create_main_keyboard()
            )
            return

        # Показываем клавиатуру выбора типа визуализации
        bot.send_message(
            message.chat.id,
            "🎨 Выберите тип визуализации:",
            reply_markup=create_visualization_keyboard()
        )

    except Exception as e:
        logger.error(f"Ошибка при построении графа: {e}")
        bot.send_message(
            message.chat.id,
            "❌ Произошла ошибка при построении графа заметок.",
            reply_markup=create_main_keyboard()
        )

# Обработчики кнопок главного меню
@bot.message_handler(
    func=lambda message: message.text in ["📝 Новая заметка", "📚 Мои заметки", "🔍 Поиск", "🌳 Дерево заметок", 
                                          "🖼️ Граф заметок", "ℹ️ Помощь", "⚡ Все команды", "📋 Главное меню", "❌ Отмена"])
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
    elif message.text == "🌳 Дерево заметок":
        tree_command(message)
    elif message.text == "🖼️ Граф заметок":
        graph_command(message)
    elif message.text == "ℹ️ Помощь":
        help_command(message)
    elif message.text == "⚡ Все команды":
        bot.send_message(
            message.chat.id,
            "⚡ Все доступные команды:\n\n"
            "📝 /new - Создать новую заметку\n"
            "📚 /notes - Показать все заметки\n"
            "🔍 /search - Поиск по заметкам\n"
            "🌳 /tree - Текстовое дерево заметок\n"
            "🖼️ /graph - Граф заметок (изображение)\n"
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
            send_notes_list(chat_id, user_id, message_id)

        elif data == "text_tree":
            bot.answer_callback_query(call.id, "📊 Строим текстовое дерево...")
            tree_command(call.message)

        elif data == "image_graph":
            bot.answer_callback_query(call.id, "🖼️ Создаем граф...")
            # Создаем визуализацию графа
            user_id = call.from_user.id
            notes, graph = db.get_all_notes_graph(user_id)
            
            if not notes:
                bot.edit_message_text(
                    "📭 У вас пока нет заметок.",
                    chat_id,
                    message_id
                )
                return

            # Пробуем создать граф через matplotlib
            graph_bytes = create_graph_visualization_matplotlib(notes, graph)
            
            if graph_bytes:
                bot.send_photo(
                    chat_id,
                    graph_bytes.getvalue(),
                    caption="🖼️ Граф ваших заметок\n\n"
                           "Каждый узел - заметка, линии показывают связи между идеями.",
                    reply_markup=create_main_keyboard()
                )
                bot.delete_message(chat_id, message_id)
            else:
                # Если не удалось создать изображение, показываем текстовую версию
                text_graph = create_simple_text_graph(notes, graph)
                bot.edit_message_text(
                    f"🖼️ Граф заметок (текстовая версия):\n\n{text_graph}",
                    chat_id,
                    message_id,
                    reply_markup=create_main_keyboard()
                )

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

        note_id = note[0]
        title = note[2]
        content = note[3]
        tags = note[4]
        created_at = note[5]

        linked_notes = db.get_linked_notes(note_id)

        text = f"""📄 <b>{title}</b>

{content}

🏷️ <b>Теги:</b> {tags if tags else "нет"}
📅 <b>Создана:</b> {created_at[:16]}
🔗 <b>Связанные заметки:</b> {len(linked_notes)}"""

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

    if chat_id in user_states:
        state = user_states[chat_id]['state']

        if state == 'waiting_title':
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
            try:
                tags = message.text.strip()
                note_id = db.add_note(
                    user_id=user_id,
                    title=user_states[chat_id]['title'],
                    content=user_states[chat_id]['content'],
                    tags=tags if tags else None
                )

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
        # Обработка поиска
        if message.text and not message.text.startswith('/'):
            try:
                notes = db.search_notes(user_id, message.text)
                if notes:
                    text = f"🔍 Результаты поиска по запросу '{message.text}':\n\n"
                    for note in notes:
                        note_id, title, content, tags = note
                        text += f"📄 {title}\n"
                        if content:
                            preview = content[:50] + "..." if len(content) > 50 else content
                            text += f"   {preview}\n"
                        text += f"   🏷️ {tags if tags else 'нет тегов'}\n"
                        text += f"   👁️ /view_{note_id}\n\n"
                    
                    bot.send_message(
                        chat_id,
                        text,
                        reply_markup=create_main_keyboard()
                    )
                else:
                    bot.send_message(
                        chat_id,
                        f"🔍 По запросу '{message.text}' ничего не найдено.",
                        reply_markup=create_main_keyboard()
                    )
            except Exception as e:
                logger.error(f"Ошибка при поиске: {e}")
                bot.send_message(
                    chat_id,
                    "❌ Произошла ошибка при поиске.",
                    reply_markup=create_main_keyboard()
                )

if __name__ == "__main__":
    logger.info("🤖 Zettelkasten Bot запущен...")
    print("Бот запущен. Нажмите Ctrl+C для остановки.")
    
    # Проверяем наличие библиотек для визуализации
    try:
        import matplotlib.pyplot as plt
        import networkx as nx
        print("✅ Matplotlib и NetworkX доступны для визуализации")
    except ImportError as e:
        print(f"❌ Библиотеки для визуализации не установлены: {e}")
        print("Установите: pip install matplotlib networkx")
    
    bot.infinity_polling()