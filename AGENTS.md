# AGENTS.md

Reusable Django app (`fieldlogger/`) that logs per-field changes to a `FieldLog` model. Library only: no `manage.py`, no project.

## Environment

- `.python-version` lists `3.8 … 3.13 system`; the first match (3.8) has no deps, so bare `pytest`/`tox` fail with `No module named 'django'` or a pyenv "command not found".
- Dev tools (tox, pytest, ruff, pre-commit; Django 6.0) live in the pyenv virtualenv `fieldlogger`: use `~/.pyenv/versions/fieldlogger/bin/<tool>` or `pyenv shell fieldlogger`.
- Existing tox envs under `.tox/` can be reused directly, e.g. `.tox/py313-django52/bin/python -m pytest -q`.

## Testing

- Settings: `tests.settings` (set in `pyproject.toml`); `pythonpath` includes both `.` and `fieldlogger`.
- Single test: `python -m pytest -q tests/test_m2m.py -k clear`.
- Coverage gate is `fail_under = 100` (migrations excluded). Every new branch needs a test.
- Matrix lives in `[tool.tox]` in `pyproject.toml`. CI runs `tox -f py313` (all Django versions for that Python); `-e py313` would run with no Django pin.
- `testapp` (`tests/testapp/`) has no migrations; tables are synced. Two SQLite DBs (`default`, `other`) exist for multi-db tests.
- Other databases: `tox -m postgres|mysql|mariadb|oracle` (envs `<backend>-django{61,52,42}`, Oracle only 61/52 since Django < 5.0 needs `cx_Oracle`; not in `env_list`, CI job `servers`). Needs a server from `DB_HOST`/`DB_PORT`/`DB_USER`/`DB_PASSWORD` (`TEST_DB` picks the backend, see `tests/settings.py`), e.g. `docker run -d --rm -e POSTGRES_PASSWORD=pw -p 5432:5432 postgres:16-alpine` then `DB_PASSWORD=pw tox -m postgres`; images: `mysql:8.4`, `mariadb:11`, `gvenzl/oracle-free:23-slim-faststart` (`ORACLE_PASSWORD`, user `system`). MySQL uses PyMySQL (no client libs). The coverage gate is off there (`PYTEST_ADDOPTS`); it is enforced by the SQLite matrix. Sequence bugs only show on PostgreSQL/Oracle (SQLite and MySQL follow explicit pks); Oracle stores `''` as NULL and lacks `ignore_conflicts` (skip with the `supports_ignore_conflicts` fixture).
- Backends without bulk-insert RETURNING (MySQL, Oracle, old SQLite): use the `no_returning_pks` fixture (patches the connection feature). Do not monkeypatch `db_supports_returning_pks`: Django's `bulk_create` ignores it.
- Tests mutate `settings.FIELD_LOGGER_SETTINGS` in place: use `helpers.set_config(...)` plus the `restore_settings` fixture, or call `helpers.refresh_config()` after any manual change. `override_settings` also works (handled by `setting_changed_receiver`).

## Architecture gotchas

- Config is built lazily and cached (`config.py`); signals are connected in `FieldloggerConfig.ready()` only for configured models. After changing settings at runtime: `invalidate_config()` + `connect_signals()`.
- Save-path logging: `pre_save` stashes DB state on `instance._fieldlogger_pre_instance`, `post_save` re-reads the logged fields from the DB and diffs both (never diff in-memory values: they may be expressions or unrounded). M2M uses `m2m_changed` on the through model (`_fieldlogger_pre_m2m`). Bulk ops are logged only via `FieldLoggerManager`.
- Intra-package imports form a DAG: `app_settings`/`utils`/`db` → `encoding` → `models` → `config` → `fieldlogger` → `managers`/`signals` (`apps` imports `signals` inside `ready()`). Keep it acyclic; no `TYPE_CHECKING` imports. Read raw settings via `app_settings.get_settings`, not `config`.
- Primary keys of bulk inserts (`db.py`): logs are inserted one by one where `bulk_create` cannot return pks; user models get `set_primary_keys`, which must always be followed by `reset_sequences` (explicit pks do not advance PostgreSQL/Oracle sequences).
- `FieldLog` has no FK to logged models; `FieldLoggerMixin.fieldlog_set` emulates the reverse relation.
- Loaded `FieldLog` values are converted (FKs become lazy related instances), which Django refuses to write to a JSON column; `FieldLog.save()` therefore skips `old_value`/`new_value` on existing logs unless they are in `update_fields`.
- Supports Python 3.8+ and Django 3.1–6.1: no 3.9+ syntax (ruff `target-version = "py38"`, pyupgrade `--py38-plus`), use `typing.Dict/List`, and guard version-specific Django APIs (see `GENERATED_FIELD`, `default_app_config` in `__init__.py`).
- Migrations check (system checks need Pillow, in `dev`/tox deps, for testapp's `ImageField`; add `--skip-checks` if it's missing):
  `PYTHONPATH=. django-admin makemigrations fieldlogger --check --dry-run --settings=tests.settings`
  It leaves an untracked `test_db` SQLite file in the repo root (not gitignored); delete it.

## Lint / workflow

- `pre-commit run -a` (ruff `--fix` + ruff-format, pyupgrade, rst checks for `README.rst`). The `no-commit-to-branch` hook blocks commits on `main`.
- Release: bump `version` in `pyproject.toml`, publish a GitHub release tagged `v<version>`; `publish.yml` fails if tag and version differ (PyPI trusted publishing).
