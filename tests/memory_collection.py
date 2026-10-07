from types import SimpleNamespace

from pymongo.errors import DuplicateKeyError


class MemoryCollection:
    def __init__(self, *documents):
        self.documents = {document["_id"]: dict(document) for document in documents}

    def insert_one(self, document):
        if document["_id"] in self.documents:
            raise DuplicateKeyError("E11000 duplicate key")
        self.documents[document["_id"]] = dict(document)

    def find_one(self, criteria, projection=None, **kwargs):
        return next((dict(doc) for doc in self.documents.values() if _matches(doc, criteria)), None)

    def find_one_and_update(self, criteria, update, **kwargs):
        document = next((doc for doc in self.documents.values() if _matches(doc, criteria)), None)
        if document is None:
            return None
        before = dict(document)
        _apply(document, update)
        return before

    def update_one(self, criteria, update, upsert=False, **kwargs):
        document = next((doc for doc in self.documents.values() if _matches(doc, criteria)), None)
        if document is None and upsert:
            document = {key: value for key, value in criteria.items() if not isinstance(value, dict)}
            self.documents[document["_id"]] = document
        elif document is None:
            return SimpleNamespace(matched_count=0, modified_count=0)
        _apply(document, update)
        return SimpleNamespace(matched_count=1, modified_count=1)

    def update_many(self, criteria, update, **kwargs):
        matched = [doc for doc in self.documents.values() if _matches(doc, criteria)]
        for document in matched:
            _apply(document, update)
        return SimpleNamespace(matched_count=len(matched), modified_count=len(matched))

    def delete_one(self, criteria, **kwargs):
        document = next((doc for doc in self.documents.values() if _matches(doc, criteria)), None)
        if document is not None:
            del self.documents[document["_id"]]


OPERATORS = {
    "$gt": lambda value, bound: value is not None and value > bound,
    "$gte": lambda value, bound: value is not None and value >= bound,
    "$lte": lambda value, bound: value is not None and value <= bound,
    "$ne": lambda value, bound: value != bound,
}


def _matches(document, criteria):
    for key, expected in criteria.items():
        value = document.get(key)
        if isinstance(expected, dict):
            if not all(OPERATORS[op](value, bound) for op, bound in expected.items()):
                return False
        elif value != expected:
            return False
    return True


def _apply(document, update):
    document.update(update.get("$set", {}))
    for key, amount in update.get("$inc", {}).items():
        document[key] = document.get(key, 0) + amount
