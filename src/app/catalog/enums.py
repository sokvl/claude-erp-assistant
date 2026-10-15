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


class Category(StrEnum):
    ACCESSORY = "Accessory"
    CPU = "CPU"
    CASE = "Case"
    COOLING = "Cooling"
    GPU = "GPU"
    LAPTOP = "Laptop"
    MONITOR = "Monitor"
    MOTHERBOARD = "Motherboard"
    NETWORKING = "Networking"
    PSU = "PSU"
    RAM = "RAM"
    RACK = "Rack"
    SERVER = "Server"
    STORAGE = "Storage"
    UPS = "UPS"


class Brand(StrEnum):
    AMD = "AMD"
    APC = "APC"
    ASROCK = "ASRock"
    ASUS = "ASUS"
    ANKER = "Anker"
    ARCTIC = "Arctic"
    CABLE_MATTERS = "Cable Matters"
    CISCO = "Cisco"
    CORSAIR = "Corsair"
    DELL = "Dell"
    EATON = "Eaton"
    G_SKILL = "G.Skill"
    GIGABYTE = "Gigabyte"
    HP = "HP"
    HPE = "HPE"
    INTEL = "Intel"
    KINGSTON = "Kingston"
    LG = "LG"
    LINKUP = "LINKUP"
    LENOVO = "Lenovo"
    NVIDIA = "NVIDIA"
    NZXT = "NZXT"
    NETGEAR = "Netgear"
    SAMSUNG = "Samsung"
    SEAGATE = "Seagate"
    SUPERMICRO = "Supermicro"
    THERMALRIGHT = "Thermalright"
    VERTIV = "Vertiv"
    WESTERN_DIGITAL = "Western Digital"


class Architecture(StrEnum):
    ADA_LOVELACE = "Ada Lovelace"
    AMPERE = "Ampere"
    CDNA_3 = "CDNA 3"
    HOPPER = "Hopper"
    RDNA_3 = "RDNA 3"


class MemoryType(StrEnum):
    GDDR6 = "GDDR6"
    GDDR6_ECC = "GDDR6 ECC"
    GDDR6X = "GDDR6X"
    HBM2E = "HBM2e"
    HBM3 = "HBM3"


class UseCase(StrEnum):
    FINE_TUNING = "fine-tuning"
    GAMING = "gaming"
    HPC = "hpc"
    INFERENCE = "inference"
    RENDERING = "rendering"
    TRAINING = "training"


SORT_PATHS: Mapping[SortField, str] = {
    SortField.NAME: "name",
    SortField.PRICE: "listPrice",
    SortField.VRAM: "specs.vramGb",
    SortField.FP16: "specs.fp16TensorTflopsDense",
    SortField.RELEASE_YEAR: "specs.releaseYear",
}
