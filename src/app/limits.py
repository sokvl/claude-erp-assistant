"""Request bounds. Every value here exists to keep input inside what BSON can encode."""

# The invariant is the PRODUCT: (MAX_PAGE - 1) * MAX_PAGE_SIZE is the largest
# $skip we can emit, and it must stay under the int64 ceiling (~9.2e18) or
# pymongo raises OverflowError while encoding. Currently ~1e7. Raising either
# constant means re-checking that product.
MAX_PAGE = 100_000
MAX_PAGE_SIZE = 100

# Domain caps. Real catalog maxima are 192GB, 1307 TFLOPS and $27,999, so these
# leave room for several hardware generations while still rejecting nonsense.
MAX_VRAM_GB = 1024
MAX_TFLOPS = 100_000.0
MAX_PRICE = 10_000_000.0

# Longest real vocabulary value is "Western Digital" (15 chars).
MAX_TEXT_LENGTH = 64

# The controlled tag vocabulary has 6 values and $in is set-valued, so no
# legitimate request needs more than this.
MAX_USE_CASES = 8

QUERY_TIMEOUT_MS = 5_000

DEFAULT_TOOL_PAGE_SIZE = 10
MAX_TOOL_PAGE_SIZE = 25

MAX_CHAT_MESSAGE_LENGTH = 4_000
MAX_CONVERSATIONS = 1_000
MAX_CONVERSATION_TURNS = 20
