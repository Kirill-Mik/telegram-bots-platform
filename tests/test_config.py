"""Тесты конфигурации, error-handler и планировщика botcore. Офлайн."""

import pytest
from botcore import Config, PeriodicScheduler, parse_admin_ids, setup_error_handler


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    """Уводим cwd в пустую папку, чтобы load_dotenv не подцепил чей-то .env."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    monkeypatch.delenv("DB_PATH", raising=False)
    monkeypatch.delenv("DEFAULT_LANG", raising=False)
    monkeypatch.delenv("ADMIN_IDS", raising=False)


class TestConfig:
    def test_load_with_token(self, monkeypatch):
        monkeypatch.setenv("BOT_TOKEN", "  123:abc  ")
        cfg = Config.load(default_db_path="data/x.db")
        assert cfg.bot_token == "123:abc"
        assert cfg.db_path == "data/x.db"
        assert cfg.default_lang == "ru"

    def test_missing_token_raises(self):
        with pytest.raises(RuntimeError, match="BOT_TOKEN"):
            Config.load()

    def test_env_overrides(self, monkeypatch):
        monkeypatch.setenv("BOT_TOKEN", "t")
        monkeypatch.setenv("DB_PATH", "custom/path.db")
        monkeypatch.setenv("DEFAULT_LANG", "EN")
        cfg = Config.load(default_db_path="data/x.db")
        assert cfg.db_path == "custom/path.db"
        assert cfg.default_lang == "en"

    def test_dotenv_file_is_read(self, monkeypatch, tmp_path):
        (tmp_path / ".env").write_text("BOT_TOKEN=from_file\n", encoding="utf-8")
        cfg = Config.load()
        assert cfg.bot_token == "from_file"


class TestParseAdminIds:
    def test_mixed_separators_and_garbage(self, monkeypatch):
        monkeypatch.setenv("ADMIN_IDS", " 1, 2;3 , abc, ")
        assert parse_admin_ids() == {1, 2, 3}

    def test_empty(self):
        assert parse_admin_ids() == set()


class TestErrorHandler:
    def test_installs_on_dispatcher(self):
        """Smoke: error-handler вешается на Dispatcher без ошибок."""
        from aiogram import Dispatcher

        dp = Dispatcher()
        setup_error_handler(dp, "test-bot")
        # у observer появился хотя бы один зарегистрированный хендлер
        assert dp.errors.handlers


class TestPeriodicScheduler:
    def test_first_run_is_scheduled(self):
        """Регрессия: у интервального джоба должен быть next_run_time (не пауза)."""
        sched = PeriodicScheduler()

        async def job():
            pass

        sched.add_interval_job(job, job_id="j1", minutes=30, first_run_delay=5)
        jobs = sched._scheduler.get_jobs()
        assert len(jobs) == 1
        assert jobs[0].next_run_time is not None

    def test_requires_interval(self):
        sched = PeriodicScheduler()

        async def job():
            pass

        with pytest.raises(ValueError):
            sched.add_interval_job(job, job_id="j2")
