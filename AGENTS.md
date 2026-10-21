# AGENTS.md

Reusable Django app (`fieldlogger/`) that logs per-field changes to a `FieldLog` model. Library only: no `manage.py`, no project.

## Environment

- `.python-version` lists `3.10 … 3.14 system`; the first match (3.10) has no deps, so bare `pytest`/`tox` fail with `No module named 'django'` or a pyenv "command not found".
- Dev tools (tox, pytest, ruff, pre-commit; Django 6.0) live in the pyenv virtualenv `fieldlogger`: use `~/.pyenv/versions/fieldlogger/bin/<tool>` or `pyenv shell fieldlogger`.
- Existing tox envs under `.tox/` can be reused directly, e.g. `.tox/py313-django52/bin/python -m pytest -q`.

## Testing

- Settings: `tests.settings` (set in `pyproject.toml`); `pythonpath` includes both `.` and `fieldlogger`.
- Single test: `python -m pytest -q tests/test_m2m.py -k clear`.
- Coverage gate is `fail_under = 100` (migrations excluded). Every new branch needs a test.
- Matrix lives in `[tool.tox]` in `pyproject.toml`. CI runs `tox -f py313` (all Django versions for that Python); `-e py313` would run with no Django pin.
- `testapp` (`tests/testapp/`) has no migrations; tables are synced. Two SQLite DBs (`default`, `other`) exist for multi-db tests.
- Other databases: `tox -m postgres|mysql|mariadb|oracle` (envs `<backend>-django{61,52,42}`, Oracle only 61/52 since Django < 5.0 needs `cx_Oracle`; not in `env_list`, CI job `servers`). Needs a server from `DB_HOST`/`DB_PORT`/`DB_USER`/`DB_PASSWORD` (`TEST_DB` picks the backend, see `tests/settings.py`), e.g. `docker run -d --rm -e POSTGRES_PASSWORD=pw -p 5432:5432 postgres:16-alpine` then `DB_PASSWORD=pw tox -m postgres`; images: `mysql:8.4`, `mariadb:11`, `gvenzl/oracle-free:23-slim-faststart` (`ORACLE_PASSWORD`, user `system`). MySQL uses PyMySQL (no client libs). The coverage gate is off there (`PYTEST_ADDOPTS`); it is enforced by the SQLite matrix. Sequence bugs only show on PostgreSQL/Oracle (SQLite and MySQL follow explicit pks); Oracle stores `''` as NULL, reads NULL text columns back as `''` (so test `actor_id`/`actor_username` for falsiness, never `is None`) and lacks `ignore_conflicts` (skip with the `supports_ignore_conflicts` fixture).
- Backends without bulk-insert RETURNING (MySQL, Oracle, old SQLite): use the `no_returning_pks` fixture (patches the connection feature). Do not monkeypatch `db_supports_returning_pks`: Django's `bulk_create` ignores it.
- Tests mutate `settings.FIELD_LOGGER_SETTINGS` in place: use `helpers.set_config(...)` plus the `restore_settings` fixture, or call `helpers.refresh_config()` after any manual change. `override_settings` also works (handled by `setting_changed_receiver`).
- `tests.settings` installs `django.contrib.auth`/`contenttypes` only so `test_actor.py` has users; the library must work without them. `settings_no_auth.py` checks that in a subprocess (`test_works_without_django_contrib_auth`), so never import auth models at module level in `fieldlogger/` (`get_user_model()` is called lazily).

## Architecture gotchas

