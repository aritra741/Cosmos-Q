import urllib.parse
import pg8000

def connect(dsn, cursor_factory=None):
    parsed = urllib.parse.urlparse(dsn)
    conn = pg8000.connect(
        user=parsed.username,
        password=parsed.password,
        host=parsed.hostname,
        port=parsed.port or 5432,
        database=parsed.path.lstrip('/')
    )
    return ConnectionWrapper(conn, cursor_factory)

class ConnectionWrapper:
    def __init__(self, conn, cursor_factory):
        self.conn = conn
        self.cursor_factory = cursor_factory
        self.closed = False

    def cursor(self, cursor_factory=None):
        factory = cursor_factory or self.cursor_factory
        cursor = self.conn.cursor()
        return CursorWrapper(cursor, factory)

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        self.conn.close()
        self.closed = True

class CursorWrapper:
    def __init__(self, cursor, factory):
        self.cursor = cursor
        self.factory = factory

    @property
    def description(self):
        return self.cursor.description

    def execute(self, query, vars=None):
        if vars is not None:
            self.cursor.execute(query, vars)
        else:
            self.cursor.execute(query)

    def fetchone(self):
        row = self.cursor.fetchone()
        if not row:
            return None
        return self._to_dict(row)

    def fetchall(self):
        rows = self.cursor.fetchall()
        return [self._to_dict(r) for r in rows]

    def _to_dict(self, row):
        desc = self.cursor.description
        if not desc:
            return row
        return {desc[i][0]: row[i] for i in range(len(row))}

    def close(self):
        self.cursor.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

class extras:
    class RealDictCursor:
        pass
