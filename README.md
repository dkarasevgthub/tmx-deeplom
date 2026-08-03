:D

Матвик: там в alembic.ini надо будет логин пароль юзера подставить, или создать нового юзера бд
psql -U postgres

CREATE USER prozapas_user WITH PASSWORD 'zapas_zapas';
CREATE DATABASE prozapas_db
    OWNER prozapas_user
    ENCODING 'UTF8'
    LC_COLLATE 'ru_RU.UTF-8'
    LC_CTYPE 'ru_RU.UTF-8'
    TEMPLATE template0;
GRANT ALL PRIVILEGES ON DATABASE prozapas_db TO prozapas_user;
\q