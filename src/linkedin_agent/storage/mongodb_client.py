from pymongo import MongoClient
from pymongo.server_api import ServerApi

from linkedin_agent.config import get_mongodb_database, get_mongodb_uri


class MongoDBClient:
    def __init__(self) -> None:
        uri = get_mongodb_uri()
        self._client = MongoClient(
            uri,
            server_api=ServerApi("1"),
            serverSelectionTimeoutMS=5000,
        )
        self._db = self._client[get_mongodb_database()]

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
