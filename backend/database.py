from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from .config import DATABASE_URL, POOL_MAX

pool = ConnectionPool(DATABASE_URL, min_size=2, max_size=POOL_MAX,
                      open=False, kwargs={'row_factory': dict_row}, timeout=10)
