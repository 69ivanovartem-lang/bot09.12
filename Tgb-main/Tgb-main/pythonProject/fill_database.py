import sqlite3

def test_bot_data():
    """Проверяет какие данные видит бот"""
    
    try:
        conn = sqlite3.connect('zettelkasten.db')
        cursor = conn.cursor()
        
        print("🔍 Проверка данных для бота:")
        
        # Проверяем заметки
        cursor.execute('SELECT id, user_id, title FROM notes')
        notes = cursor.fetchall()
        
        print(f"📝 Найдено заметок: {len(notes)}")
        for note in notes:
            print(f"   • ID: {note[0]}, User: {note[1]}, Title: {note[2]}")
        
        # Проверяем связи
        cursor.execute('SELECT from_note_id, to_note_id FROM note_links')
        links = cursor.fetchall()
        
        print(f"🔗 Найдено связей: {len(links)}")
        for link in links:
            print(f"   • {link[0]} → {link[1]}")
            
        conn.close()
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")

if __name__ == "__main__":
    test_bot_data()