- Config is built lazily and cached (`config.py`); signals are connected in `FieldloggerConfig.ready()` only for configured models. After changing settings at runtime: `invalidate_config()` + `connect_signals()`.
- Save-path logging: `pre_save` stashes DB state on `instance._fieldlogger_pre_instance`, `post_save` re-reads the logged fields from the DB and diffs both (never diff in-memory values: they may be expressions or unrounded). M2M uses `m2m_changed` on the through model (`_fieldlogger_pre_m2m`). Bulk ops are logged only via `FieldLoggerQuerySet` (`managers.py`), which `FieldLoggerManager` returns; override queryset methods there, not on the manager, or chained calls (`using()`, `filter()`, async variants) bypass them. `QuerySet.update()` is not logged.
- Version-specific code paths (e.g. `update_conflicts`, Django 4.1+) still need 100% coverage on every tox env: keep them in helpers that are unit-tested on all versions, or in single-statement expressions.
- Intra-package imports form a DAG: `app_settings`/`utils`/`db`/`context` → `encoding` → `models` → `callbacks` → `config` → `fieldlogger` → `managers`/`signals` (`apps` imports `signals` inside `ready()`; `middleware` only imports `context`). Keep it acyclic; no `TYPE_CHECKING` imports. Read raw settings via `app_settings.get_settings`, not `config`. `__init__` re-exports `disable_logging`/`set_actor` from `context`, so `context` must never import Django (the package is imported before the app registry is ready).
- Who made the change (`set_actor()`, `FieldLoggerMiddleware`): `fieldlogger._save_logs`, the one place logs are inserted, reads `context.current_actor()` once per operation and only when there are logs, so a lazy `request.user` is not loaded for requests that log nothing. The user is referenced without a FK (`actor_id` text plus an `actor_username` snapshot): a FK would make every install need a user model and break with `FieldLog` routed to another database. `remote_addr` is validated with `ipaddress` before saving (PostgreSQL's `inet` would reject a malformed value and fail the user's own save). `log_actor`/`log_remote_addr` are scoped options (global `LOG_*` key, app and model lowercase keys) resolved per model into `ModelConfig` by `config._all_scopes`, like `fail_silently`; `_save_logs` takes the model's config, and `log_actor` is checked before the user is evaluated. Any new scoped option belongs there too.
- `disable_logging()` (`context.py`) is a `ContextVar` switch checked by the signal receivers (pre and post, so no previous state is read) and at the top of the queryset's bulk methods, where it acts as `log_fields=False`. Direct calls to `log_fields()`/`log_m2m_fields()` ignore it. Any new automatic logging path must check `logging_disabled()` too.
- Lookups over an unbounded list of pks (`field__in=...`) must go through `db.batches()`: SQLite before 3.32 accepts 999 parameters per query and a single huge `IN` made the user's own operation fail. `in_bulk()` already batches. Test with the `batch_size_2` fixture (`tests/test_batching.py`).
- Primary keys of bulk inserts (`db.py`): logs are inserted one by one where `bulk_create` cannot return pks; user models get `reserve_primary_keys`, which reserves the keys from the pk sequence on PostgreSQL/Oracle (never assign explicit pks there without it: they do not advance the sequence) and falls back to `MAX(pk)` elsewhere, where concurrent bulk inserts can collide.
- `FieldLog`'s JSON fields always use `encoding.Encoder`/`Decoder`, whose `__new__` returns the configured `ENCODER`/`DECODER` instead; never pass the configured classes to the fields, or migrations would depend on the settings.
- `FieldLog` has no FK to logged models; `FieldLoggerMixin.fieldlog_set` emulates the reverse relation. Keep it a plain `property` (a new QuerySet per access, like Django's reverse managers): as a `cached_property` it returned stale results after its first evaluation, `refresh_from_db()` did not clear it, and it kept the pk of its first access (`None` before saving). The `cached_property`s of `FieldLog` are fine: a log does not change.
- Loaded `FieldLog` values are converted (FKs become lazy related instances), which Django refuses to write to a JSON column; `FieldLog.save()` therefore skips `old_value`/`new_value` on existing logs unless they are in `update_fields`.
- Supports Python 3.10+ and Django 4.0–6.1: builtin generics, `collections.abc` and `X | None` (quoted forward refs too: `"FieldLog | None"`), but no 3.11+ syntax (ruff `target-version = "py310"`, pyupgrade `--py310-plus`, which leaves quoted refs alone). Guard version-specific Django APIs (see `GENERATED_FIELD`, the `django.VERSION` check in `FieldLoggerQuerySet.bulk_create`, and `FieldLog.from_db`'s `**kwargs` for 6.1's `fetch_mode`).
- Migrations check (system checks need Pillow, in `dev`/tox deps, for testapp's `ImageField`; add `--skip-checks` if it's missing):
  `PYTHONPATH=. django-admin makemigrations fieldlogger --check --dry-run --settings=tests.settings`
  It leaves untracked `test_db` and `test_db_other` SQLite files in the repo root (not gitignored); delete them.

## Lint / workflow

- `pre-commit run -a` (ruff `--fix` + ruff-format, pyupgrade, rst checks for `README.rst`). The `no-commit-to-branch` hook blocks commits on `main`.
- Release: bump `version` in `pyproject.toml`, publish a GitHub release tagged `v<version>`; `publish.yml` fails if tag and version differ (PyPI trusted publishing).
