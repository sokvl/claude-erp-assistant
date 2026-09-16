"""Static product catalog for the (imaginary) hardware distributor.

Prices are wholesale/distributor unit prices in USD, not consumer retail
prices - this fits the B2B customer base (WAL-MAR, SYSC, BEN E, ...) and
the invoice total range ($0.72 - $668k) seen in seed/dataset.csv.

`tier` groups products for quantity-range selection when generating line
items (see generate_invoice_items.py) - it's a catalog-generation concern,
not a real-world product attribute.

`specs` on GPU products holds the technical fields needed to answer
capability questions like "what has >=24GB VRAM" or "what can train a
7B-parameter model" - vramGb/fp16TensorTflops for capacity/throughput,
multiGpuScaling+interconnect for whether cards can be pooled for larger
models, useCases as a coarse recommendation tag.

`specs.useCases` is a controlled vocabulary (see USE_CASE_TAGS) naming the
*kind* of workload only. Scale deliberately lives in the numeric fields
instead - vramGb, fp16TensorTflopsDense and multiGpuScaling already say how
big a model a card can handle, so encoding "small/large-model" in the tags
too would duplicate it and let the two disagree.
"""

USE_CASE_TAGS = frozenset(
    {"gaming", "inference", "fine-tuning", "training", "rendering", "hpc"}
)

