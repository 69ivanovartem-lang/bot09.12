import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import sqlite3
import logging
import structlog
from collections import defaultdict, deque
import tempfile
import os
import io
import networkx as nx
import math
import random
from pyvis.network import Network
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from PIL import Image
import time
import atexit
import sys
import traceback
import html

structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ]
)
logger = structlog.get_logger()

BOT_TOKEN = "8250247525:AAFIixru3WzZGxdPoQ-e35PvegpPSGzzn7s"
bot = telebot.TeleBot(BOT_TOKEN)

driver = None
def init_selenium():
    global driver
    try:
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1200,800")
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
    except Exception as e:
        logger.error("selenium_init_failed", error=str(e))
        driver = None

# Инициализация при старте
init_selenium()

class Database:
    def __init__(self, db_path):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
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
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO notes (user_id, title, content, tags)
                VALUES (?, ?, ?, ?)
            ''', (user_id, title, content, tags))
            conn.commit()
            return cursor.lastrowid

    def get_user_notes(self, user_id):
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
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, user_id, title, content, tags, created_at 
                FROM notes 
                WHERE id = ? AND user_id = ?
            ''', (note_id, user_id))
            return cursor.fetchone()

    def search_notes(self, user_id, query):
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
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO note_links (from_note_id, to_note_id)
                VALUES (?, ?)
            ''', (from_note_id, to_note_id))
            conn.commit()

    def get_linked_notes(self, note_id):
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
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                DELETE FROM note_links 
                WHERE from_note_id = ? OR to_note_id = ?
            ''', (note_id, note_id))
            cursor.execute('''
                DELETE FROM notes 
                WHERE id = ? AND user_id = ?
            ''', (note_id, user_id))
            conn.commit()
            return cursor.rowcount > 0

    def get_all_notes_graph(self, user_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, title FROM notes WHERE user_id = ?
            ''', (user_id,))
            notes = {row[0]: row[1] for row in cursor.fetchall()}
            cursor.execute('''
                SELECT from_note_id, to_note_id FROM note_links
                WHERE from_note_id IN (SELECT id FROM notes WHERE user_id = ?)
                AND to_note_id IN (SELECT id FROM notes WHERE user_id = ?)
            ''', (user_id, user_id))
            graph = defaultdict(list)
            for from_id, to_id in cursor.fetchall():
                if from_id in notes and to_id in notes:
                    graph[from_id].append(to_id)
                    graph[to_id].append(from_id)
            return notes, graph

db = Database('zettelkasten.db')
user_states = {}

def create_main_keyboard():
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
    keyboard = InlineKeyboardMarkup()
    keyboard.row(
        InlineKeyboardButton("📊 Текстовое дерево", callback_data="text_tree"),
        InlineKeyboardButton("🖼️ Граф (изображение)", callback_data="image_graph")
    )
    return keyboard

def create_commands_keyboard():
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
def create_enhanced_graph_visualization(notes, graph):
    try:
        import base64
        import html
        
        G = nx.Graph()
        node_degrees = {}
        
        for note_id, title in notes.items():
            safe_title = html.escape(title)
            node_degrees[note_id] = len(graph.get(note_id, []))
        
        added_edges = set()
        for from_id, to_ids in graph.items():
            for to_id in to_ids:
                edge = tuple(sorted([from_id, to_id]))
                if edge not in added_edges:
                    G.add_edge(from_id, to_id)
                    added_edges.add(edge)
        
        connected_nodes = [node for node in G.nodes() if G.degree(node) > 0]
        isolated_nodes = [node for node in notes.keys() if node not in connected_nodes]
        
        nt = Network(
            height="800px",
            width="1200px",
            directed=False,
            notebook=False,
            cdn_resources='in_line'
        )
        
        nt.set_options("""
        var options = {
          "physics": {
            "forceAtlas2Based": {
              "gravitationalConstant": -100,
              "centralGravity": 0.005,
              "springLength": 200,
              "springConstant": 0.18,
              "damping": 0.4,
              "avoidOverlap": 1
            },
            "maxVelocity": 50,
            "solver": "forceAtlas2Based",
            "timestep": 0.35,
            "stabilization": {
              "enabled": true,
              "iterations": 500,
              "updateInterval": 25
            }
          },
          "nodes": {
            "font": {
              "size": 16,
              "face": "Arial",
              "bold": true
            },
            "borderWidth": 2,
            "shadow": {
              "enabled": true,
              "color": "rgba(0,0,0,0.3)",
              "size": 10
            },
            "scaling": {
              "min": 20,
              "max": 60,
              "label": {
                "enabled": true,
                "min": 14,
                "max": 30
              }
            }
          },
          "edges": {
            "color": {
              "inherit": true
            },
            "smooth": {
              "type": "continuous",
              "roundness": 0.5
            },
            "width": 2
          },
          "interaction": {
            "hover": true,
            "tooltipDelay": 200
          }
        }
        """)
        
        node_number = {}
        for i, node_id in enumerate(sorted(notes.keys()), 1):
            node_number[node_id] = i
        
        max_degree = max(node_degrees.values()) if node_degrees else 1
        
        for node_id, title in notes.items():
            degree = node_degrees[node_id]
            safe_title = html.escape(title)
            short_title = safe_title[:12] + '...' if len(safe_title) > 12 else safe_title
            
            if degree > 0:
                size = 30 + (degree / max_degree) * 30
                color = '#4169E1'
                group = 1
            else:
                size = 25
                color = '#FF6B6B'
                group = 2
            
            label = f"{node_number[node_id]}"
            tooltip = f"Заметка {node_number[node_id]}: {safe_title}<br>Связей: {degree}"
            
            nt.add_node(
                node_id,
                label=label,
                title=tooltip,
                size=size,
                color=color,
                group=group,
                font={'size': 16, 'face': 'Arial', 'color': '#000000'},
                borderWidth=2,
                shadow=True
            )
        
        for edge in G.edges():
            nt.add_edge(edge[0], edge[1], width=1.5)
        
        html_content = nt.generate_html()
        
        html_path = os.path.join(tempfile.gettempdir(), f"graph_{random.randint(1000, 9999)}.html")
        
        with open(html_path, 'wb') as f:
            f.write(html_content.encode('utf-8'))
        
        driver.get(f"file://{html_path}")
        
        try:
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.common.by import By
            
            wait = WebDriverWait(driver, 20)
            
            wait.until(lambda d: d.execute_script(
                """
                try {
                    var loadingBar = document.getElementById('loading_bar');
                    var network = document.getElementById('mynetwork');
                    
                    if (!loadingBar || !network) {
                        console.log('Elements not found');
                        return false;
                    }
                    
                    var loadingHidden = 
                        (loadingBar.style.opacity === '0' || 
                         getComputedStyle(loadingBar).opacity === '0') &&
                        (loadingBar.style.display === 'none' || 
                         getComputedStyle(loadingBar).display === 'none');
                    
                    var canvas = network.querySelector('canvas');
                    var canvasReady = canvas && canvas.width > 100 && canvas.height > 100;
                    
                    console.log('Loading hidden:', loadingHidden, 'Canvas ready:', canvasReady);
                    
                    return loadingHidden && canvasReady;
                } catch(e) {
                    console.log('Error in wait condition:', e);
                    return false;
                }
                """
            ))
            
            time.sleep(1)
            
            screenshot_path = html_path.replace('.html', '.png')
            
            driver.save_screenshot(screenshot_path)
            
            with open(screenshot_path, 'rb') as f:
                image_bytes = f.read()
            
            img_io = io.BytesIO(image_bytes)
            
            try:
                os.unlink(html_path)
            except:
                pass
            
            try:
                os.unlink(screenshot_path)
            except:
                pass
            
            return img_io
            
        except Exception as e:
            logger.error("screenshot_failed", error=str(e), exc_info=True)
            
            try:
                screenshot_path = html_path.replace('.html', '.png')
                driver.save_screenshot(screenshot_path)
                
                with open(screenshot_path, 'rb') as f:
                    image_bytes = f.read()
                
                img_io = io.BytesIO(image_bytes)
                
                try:
                    os.unlink(html_path)
                except:
                    pass
                
                try:
                    os.unlink(screenshot_path)
                except:
                    pass
                
                return img_io
            except Exception as inner_e:
                logger.error("fallback_screenshot_failed", error=str(inner_e))
                return None
            
    except Exception as e:
        logger.error("graph_creation_failed", error=str(e), exc_info=True)
        return None
                
        driver.get(f"file://{html_path}")
        
        try:
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.common.by import By
            
            wait = WebDriverWait(driver, 20)
            
            wait.until(lambda d: d.execute_script(
                """
                try {
                    var loadingBar = document.getElementById('loading_bar');
                    var network = document.getElementById('mynetwork');
                    
                    if (!loadingBar || !network) {
                        console.log('Elements not found');
                        return false;
                    }
                    
                    var loadingHidden = 
                        (loadingBar.style.opacity === '0' || 
                         getComputedStyle(loadingBar).opacity === '0') &&
                        (loadingBar.style.display === 'none' || 
                         getComputedStyle(loadingBar).display === 'none');
                    
                    var canvas = network.querySelector('canvas');
                    var canvasReady = canvas && canvas.width > 100 && canvas.height > 100;
                    
                    console.log('Loading hidden:', loadingHidden, 'Canvas ready:', canvasReady);
                    
                    return loadingHidden && canvasReady;
                } catch(e) {
                    console.log('Error in wait condition:', e);
                    return false;
                }
                """
            ))
            
            time.sleep(1)
            
            screenshot_path = html_path.replace('.html', '.png')
            
            driver.save_screenshot(screenshot_path)
            
            with open(screenshot_path, 'rb') as f:
                image_bytes = f.read()
            
            img_io = io.BytesIO(image_bytes)
            
            if os.path.exists(html_path):
                try:
                    os.unlink(html_path)
                except:
                    pass
            
            if os.path.exists(screenshot_path):
                try:
                    os.unlink(screenshot_path)
                except:
                    pass
            
            return img_io
            
        except Exception as e:
            logger.error("screenshot_failed", error=str(e), exc_info=True)
            
            try:
                screenshot_path = html_path.replace('.html', '.png')
                driver.save_screenshot(screenshot_path)
                
                with open(screenshot_path, 'rb') as f:
                    image_bytes = f.read()
                
                img_io = io.BytesIO(image_bytes)
                
                if os.path.exists(html_path):
                    try:
                        os.unlink(html_path)
                    except:
                        pass
                
                if os.path.exists(screenshot_path):
                    try:
                        os.unlink(screenshot_path)
                    except:
                        pass
                
                return img_io
            except Exception as inner_e:
                logger.error("fallback_screenshot_failed", error=str(inner_e))
                return None
            
    except Exception as e:
        logger.error("graph_creation_failed", error=str(e), exc_info=True)
        return None
            
    except Exception as e:
        logger.error("graph_creation_failed", error=str(e))
        return None

def send_notes_list(chat_id, user_id, message_id=None):
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
        logger.error("notes_list_failed", error=str(e))
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

def build_notes_tree(notes, graph):
    visited = set()
    trees = []
    for note_id in notes:
        if note_id not in visited:
            tree_text = build_tree_from_root(note_id, notes, graph, visited)
            if tree_text:
                trees.append(tree_text)
    if not trees:
        return "🔗 Связи между заметками отсутствуют."
    return "\n\n".join(trees)

def build_tree_from_root(root_id, notes, graph, visited, level=0, prefix=""):
    if root_id in visited:
        return ""
    visited.add(root_id)
    note_title = notes[root_id]
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

def split_long_message(text, max_length=4000):
    parts = []
    while len(text) > max_length:
        split_pos = text.rfind('\n', 0, max_length)
        if split_pos == -1:
            split_pos = max_length
        parts.append(text[:split_pos])
        text = text[split_pos:].lstrip()
    parts.append(text)
    return parts

@bot.message_handler(commands=['start'])
def start_command(message):
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
    help_text = """
📖 Помощь по Zettelkasten Bot:
🔹 Основные команды:
/new - Создать новую заметку
/notes - Список всех заметок
/search <запрос> - Поиск по заметкам
/tree - Текстовое дерево связей
/graph - Визуальный граф заметок
🔹 Визуализация графа:
• 📏 РАЗМЕР УЗЛА: Растет с количеством связей
• 🔵 СИНИЙ: Связанные заметки
• 🔴 КРАСНЫЙ: Изолированные заметки
• 🎨 ИНТЕРАКТИВНОСТЬ: Физическое моделирование
🔹 Как работать с заметками:
1. Создавайте атомарные заметки (одна идея = одна заметка)
2. Связывайте связанные заметки между собой
3. Используйте теги для категоризации
4. Просматривайте граф для поиска новых идей
    """
    bot.send_message(
        message.chat.id,
        help_text,
        reply_markup=create_main_keyboard()
    )

@bot.message_handler(commands=['new'])
def new_note_command(message):
    user_states[message.chat.id] = {'state': 'waiting_title'}
    bot.send_message(
        message.chat.id,
        "📝 Создание новой заметки\n\nВведите заголовок заметки:",
        reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton("❌ Отмена"))
    )

@bot.message_handler(commands=['notes'])
def list_notes_command(message):
    send_notes_list(message.chat.id, message.from_user.id)

@bot.message_handler(commands=['tree'])
def tree_command(message):
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
        tree_text = build_notes_tree(notes, graph)
        if len(tree_text) > 4000:
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
        logger.error("tree_creation_failed", error=str(e))
        bot.send_message(
            message.chat.id,
            "❌ Произошла ошибка при построении дерева заметок.",
            reply_markup=create_main_keyboard()
        )

@bot.message_handler(commands=['graph'])
def graph_command(message):
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
        bot.send_message(
            message.chat.id,
            "🎨 Выберите тип визуализации:",
            reply_markup=create_visualization_keyboard()
        )
    except Exception as e:
        logger.error("graph_command_failed", error=str(e))
        bot.send_message(
            message.chat.id,
            "❌ Произошла ошибка при построении графа заметок.",
            reply_markup=create_main_keyboard()
        )

@bot.message_handler(
    func=lambda message: message.text in ["📝 Новая заметка", "📚 Мои заметки", "🔍 Поиск", "🌳 Дерево заметок", 
                                          "🖼️ Граф заметок", "ℹ️ Помощь", "⚡ Все команды", "📋 Главное меню", "❌ Отмена"])
def handle_main_menu_buttons(message):
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
            user_id = call.from_user.id
            notes, graph = db.get_all_notes_graph(user_id)
            if not notes:
                bot.edit_message_text(
                    "📭 У вас пока нет заметок.",
                    chat_id,
                    message_id
                )
                return
            bot.send_message(chat_id, "🖼️ Создаю интерактивный граф...")
            graph_bytes = create_enhanced_graph_visualization(notes, graph)
            if graph_bytes:
                bot.send_photo(
                    chat_id,
                    graph_bytes.getvalue(),
                    caption="🖼️ **Граф заметок с интерактивной визуализацией**\n\n"
                           "• 📏 **РАЗМЕР УЗЛА**: Пропорционален количеству связей\n"
                           "• 🔵 **СВЯЗАННЫЕ ЗАМЕТКИ**: Синие узлы справа\n"
                           "• 🔴 **ИЗОЛИРОВАННЫЕ ЗАМЕТКИ**: Красные узлы слева\n"
                           "• ⚡ **ФИЗИЧЕСКОЕ МОДЕЛИРОВАНИЕ**: Узлы взаимодействуют\n"
                           "• 🔢 **ЦИФРЫ**: Номера заметок\n\n"
                           "📋 Граф создан с помощью Pyvis и преобразован в изображение",
                    parse_mode='Markdown',
                    reply_markup=create_main_keyboard()
                )
                bot.delete_message(chat_id, message_id)
            else:
                bot.edit_message_text(
                    "❌ Не удалось создать граф. Попробуйте позже.",
                    chat_id,
                    message_id
                )
    except Exception as e:
        logger.error("callback_handler_failed", error=str(e))
        bot.answer_callback_query(call.id, "❌ Произошла ошибка при обработке запроса.")

def show_note_detail(chat_id, message_id, note_id, user_id):
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
        logger.error("note_detail_failed", error=str(e))
        bot.edit_message_text(
            "❌ Произошла ошибка при загрузке заметки.",
            chat_id,
            message_id
        )

def start_linking(chat_id, message_id, from_note_id, user_id):
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
        logger.error("linking_failed", error=str(e))
        bot.edit_message_text(
            "❌ Произошла ошибка при начале связывания заметок.",
            chat_id,
            message_id
        )

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
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
                logger.error("note_creation_failed", error=str(e))
                del user_states[chat_id]
                bot.send_message(
                    chat_id,
                    "❌ Произошла ошибка при создании заметки. Попробуйте снова.",
                    reply_markup=create_main_keyboard()
                )
    else:
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
                logger.error("search_failed", error=str(e))
                bot.send_message(
                    chat_id,
                    "❌ Произошла ошибка при поиске.",
                    reply_markup=create_main_keyboard()
                )

if __name__ == "__main__":
    logger.info("bot_started")
    print("=" * 70)
    print("🤖 Zettelkasten Bot запущен!")
    print("=" * 70)
    print("Визуализация графа с помощью Pyvis:")
    print("• 🎨 Интерактивный граф с физическим моделированием")
    print("• 📏 Размер узлов зависит от количества связей")
    print("• 🔵 Синие узлы: связанные заметки")
    print("• 🔴 Красные узлы: изолированные заметки")
    print("• 🖼️ Автоматическая конвертация HTML в изображение")
    print("=" * 70)
    bot.infinity_polling()