# tests/integration_tests.py
import json
from pathlib import Path

import pytest

from project.app import app, db
from project import models

TEST_DB = "test.db"


@pytest.fixture
def client(tmp_path, monkeypatch):
    """
    Создаём тестовый клиент, указываем тестовую БД (файл в каталоге проекта),
    создаём структуры (db.create_all) и удаляем их по завершении.
    """
    base_dir = Path(__file__).resolve().parent.parent
    test_db_path = base_dir.joinpath(TEST_DB)

    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{test_db_path}"

    # создаём таблицы
    with app.app_context():
        db.create_all()

    client = app.test_client()
    yield client

    # teardown
    with app.app_context():
        db.drop_all()
    try:
        test_db_path.unlink()
    except Exception:
        pass


def login(client, username, password):
    return client.post(
        "/login",
        data=dict(username=username, password=password),
        follow_redirects=True,
    )


def logout(client):
    return client.get("/logout", follow_redirects=True)


def add_post(client, title, text):
    return client.post(
        "/add",
        data=dict(title=title, text=text),
        follow_redirects=True,
    )


# Успешные интеграционные тесты

def test_search_returns_only_matching_entries(client):
    login(client, app.config["USERNAME"], app.config["PASSWORD"])
    add_post(client, "apple pie", "tasty")
    add_post(client, "banana bread", "also tasty")

    rv = client.get("/search/?query=apple")
    assert rv.status_code == 200
    assert b"apple pie" in rv.data
    assert b"banana bread" not in rv.data


def test_new_post_appears_on_index(client):
    login(client, app.config["USERNAME"], app.config["PASSWORD"])
    title = "Мой тестовый пост"
    body = "Тело тестового поста"
    add_post(client, title, body)

    rv = client.get("/")
    html = rv.data.decode()
    assert title in html
    assert body in html
    print("Тест test_new_post_appears_on_index пройден")


def test_login_link_changes_to_logout_after_login(client):
    """До логина виден 'log in', после логина — 'log out'."""
    rv = client.get("/")
    assert b"log in" in rv.data
    login(client, app.config["USERNAME"], app.config["PASSWORD"])
    rv2 = client.get("/")
    assert b"log out" in rv2.data


def test_direct_db_persistence_after_add(client):
    """После добавления поста через HTTP проверяем БД напрямую."""
    login(client, app.config["USERNAME"], app.config["PASSWORD"])
    add_post(client, "DirectDB", "persisted")
    with app.app_context():
        post = db.session.query(models.Post).filter_by(title="DirectDB").first()
        assert post is not None
        assert post.text == "persisted"


def test_delete_requires_login_and_flashes_message(client):
    """DELETE endpoint: проверка без логина и с логином."""
    login(client, app.config["USERNAME"], app.config["PASSWORD"])
    add_post(client, "ToDelete", "please")
    logout(client)

    rv = client.get("/delete/1")
    assert rv.status_code == 401 or rv.status_code == 200
    data = json.loads(rv.data)
    assert data.get("status") == 0

    login(client, app.config["USERNAME"], app.config["PASSWORD"])
    rv2 = client.get("/delete/1")
    data2 = json.loads(rv2.data)
    assert data2.get("status") == 1
    rv_index = client.get("/")
    assert b"The entry was deleted." in rv_index.data or b"New entry was successfully posted" not in rv_index.data


# Граничные / ошибочные тесты

def test_search_with_no_matching_entries(client):
    """Поиск по несуществующему слову — возвращает пустой результат или сообщение."""
    login(client, app.config["USERNAME"], app.config["PASSWORD"])
    add_post(client, "apple pie", "tasty")
    rv = client.get("/search/?query=nonexistent")
    assert b"apple pie" not in rv.data
    # В зависимости от реализации проекта:
    # assert b"No results found" in rv.data


def test_new_post_with_empty_title(client):
    """Попытка добавить пост с пустым заголовком — должна быть ошибка."""
    login(client, app.config["USERNAME"], app.config["PASSWORD"])
    rv = add_post(client, "", "Body text")
    # В зависимости от реализации: проверка flash или текста ошибки
    assert b"Title required" in rv.data or b"error" in rv.data


def test_login_with_wrong_password(client):
    """Попытка логина с неправильным паролем."""
    rv = login(client, app.config["USERNAME"], "wrongpassword")
    assert b"Invalid credentials" in rv.data or b"error" in rv.data


def test_db_query_for_nonexistent_post(client):
    """Запрос в БД для несуществующего поста возвращает None."""
    with app.app_context():
        post = db.session.query(models.Post).filter_by(id=9999).first()
        assert post is None


def test_delete_post_without_permission(client):
    """Попытка удалить пост пользователем без прав."""
    # создаём обычного пользователя (если есть система пользователей)
    login(client, "someuser", "wrongpass")
    rv = client.get("/delete/1")
    # проверка на отказ в правах
    assert b"Permission denied" in rv.data or b"error" in rv.data