PRODUCTS = [
    # --- GPUs: consumer/prosumer ---
    {"sku": "GPU-4060-8G", "name": "GeForce RTX 4060 8GB", "brand": "NVIDIA", "category": "GPU", "listPrice": 249.00, "tier": "gpu_consumer",
     "specs": {
         "architecture": "Ada Lovelace", "releaseYear": 2023, "processNodeNm": 5,
         "vramGb": 8, "memoryType": "GDDR6", "memoryBusWidthBit": 128, "memoryBandwidthGBs": 272.0,
         "coreCount": 3072, "coreType": "CUDA Cores", "tensorCoreCount": 96,
         "fp32TflopsBase": 15.1, "fp16TensorTflopsDense": 121.0,
         "tdpWatts": 115, "interconnect": "PCIe 4.0 x8", "formFactor": "PCIe add-in card",
         "multiGpuScaling": False, "useCases": ["gaming", "inference", "fine-tuning"],
     }},
    {"sku": "GPU-4070-12G", "name": "GeForce RTX 4070 12GB", "brand": "NVIDIA", "category": "GPU", "listPrice": 479.00, "tier": "gpu_consumer",
     "specs": {
         "architecture": "Ada Lovelace", "releaseYear": 2023, "processNodeNm": 5,
         "vramGb": 12, "memoryType": "GDDR6X", "memoryBusWidthBit": 192, "memoryBandwidthGBs": 504.2,
         "coreCount": 5888, "coreType": "CUDA Cores", "tensorCoreCount": 184,
         "fp32TflopsBase": 29.2, "fp16TensorTflopsDense": 233.0,
         "tdpWatts": 200, "interconnect": "PCIe 4.0 x16", "formFactor": "PCIe add-in card",
         "multiGpuScaling": False, "useCases": ["gaming", "inference", "fine-tuning"],
     }},
    {"sku": "GPU-4070TI-12G", "name": "GeForce RTX 4070 Ti 12GB", "brand": "NVIDIA", "category": "GPU", "listPrice": 699.00, "tier": "gpu_consumer",
     "specs": {
         "architecture": "Ada Lovelace", "releaseYear": 2023, "processNodeNm": 5,
         "vramGb": 12, "memoryType": "GDDR6X", "memoryBusWidthBit": 192, "memoryBandwidthGBs": 504.2,
         "coreCount": 7680, "coreType": "CUDA Cores", "tensorCoreCount": 240,
         "fp32TflopsBase": 40.1, "fp16TensorTflopsDense": 320.0,
         "tdpWatts": 285, "interconnect": "PCIe 4.0 x16", "formFactor": "PCIe add-in card",
         "multiGpuScaling": False, "useCases": ["gaming", "inference", "fine-tuning"],
     }},
    {"sku": "GPU-4080S-16G", "name": "GeForce RTX 4080 Super 16GB", "brand": "NVIDIA", "category": "GPU", "listPrice": 899.00, "tier": "gpu_consumer",
     "specs": {
         "architecture": "Ada Lovelace", "releaseYear": 2024, "processNodeNm": 5,
         "vramGb": 16, "memoryType": "GDDR6X", "memoryBusWidthBit": 256, "memoryBandwidthGBs": 736.0,
         "coreCount": 10240, "coreType": "CUDA Cores", "tensorCoreCount": 320,
         "fp32TflopsBase": 52.2, "fp16TensorTflopsDense": 418.0,
         "tdpWatts": 320, "interconnect": "PCIe 4.0 x16", "formFactor": "PCIe add-in card",
         "multiGpuScaling": False, "useCases": ["gaming", "inference", "fine-tuning"],
     }},
    {"sku": "GPU-4090-24G", "name": "GeForce RTX 4090 24GB", "brand": "NVIDIA", "category": "GPU", "listPrice": 1499.00, "tier": "gpu_consumer",
     "specs": {
         "architecture": "Ada Lovelace", "releaseYear": 2022, "processNodeNm": 5,
         "vramGb": 24, "memoryType": "GDDR6X", "memoryBusWidthBit": 384, "memoryBandwidthGBs": 1008.0,
         "coreCount": 16384, "coreType": "CUDA Cores", "tensorCoreCount": 512,
         "fp32TflopsBase": 82.6, "fp16TensorTflopsDense": 330.0,
         "tdpWatts": 450, "interconnect": "PCIe 4.0 x16", "formFactor": "PCIe add-in card",
         "multiGpuScaling": False, "useCases": ["gaming", "inference", "fine-tuning"],
     }},
    {"sku": "GPU-7700XT-12G", "name": "Radeon RX 7700 XT 12GB", "brand": "AMD", "category": "GPU", "listPrice": 389.00, "tier": "gpu_consumer",
     "specs": {
         "architecture": "RDNA 3", "releaseYear": 2023, "processNodeNm": 5,
         "vramGb": 12, "memoryType": "GDDR6", "memoryBusWidthBit": 192, "memoryBandwidthGBs": 432.0,
         "coreCount": 3456, "coreType": "Stream Processors", "tensorCoreCount": None,
         "fp32TflopsBase": 35.2, "fp16TensorTflopsDense": 70.3,
         "tdpWatts": 245, "interconnect": "PCIe 4.0 x16", "formFactor": "PCIe add-in card",
         "multiGpuScaling": False, "useCases": ["gaming", "inference"],
     }},
    {"sku": "GPU-7900XTX-24G", "name": "Radeon RX 7900 XTX 24GB", "brand": "AMD", "category": "GPU", "listPrice": 899.00, "tier": "gpu_consumer",
     "specs": {
         "architecture": "RDNA 3", "releaseYear": 2022, "processNodeNm": 5,
         "vramGb": 24, "memoryType": "GDDR6", "memoryBusWidthBit": 384, "memoryBandwidthGBs": 960.0,
         "coreCount": 6144, "coreType": "Stream Processors", "tensorCoreCount": None,
         "fp32TflopsBase": 61.4, "fp16TensorTflopsDense": 122.8,
         "tdpWatts": 355, "interconnect": "PCIe 4.0 x16", "formFactor": "PCIe add-in card",
         "multiGpuScaling": False, "useCases": ["gaming", "inference", "fine-tuning"],
     }},

    # --- GPUs: datacenter/enterprise ---
    {"sku": "GPU-L40S-48G", "name": "L40S 48GB Datacenter GPU", "brand": "NVIDIA", "category": "GPU", "listPrice": 8999.00, "tier": "enterprise",
     "specs": {
         "architecture": "Ada Lovelace", "releaseYear": 2023, "processNodeNm": 5,
         "vramGb": 48, "memoryType": "GDDR6 ECC", "memoryBusWidthBit": 384, "memoryBandwidthGBs": 864.0,
         "coreCount": 18176, "coreType": "CUDA Cores", "tensorCoreCount": 568,
         "fp32TflopsBase": 91.6, "fp16TensorTflopsDense": 362.0,
         "tdpWatts": 350, "interconnect": "PCIe 4.0 x16", "formFactor": "PCIe add-in card (dual-slot)",
         "multiGpuScaling": False, "useCases": ["inference", "fine-tuning", "rendering", "hpc"],
     }},
    {"sku": "GPU-A100-80G", "name": "A100 80GB SXM Datacenter GPU", "brand": "NVIDIA", "category": "GPU", "listPrice": 14999.00, "tier": "enterprise",
     "specs": {
         "architecture": "Ampere", "releaseYear": 2020, "processNodeNm": 7,
         "vramGb": 80, "memoryType": "HBM2e", "memoryBusWidthBit": 5120, "memoryBandwidthGBs": 2039.0,
         "coreCount": 6912, "coreType": "CUDA Cores", "tensorCoreCount": 432,
         "fp32TflopsBase": 19.5, "fp16TensorTflopsDense": 312.0,
         "tdpWatts": 400, "interconnect": "NVLink 600GB/s", "formFactor": "SXM4",
         "multiGpuScaling": True, "useCases": ["training", "inference", "hpc"],
     }},
    {"sku": "GPU-H100-80G", "name": "H100 80GB SXM Datacenter GPU", "brand": "NVIDIA", "category": "GPU", "listPrice": 27999.00, "tier": "enterprise",
     "specs": {
         "architecture": "Hopper", "releaseYear": 2022, "processNodeNm": 4,
         "vramGb": 80, "memoryType": "HBM3", "memoryBusWidthBit": 5120, "memoryBandwidthGBs": 3350.0,
         "coreCount": 16896, "coreType": "CUDA Cores", "tensorCoreCount": 528,
         "fp32TflopsBase": 67.0, "fp16TensorTflopsDense": 989.0,
         "tdpWatts": 700, "interconnect": "NVLink 900GB/s", "formFactor": "SXM5",
         "multiGpuScaling": True, "useCases": ["training", "inference", "hpc"],
     }},
    {"sku": "GPU-MI300X-192G", "name": "Instinct MI300X 192GB Accelerator", "brand": "AMD", "category": "GPU", "listPrice": 26999.00, "tier": "enterprise",
     "specs": {
         "architecture": "CDNA 3", "releaseYear": 2023, "processNodeNm": 5,
         "vramGb": 192, "memoryType": "HBM3", "memoryBusWidthBit": 8192, "memoryBandwidthGBs": 5300.0,
         "coreCount": 304, "coreType": "Compute Units", "tensorCoreCount": None, "matrixCoreCount": 1216,
         "fp32TflopsBase": 163.4, "fp16TensorTflopsDense": 1307.4,
         "tdpWatts": 750, "interconnect": "Infinity Fabric", "formFactor": "OAM",
         "multiGpuScaling": True, "useCases": ["training", "inference", "hpc"],
     }},

    # --- CPUs ---
    {"sku": "CPU-R5-7600", "name": "Ryzen 5 7600", "brand": "AMD", "category": "CPU", "listPrice": 189.00, "tier": "component"},
    {"sku": "CPU-R7-7700X", "name": "Ryzen 7 7700X", "brand": "AMD", "category": "CPU", "listPrice": 329.00, "tier": "component"},
    {"sku": "CPU-R9-7950X", "name": "Ryzen 9 7950X", "brand": "AMD", "category": "CPU", "listPrice": 549.00, "tier": "component"},
    {"sku": "CPU-I5-14600K", "name": "Core i5-14600K", "brand": "Intel", "category": "CPU", "listPrice": 259.00, "tier": "component"},
    {"sku": "CPU-I7-14700K", "name": "Core i7-14700K", "brand": "Intel", "category": "CPU", "listPrice": 389.00, "tier": "component"},
    {"sku": "CPU-I9-14900K", "name": "Core i9-14900K", "brand": "Intel", "category": "CPU", "listPrice": 579.00, "tier": "component"},
    {"sku": "CPU-XEON-SILVER-4416", "name": "Xeon Silver 4416+", "brand": "Intel", "category": "CPU", "listPrice": 1699.00, "tier": "enterprise"},
    {"sku": "CPU-XEON-GOLD-6448Y", "name": "Xeon Gold 6448Y", "brand": "Intel", "category": "CPU", "listPrice": 4299.00, "tier": "enterprise"},
    {"sku": "CPU-EPYC-9354", "name": "EPYC 9354", "brand": "AMD", "category": "CPU", "listPrice": 3899.00, "tier": "enterprise"},

    # --- Motherboards ---
    {"sku": "MB-B650-AORUS-E", "name": "B650 AORUS Elite AX", "brand": "Gigabyte", "category": "Motherboard", "listPrice": 189.00, "tier": "component"},
    {"sku": "MB-X670E-TAICHI", "name": "X670E Taichi", "brand": "ASRock", "category": "Motherboard", "listPrice": 399.00, "tier": "component"},
    {"sku": "MB-Z790-STRIX", "name": "ROG Strix Z790-E Gaming", "brand": "ASUS", "category": "Motherboard", "listPrice": 449.00, "tier": "component"},
    {"sku": "MB-EPYC-H13SSL", "name": "H13SSL-N EPYC Server Board", "brand": "Supermicro", "category": "Motherboard", "listPrice": 899.00, "tier": "enterprise"},

    # --- RAM ---
    {"sku": "RAM-DDR5-16-6000", "name": "DDR5-6000 16GB (2x8GB) Kit", "brand": "Corsair", "category": "RAM", "listPrice": 54.00, "tier": "accessory"},
    {"sku": "RAM-DDR5-32-6000", "name": "DDR5-6000 32GB (2x16GB) Kit", "brand": "Corsair", "category": "RAM", "listPrice": 94.00, "tier": "accessory"},
    {"sku": "RAM-DDR5-64-6000", "name": "DDR5-6000 64GB (2x32GB) Kit", "brand": "G.Skill", "category": "RAM", "listPrice": 179.00, "tier": "component"},
    {"sku": "RAM-DDR5-128-ECC", "name": "DDR5-4800 128GB ECC RDIMM", "brand": "Samsung", "category": "RAM", "listPrice": 449.00, "tier": "enterprise"},

    # --- Storage ---
    {"sku": "SSD-NVME-1TB", "name": "980 Pro NVMe SSD 1TB", "brand": "Samsung", "category": "Storage", "listPrice": 74.00, "tier": "accessory"},
    {"sku": "SSD-NVME-2TB", "name": "990 Pro NVMe SSD 2TB", "brand": "Samsung", "category": "Storage", "listPrice": 139.00, "tier": "component"},
    {"sku": "SSD-NVME-4TB", "name": "SN850X NVMe SSD 4TB", "brand": "Western Digital", "category": "Storage", "listPrice": 289.00, "tier": "component"},
    {"sku": "SSD-ENT-U2-7T6", "name": "PM1733 Enterprise U.2 SSD 7.68TB", "brand": "Samsung", "category": "Storage", "listPrice": 999.00, "tier": "enterprise"},

    # --- PSUs ---
    {"sku": "PSU-650W-GOLD", "name": "RM650x 650W 80+ Gold", "brand": "Corsair", "category": "PSU", "listPrice": 89.00, "tier": "accessory"},
    {"sku": "PSU-850W-GOLD", "name": "RM850x 850W 80+ Gold", "brand": "Corsair", "category": "PSU", "listPrice": 129.00, "tier": "component"},
    {"sku": "PSU-1200W-PLAT", "name": "HX1200i 1200W 80+ Platinum", "brand": "Corsair", "category": "PSU", "listPrice": 249.00, "tier": "component"},
    {"sku": "PSU-SRV-2000W", "name": "2000W Redundant Server PSU", "brand": "Supermicro", "category": "PSU", "listPrice": 599.00, "tier": "enterprise"},

    # --- Cases ---
    {"sku": "CASE-MIDTOWER", "name": "4000D Airflow Mid Tower", "brand": "Corsair", "category": "Case", "listPrice": 104.00, "tier": "accessory"},
    {"sku": "CASE-FULLTOWER", "name": "7000D Airflow Full Tower", "brand": "Corsair", "category": "Case", "listPrice": 269.00, "tier": "component"},
    {"sku": "CASE-4U-RACK", "name": "4U Rackmount Server Chassis", "brand": "Supermicro", "category": "Case", "listPrice": 449.00, "tier": "enterprise"},

    # --- Cooling ---
    {"sku": "COOL-AIR-TOWER", "name": "Peerless Assassin 120 SE Air Cooler", "brand": "Thermalright", "category": "Cooling", "listPrice": 39.00, "tier": "accessory"},
    {"sku": "COOL-AIO-240", "name": "Kraken 240 AIO Liquid Cooler", "brand": "NZXT", "category": "Cooling", "listPrice": 109.00, "tier": "accessory"},
    {"sku": "COOL-AIO-360", "name": "Kraken 360 AIO Liquid Cooler", "brand": "NZXT", "category": "Cooling", "listPrice": 159.00, "tier": "component"},

    # --- Networking ---
    {"sku": "NET-NIC-10G", "name": "10GbE PCIe Network Adapter", "brand": "Intel", "category": "Networking", "listPrice": 119.00, "tier": "component"},
    {"sku": "NET-SW-24P", "name": "24-Port Managed Gigabit Switch", "brand": "Netgear", "category": "Networking", "listPrice": 649.00, "tier": "component"},
    {"sku": "NET-SW-48P-10G", "name": "48-Port 10GbE Managed Switch", "brand": "Netgear", "category": "Networking", "listPrice": 2899.00, "tier": "enterprise"},

    # --- Monitors ---
    {"sku": "MON-27-1440-165", "name": "27in QHD 165Hz Monitor", "brand": "LG", "category": "Monitor", "listPrice": 259.00, "tier": "component"},
    {"sku": "MON-32-4K-144", "name": "32in 4K 144Hz Monitor", "brand": "LG", "category": "Monitor", "listPrice": 599.00, "tier": "component"},

    # --- Accessories ---
    {"sku": "ACC-HDMI-2M", "name": "HDMI 2.1 Cable 2m", "brand": "Cable Matters", "category": "Accessory", "listPrice": 8.50, "tier": "accessory"},
    {"sku": "ACC-DP-2M", "name": "DisplayPort 1.4 Cable 2m", "brand": "Cable Matters", "category": "Accessory", "listPrice": 9.50, "tier": "accessory"},
    {"sku": "ACC-RISER-PCIE4", "name": "PCIe 4.0 Riser Cable 20cm", "brand": "LINKUP", "category": "Accessory", "listPrice": 27.00, "tier": "accessory"},
    {"sku": "ACC-THERMAL-PASTE", "name": "Thermal Paste 5g Syringe", "brand": "Arctic", "category": "Accessory", "listPrice": 7.00, "tier": "accessory"},
    {"sku": "ACC-USB-HUB", "name": "USB-C 10-in-1 Hub", "brand": "Anker", "category": "Accessory", "listPrice": 34.00, "tier": "accessory"},
]

TIER_QTY_RANGE = {
    "accessory": (5, 150),
    "component": (2, 60),
    "gpu_consumer": (1, 30),
    "enterprise": (1, 15),
}
