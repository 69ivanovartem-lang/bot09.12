from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional
import sqlite3
import logging
from datetime import datetime


class UserRepository:
    def __init__(self, db_path: str = "users.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Инициализация базы данных"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        username TEXT,
                        first_name TEXT,
                        last_name TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                conn.commit()
        except Exception as e:
            logging.error(f"Error initializing database: {e}")

    def add_user(self, user_id: int, username: str, first_name: str, last_name: str) -> bool:
        """Добавление пользователя в БД"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO users (user_id, username, first_name, last_name)
                    VALUES (?, ?, ?, ?)
                ''', (user_id, username, first_name, last_name))
                conn.commit()
                return True
        except Exception as e:
            logging.error(f"Error adding user {user_id}: {e}")
            return False

    def get_user(self, user_id: int) -> Optional[tuple]:
        """Получение пользователя по ID"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
                return cursor.fetchone()
        except Exception as e:
            logging.error(f"Error getting user {user_id}: {e}")
            return None

    def get_all_users(self) -> List[tuple]:
        """Получение всех пользователей"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM users ORDER BY created_at DESC')
                return cursor.fetchall()
        except Exception as e:
            logging.error(f"Error getting all users: {e}")
            return []

    def delete_user(self, user_id: int) -> bool:
        """Удаление пользователя по ID"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM users WHERE user_id = ?', (user_id,))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logging.error(f"Error deleting user {user_id}: {e}")
            return False

    def get_users_count(self) -> int:
        """Получение количества пользователей"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT COUNT(*) FROM users')
                return cursor.fetchone()[0]
        except Exception as e:
            logging.error(f"Error getting users count: {e}")
            return 0


# Pydantic модели
class UserCreate(BaseModel):
    user_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None


class UserResponse(BaseModel):
    user_id: int
    username: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    created_at: Optional[str]


class UsersResponse(BaseModel):
    users: List[UserResponse]
    total: int


class StatsResponse(BaseModel):
    total_users: int
    database_path: str


# Создание FastAPI приложения
app = FastAPI(
    title="Telegram Bot API",
    description="API для управления пользователями телеграм бота",
    version="1.0.0"
)


# Зависимость для получения репозитория
def get_user_repository() -> UserRepository:
    return UserRepository()


# Эндпоинты
@app.get("/")
async def root():
    """Корневой эндпоинт"""
    return {"message": "Telegram Bot API Server", "status": "running"}


@app.post("/users/", response_model=dict)
async def create_user(
        user: UserCreate,
        repo: UserRepository = Depends(get_user_repository)
):
    """Создание нового пользователя"""
    success = repo.add_user(
        user_id=user.user_id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name
    )

    if not success:
        raise HTTPException(status_code=500, detail="Failed to create user")

    return {"message": "User created successfully", "user_id": user.user_id}


@app.get("/users/{user_id}", response_model=UserResponse)
async def get_user(
        user_id: int,
        repo: UserRepository = Depends(get_user_repository)
):
    """Получение пользователя по ID"""
    user_data = repo.get_user(user_id)

    if not user_data:
        raise HTTPException(status_code=404, detail="User not found")

    return UserResponse(
        user_id=user_data[0],
        username=user_data[1],
        first_name=user_data[2],
        last_name=user_data[3],
        created_at=user_data[4] if len(user_data) > 4 else None
    )


@app.get("/users/", response_model=UsersResponse)
async def get_all_users(repo: UserRepository = Depends(get_user_repository)):
    """Получение всех пользователей"""
    users_data = repo.get_all_users()
    total = repo.get_users_count()

    users = []
    for user_data in users_data:
        users.append(UserResponse(
            user_id=user_data[0],
            username=user_data[1],
            first_name=user_data[2],
            last_name=user_data[3],
            created_at=user_data[4] if len(user_data) > 4 else None
        ))

    return UsersResponse(users=users, total=total)


@app.delete("/users/{user_id}")
async def delete_user(
        user_id: int,
        repo: UserRepository = Depends(get_user_repository)
):
    """Удаление пользователя по ID"""
    success = repo.delete_user(user_id)

    if not success:
        raise HTTPException(status_code=404, detail="User not found")

    return {"message": "User deleted successfully"}


@app.get("/stats/", response_model=StatsResponse)
async def get_stats(repo: UserRepository = Depends(get_user_repository)):
    """Получение статистики"""
    total_users = repo.get_users_count()

    return StatsResponse(
        total_users=total_users,
        database_path=repo.db_path
    )


@app.get("/health/")
async def health_check():
    """Проверка здоровья сервера"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


# Запуск сервера
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)