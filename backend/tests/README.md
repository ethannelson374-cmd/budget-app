# Backend integration tests

The normal `pytest` run uses isolated SQLite databases. The MySQL migration and
TLS test is opt-in and skipped unless `RUN_MYSQL_INTEGRATION=true` is set.

Use a disposable, existing, completely empty MySQL schema whose name ends in
`_test`. The test refuses any other schema name, refuses disabled TLS, verifies a
non-empty negotiated TLS cipher, runs `alembic upgrade head` and `alembic check`,
then downgrades back to an empty schema.

PowerShell example:

```powershell
$env:RUN_MYSQL_INTEGRATION = 'true'
$env:TEST_DB_HOST = 'mysql.internal.example'
$env:TEST_DB_PORT = '3306'
$env:TEST_DB_NAME = 'budget_test'
$env:TEST_DB_USER = 'budget_test_runner'
$env:TEST_DB_PASSWORD = '<test-schema-password>'
$env:TEST_DB_SSL_REQUIRED = 'true'
pytest -m mysql_integration tests/test_mysql_integration.py
```

The unprefixed `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, and
`DB_SSL_REQUIRED` variables may be used instead only when no `TEST_DB_*` value is
present. The `_test`, empty-schema, and TLS guards still apply.
