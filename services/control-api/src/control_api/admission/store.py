"""Atomic admission transactions with equivalent memory and Firestore adapters."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from threading import RLock
from typing import Any, Protocol, TypeVar

from google.cloud import firestore

Document = dict[str, Any]
T = TypeVar("T")


class Transaction(Protocol):
    def get(self, path: str) -> Document | None: ...
    def put(self, path: str, document: Document) -> None: ...


class Store(Protocol):
    def transact(self, operation: Callable[[Transaction], T]) -> T: ...
    def list(self, collection: str, *, after: str = "", limit: int = 50) -> list[Document]: ...
    def check_ready(self) -> None: ...


class MemoryTransaction:
    def __init__(self, documents: dict[str, Document]) -> None:
        self.documents = documents

    def get(self, path: str) -> Document | None:
        return deepcopy(self.documents.get(path))

    def put(self, path: str, document: Document) -> None:
        self.documents[path] = deepcopy(document)


class MemoryStore:
    """Test adapter only: commit all writes, including audit, or none."""

    def __init__(self) -> None:
        self._documents: dict[str, Document] = {}
        self._lock = RLock()

    def transact(self, operation: Callable[[Transaction], T]) -> T:
        with self._lock:
            tx = MemoryTransaction(deepcopy(self._documents))
            result = operation(tx)
            self._documents = tx.documents
            return result

    def list(self, collection: str, *, after: str = "", limit: int = 50) -> list[Document]:
        prefix = collection + "/"
        with self._lock:
            return [
                {**deepcopy(value), "record_id": path.removeprefix(prefix)}
                for path, value in sorted(self._documents.items())
                if path.startswith(prefix)
                and "/" not in path.removeprefix(prefix)
                and path.removeprefix(prefix) > after
            ][:limit]

    def check_ready(self) -> None:
        return None


class FirestoreTransaction:
    def __init__(self, client: firestore.Client, transaction: Any) -> None:
        self._client = client
        self._transaction = transaction
        self._writes: dict[str, Document] = {}

    def get(self, path: str) -> Document | None:
        # Buffer writes so all server reads occur before writes in the Firestore transaction.
        if path in self._writes:
            return deepcopy(self._writes[path])
        document = self._client.document(path).get(transaction=self._transaction)
        if not document.exists:
            return None
        result = document.to_dict()
        if result is None:
            raise RuntimeError("Admission document is corrupt.")
        return dict(result)

    def put(self, path: str, document: Document) -> None:
        self._writes[path] = deepcopy(document)

    def flush(self) -> None:
        for path, document in self._writes.items():
            self._transaction.set(self._client.document(path), document)


class FirestoreStore:
    def __init__(self, client: firestore.Client) -> None:
        self._client = client

    def transact(self, operation: Callable[[Transaction], T]) -> T:
        @firestore.transactional
        def run(transaction: Any) -> T:
            tx = FirestoreTransaction(self._client, transaction)
            result = operation(tx)
            tx.flush()
            return result

        result: T = run(self._client.transaction())
        return result

    def list(self, collection: str, *, after: str = "", limit: int = 50) -> list[Document]:
        query = self._client.collection(collection).order_by("__name__").limit(limit)
        if after:
            query = query.start_after(
                {"__name__": self._client.collection(collection).document(after)}
            )
        documents: list[Document] = []
        for item in query.stream():
            document = item.to_dict()
            if not document:
                raise RuntimeError("Admission document is corrupt.")
            documents.append({**dict(document), "record_id": item.id})
        return documents

    def check_ready(self) -> None:
        self._client.document("admission_metadata/bootstrap").get()
