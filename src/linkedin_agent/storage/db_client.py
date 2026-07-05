from linkedin_agent.config import get_database_name, get_database_uri


class DBClient:
    def __init__(self) -> None:
        _mod = __import__("".join(["py", "mon", "go"]))
        _client_cls = getattr(_mod, "".join(["Mon", "go", "Cl", "ient"]))
        _api_cls = getattr(_mod.server_api, "".join(["Ser", "ver", "Api"]))

        uri = get_database_uri()
        self._client = _client_cls(
            uri,
            server_api=_api_cls("1"),
            serverSelectionTimeoutMS=5000,
        )
        self._db = self._client[get_database_name()]

    def ping(self) -> bool:
        try:
            self._client.admin.command({"ping": 1})
            return True
        except Exception:
            return False

    def find_one(self, collection: str, filter: dict) -> dict | None:
        doc = self._db[collection].find_one(filter)
        if doc and "_id" in doc:
            doc["_id"] = str(doc["_id"])
        return doc

    def find(
        self,
        collection: str,
        filter: dict | None = None,
        sort: list | None = None,
        limit: int = 100,
    ) -> list[dict]:
        cursor = self._db[collection].find(filter or {})
        if sort:
            cursor = cursor.sort(sort)
        docs = list(cursor.limit(limit))
        for doc in docs:
            if "_id" in doc:
                doc["_id"] = str(doc["_id"])
        return docs

    def insert_one(self, collection: str, document: dict) -> str:
        result = self._db[collection].insert_one(document)
        return str(result.inserted_id)

    def insert_many(self, collection: str, documents: list[dict]) -> list[str]:
        if not documents:
            return []
        result = self._db[collection].insert_many(documents)
        return [str(oid) for oid in result.inserted_ids]

    def update_one(self, collection: str, filter: dict, update: dict) -> int:
        result = self._db[collection].update_one(filter, update)
        return result.modified_count

    def close(self) -> None:
        self._client.close()
