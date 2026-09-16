from collections.abc import Mapping
from enum import StrEnum


class SortField(StrEnum):
    NAME = "name"
    PRICE = "price"
    VRAM = "vram"
    FP16 = "fp16"
    RELEASE_YEAR = "release_year"


class SortOrder(StrEnum):
    ASC = "asc"
    DESC = "desc"


SORT_PATHS: Mapping[SortField, str] = {
    SortField.NAME: "name",
    SortField.PRICE: "listPrice",
    SortField.VRAM: "specs.vramGb",
    SortField.FP16: "specs.fp16TensorTflopsDense",
    SortField.RELEASE_YEAR: "specs.releaseYear",
}
