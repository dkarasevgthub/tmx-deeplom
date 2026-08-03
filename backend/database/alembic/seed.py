# seed.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


DATABASE_URL = "postgresql://prozapas_user:your_secure_password@localhost:5432/prozapas_db"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

def seed_data():
    db = SessionLocal()
    try:
        # 1. Создаем роли
        if not db.query(Role).first():
            roles = [
                Role(code='manager', label='Менеджер'),
                Role(code='stockman', label='Кладовщик'),
                Role(code='admin', label='Администратор')
            ]
            db.add_all(roles)
            db.commit()
            print("Роли добавлены.")

        admin_role = db.query(Role).filter(Role.code == 'admin').first()
        if admin_role and not db.query(UserAccount).filter(UserAccount.email == 'admin@prozapas.ru').first():
            admin = UserAccount(
                full_name='Главный Админ',
                email='admin@prozapas.ru',
                password_hash='$argon2id$...',
                role_id=admin_role.id
            )
            db.add(admin)
            db.commit()
            print("Администратор добавлен.")
            

        
    finally:
        db.close()

if __name__ == "__main__":
    print("Начинаем заполнение БД...")
    seed_data()
    print("Готово!")