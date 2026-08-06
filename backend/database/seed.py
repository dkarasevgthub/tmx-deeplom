from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Role, RolePermission, UserAccount, Warehouse

DATABASE_URL = "postgresql://prozapas_user:prozapas_secure_pwd@localhost:5432/prozapas_db"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

def seed_data():
    db = SessionLocal()
    try:
        # 1. Роли
        if not db.query(Role).first():
            roles = [
                Role(code='manager', label='Менеджер'),
                Role(code='stockman', label='Кладовщик'),
                Role(code='admin', label='Администратор')
            ]
            db.add_all(roles)
            db.commit()
            print("✅ Роли добавлены")

        # 2. Матрица прав (ТОЧНО по разделу 4 backend-spec.md)
        if not db.query(RolePermission).first():
            sections = ['orders', 'shipping', 'receiving', 'catalog', 'stock', 'users']
            permissions_map = {
                'orders':    {'manager': (True, True),  'stockman': (True, False), 'admin': (True, True)},
                'shipping':  {'manager': (True, False), 'stockman': (True, True),  'admin': (True, True)},
                'receiving': {'manager': (True, False), 'stockman': (True, True),  'admin': (True, True)},
                'catalog':   {'manager': (True, True),  'stockman': (True, False), 'admin': (True, True)},
                'stock':     {'manager': (True, False), 'stockman': (True, True),  'admin': (True, True)},
                'users':     {'manager': (False, False),'stockman': (False, False),'admin': (True, True)}
            }
            
            perms = []
            for section in sections:
                for role_code, (view, edit) in permissions_map[section].items():
                    role = db.query(Role).filter(Role.code == role_code).first()
                    perms.append(RolePermission(role_id=role.id, section=section, can_view=view, can_edit=edit))
            
            db.add_all(perms)
            db.commit()
            print("✅ Матрица прав добавлена")

        # 3. Склад
        if not db.query(Warehouse).first():
            db.add(Warehouse(code="128", name="Склад №1", is_own=True))
            db.commit()
            print("✅ Склад добавлен")

        # 4. Админ
        admin_role = db.query(Role).filter(Role.code == 'admin').first()
        if admin_role and not db.query(UserAccount).filter(UserAccount.email == 'admin@prozapas.ru').first():
            db.add(UserAccount(
                full_name='Главный Админ',
                email='admin@prozapas.ru',
                password_hash='$argon2id$placeholder', # В реальном API хешируется аргон2
                role_id=admin_role.id
            ))
            db.commit()
            print("✅ Администратор добавлен")

    except Exception as e:
        print(f"❌ Ошибка: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    print("Начинаем заполнение БД...")
    seed_data()
    print("Готово!")