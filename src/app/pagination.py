from pymongo.collection import Collection


def paginate(collection: Collection, page: int, page_size: int):
    skip = (page - 1) * page_size
    items = list(collection.find().skip(skip).limit(page_size))
    total = collection.estimated_document_count()
    return {
        "page": page,
        "pageSize": page_size,
        "total": total,
        "items": items,
    }
