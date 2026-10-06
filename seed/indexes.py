"""The complete index set of every collection the app queries.

sync_indexes() drops any index not declared here, so the database holds
exactly what the queries need (tests/integration/test_query_plans.py checks
that each query shape picks the index meant for it).

invoices - equality, then sort, then range; `_id` is the pagination tiebreaker:
- (postingDate, _id): default newest-first list, posting-date ranges, and the
  covered min/max coverage lookups.
- (isOpen, postingDate, _id): status filters with the default sort and covered
  status counts. Overdue adds `dueInDate` as a residual filter; overdue is a
  subset of open, so a fourth key would widen the index for little gain.
- (totalOpen, _id): largest/smallest-first lists and amount ranges.
- customer.number and customer.nameLower: the two branches of the customer
  `$or`; nameLower is matched with a left-anchored prefix so both are bounded.
No currency index: two values, and analytics already splits per currency. No
index on `dates.clearDate`: nothing filters on it, and it is stored as null on
open invoices, which a sparse index would still hold.

charts - written by the app when the analyst draws one, read back by id and
by conversation:
- expiresAt is a TTL index (expireAfterSeconds=0), so mongod deletes a chart
  once its stored expiry passes; nothing else prunes the collection.
- (conversationId, createdAt): the recent-charts list for one conversation,
  newest first. createdAt descends in the query, which an ascending index
  serves by walking it backwards.

pending_actions - a close request the analyst raised and a human has not decided
yet. Read back only by `_id`, which is always indexed, so the TTL index is the
only one declared: it is the lifecycle, not an optimisation. Nothing else prunes
the collection, so every pending action must carry `expiresAt`. Deciding also
checks `expiresAt` in its filter, because the TTL sweep runs about once a minute
rather than exactly on expiry.

refresh_tokens - one document per issued refresh token, keyed by its SHA-256,
so the token itself is never stored. expiresAt is the TTL; familyId lets one
update revoke every token of a session when a used token is replayed.

login_attempts - failed logins per username, keyed by the username. expiresAt
is the TTL, so a lockout lifts itself once the window passes.

users - keyed by the username, so the _id index is the unique one it needs.

products - 52 documents fit in one storage page, where a collection scan beats
any index lookup, and every spec field lives on the 11 GPUs that `category`
already isolates. (category, listPrice) is kept for the primary shape: a
category with a budget or a price sort. Add more when explain shows a hot shape
examining far more documents than it returns.
"""

from pymongo import ASCENDING, IndexModel

INVOICE_INDEXES = [
    IndexModel([("dates.postingDate", ASCENDING), ("_id", ASCENDING)]),
    IndexModel([("isOpen", ASCENDING), ("dates.postingDate", ASCENDING), ("_id", ASCENDING)]),
    IndexModel([("amounts.totalOpen", ASCENDING), ("_id", ASCENDING)]),
    IndexModel([("customer.number", ASCENDING)]),
    IndexModel([("customer.nameLower", ASCENDING)]),
]

CHART_INDEXES = [
    IndexModel([("expiresAt", ASCENDING)], expireAfterSeconds=0),
    IndexModel([("conversationId", ASCENDING), ("createdAt", ASCENDING)]),
]

PENDING_ACTION_INDEXES = [
    IndexModel([("expiresAt", ASCENDING)], expireAfterSeconds=0),
]

REFRESH_TOKEN_INDEXES = [
    IndexModel([("expiresAt", ASCENDING)], expireAfterSeconds=0),
    IndexModel([("familyId", ASCENDING)]),
]

LOGIN_ATTEMPT_INDEXES = [
    IndexModel([("expiresAt", ASCENDING)], expireAfterSeconds=0),
]

PRODUCT_INDEXES = [
    IndexModel([("category", ASCENDING), ("listPrice", ASCENDING)], name="category_listPrice"),
]


def sync_indexes(collection, indexes):
    declared = {index.document["name"] for index in indexes} | {"_id_"}
    for name in collection.index_information():
        if name not in declared:
            collection.drop_index(name)
    collection.create_indexes(indexes)
