from unittest.mock import MagicMock, patch

from safi_app import bootstrap


def test_initialize_runs_demo_policies_and_local_admin_without_name_error():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    cursor.fetchone.return_value = None

    with patch.object(bootstrap.db, "get_policy", return_value={"id": "p"}), \
         patch.object(bootstrap.db, "get_db_connection", return_value=conn), \
         patch.object(bootstrap.Config, "ENABLE_LOCAL_LOGIN", True), \
         patch.object(bootstrap.Config, "LOCAL_ADMIN_USERNAME", "admin"), \
         patch.object(bootstrap.Config, "LOCAL_ADMIN_PASSWORD", "secret"):
        bootstrap.initialize()

    sql_calls = [str(call.args[0]) for call in cursor.execute.call_args_list if call.args]
    assert any("INSERT INTO users" in s and "'local_admin'" in s for s in sql_calls)
