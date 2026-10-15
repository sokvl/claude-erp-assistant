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

Other categories (laptops, servers, UPS units, rack gear, enterprise storage
and so on) carry `specs` with fields of their own, since each kind of product
is described by different things. They never reuse a key a GPU filter, facet
or sort reads (architecture, memoryType, useCases, vramGb,
fp16TensorTflopsDense, releaseYear, multiGpuScaling), because a GPU-only
filter would then start matching products that are not GPUs.

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

    # --- Laptops: ready-made business fleet and mobile workstations ---
    {"sku": "LAP-DELL-7450", "name": "Latitude 7450 14\" Core Ultra 7 165U 32GB/1TB", "brand": "Dell", "category": "Laptop", "listPrice": 1649.00, "tier": "fleet",
     "specs": {"segment": "business", "cpu": "Intel Core Ultra 7 165U", "ramGb": 32, "ramKind": "LPDDR5x", "storageGb": 1024, "screenInches": 14.0,
               "resolution": "1920x1200", "graphics": "Intel Graphics", "weightKg": 1.39, "batteryWh": 57, "os": "Windows 11 Pro", "warrantyYears": 3}},
    {"sku": "LAP-DELL-5450", "name": "Latitude 5450 14\" Core Ultra 5 135U 16GB/512GB", "brand": "Dell", "category": "Laptop", "listPrice": 1049.00, "tier": "fleet",
     "specs": {"segment": "business", "cpu": "Intel Core Ultra 5 135U", "ramGb": 16, "ramKind": "DDR5", "storageGb": 512, "screenInches": 14.0,
               "resolution": "1920x1080", "graphics": "Intel Graphics", "weightKg": 1.48, "batteryWh": 54, "os": "Windows 11 Pro", "warrantyYears": 3}},
    {"sku": "LAP-DELL-PRE5690", "name": "Precision 5690 16\" Core Ultra 9 185H 64GB/2TB RTX 3500 Ada", "brand": "Dell", "category": "Laptop", "listPrice": 3899.00, "tier": "fleet",
     "specs": {"segment": "mobile workstation", "cpu": "Intel Core Ultra 9 185H", "ramGb": 64, "ramKind": "LPDDR5x", "storageGb": 2048, "screenInches": 16.0,
               "resolution": "3840x2400", "graphics": "NVIDIA RTX 3500 Ada 12GB", "weightKg": 2.25, "batteryWh": 99, "os": "Windows 11 Pro", "warrantyYears": 3}},
    {"sku": "LAP-HP-840G11", "name": "EliteBook 840 G11 14\" Core Ultra 7 155U 32GB/1TB", "brand": "HP", "category": "Laptop", "listPrice": 1599.00, "tier": "fleet",
     "specs": {"segment": "business", "cpu": "Intel Core Ultra 7 155U", "ramGb": 32, "ramKind": "DDR5", "storageGb": 1024, "screenInches": 14.0,
               "resolution": "1920x1200", "graphics": "Intel Graphics", "weightKg": 1.36, "batteryWh": 56, "os": "Windows 11 Pro", "warrantyYears": 3}},
    {"sku": "LAP-HP-450G10", "name": "ProBook 450 G10 15.6\" Core i5-1335U 16GB/512GB", "brand": "HP", "category": "Laptop", "listPrice": 849.00, "tier": "fleet",
     "specs": {"segment": "business", "cpu": "Intel Core i5-1335U", "ramGb": 16, "ramKind": "DDR4", "storageGb": 512, "screenInches": 15.6,
               "resolution": "1920x1080", "graphics": "Intel Iris Xe", "weightKg": 1.79, "batteryWh": 51, "os": "Windows 11 Pro", "warrantyYears": 1}},
    {"sku": "LAP-HP-FURY16", "name": "ZBook Fury 16 G11 Core i9-14900HX 64GB/2TB RTX 3500 Ada", "brand": "HP", "category": "Laptop", "listPrice": 4199.00, "tier": "fleet",
     "specs": {"segment": "mobile workstation", "cpu": "Intel Core i9-14900HX", "ramGb": 64, "ramKind": "DDR5", "storageGb": 2048, "screenInches": 16.0,
               "resolution": "3840x2400", "graphics": "NVIDIA RTX 3500 Ada 12GB", "weightKg": 2.6, "batteryWh": 95, "os": "Windows 11 Pro", "warrantyYears": 3}},
    {"sku": "LAP-LEN-T14G5", "name": "ThinkPad T14 Gen 5 14\" Core Ultra 7 155U 32GB/1TB", "brand": "Lenovo", "category": "Laptop", "listPrice": 1579.00, "tier": "fleet",
     "specs": {"segment": "business", "cpu": "Intel Core Ultra 7 155U", "ramGb": 32, "ramKind": "DDR5", "storageGb": 1024, "screenInches": 14.0,
               "resolution": "1920x1200", "graphics": "Intel Graphics", "weightKg": 1.37, "batteryWh": 52, "os": "Windows 11 Pro", "warrantyYears": 3}},
    {"sku": "LAP-LEN-E14G6", "name": "ThinkPad E14 Gen 6 14\" Ryzen 5 7535HS 16GB/512GB", "brand": "Lenovo", "category": "Laptop", "listPrice": 829.00, "tier": "fleet",
     "specs": {"segment": "business", "cpu": "AMD Ryzen 5 7535HS", "ramGb": 16, "ramKind": "DDR5", "storageGb": 512, "screenInches": 14.0,
               "resolution": "1920x1200", "graphics": "AMD Radeon 660M", "weightKg": 1.41, "batteryWh": 47, "os": "Windows 11 Pro", "warrantyYears": 1}},
    {"sku": "LAP-LEN-P16SG3", "name": "ThinkPad P16s Gen 3 16\" Core Ultra 7 165H 64GB/1TB RTX 500 Ada", "brand": "Lenovo", "category": "Laptop", "listPrice": 2449.00, "tier": "fleet",
     "specs": {"segment": "mobile workstation", "cpu": "Intel Core Ultra 7 165H", "ramGb": 64, "ramKind": "DDR5", "storageGb": 1024, "screenInches": 16.0,
               "resolution": "3840x2400", "graphics": "NVIDIA RTX 500 Ada 4GB", "weightKg": 1.85, "batteryWh": 86, "os": "Windows 11 Pro", "warrantyYears": 3}},
    {"sku": "LAP-ASUS-B5", "name": "ExpertBook B5 14\" Core i7-1355U 16GB/512GB", "brand": "ASUS", "category": "Laptop", "listPrice": 1149.00, "tier": "fleet",
     "specs": {"segment": "business", "cpu": "Intel Core i7-1355U", "ramGb": 16, "ramKind": "DDR5", "storageGb": 512, "screenInches": 14.0,
               "resolution": "1920x1200", "graphics": "Intel Iris Xe", "weightKg": 1.35, "batteryWh": 63, "os": "Windows 11 Pro", "warrantyYears": 2}},

    # --- Servers: general purpose rack servers and GPU servers ---
    {"sku": "SRV-DELL-R660", "name": "PowerEdge R660 1U 2x Xeon Gold 6430 256GB", "brand": "Dell", "category": "Server", "listPrice": 12900.00, "tier": "enterprise",
     "specs": {"formFactor": "1U rack", "cpuModel": "2x Intel Xeon Gold 6430 (32 cores)", "cpuSockets": 2, "ramGb": 256, "ramKind": "DDR5-4800 ECC",
               "driveBays": 10, "driveBayType": "2.5in NVMe/SAS/SATA", "gpuSlots": 0, "psuWatts": 1100, "redundantPsu": True, "warrantyYears": 3}},
    {"sku": "SRV-DELL-R760", "name": "PowerEdge R760 2U 2x Xeon Gold 6430 512GB", "brand": "Dell", "category": "Server", "listPrice": 16800.00, "tier": "enterprise",
     "specs": {"formFactor": "2U rack", "cpuModel": "2x Intel Xeon Gold 6430 (32 cores)", "cpuSockets": 2, "ramGb": 512, "ramKind": "DDR5-4800 ECC",
               "driveBays": 16, "driveBayType": "2.5in NVMe/SAS/SATA", "gpuSlots": 2, "psuWatts": 1400, "redundantPsu": True, "warrantyYears": 3}},
    {"sku": "SRV-DELL-XE9680", "name": "PowerEdge XE9680 6U 2x Xeon Platinum 8468 8x H100 SXM5 2TB", "brand": "Dell", "category": "Server", "listPrice": 289000.00, "tier": "enterprise",
     "specs": {"formFactor": "6U rack", "cpuModel": "2x Intel Xeon Platinum 8468 (48 cores)", "cpuSockets": 2, "ramGb": 2048, "ramKind": "DDR5-4800 ECC",
               "driveBays": 8, "driveBayType": "2.5in NVMe", "gpuSlots": 8, "gpuModel": "8x NVIDIA H100 80GB SXM5", "psuWatts": 2800, "redundantPsu": True, "warrantyYears": 3}},
    {"sku": "SRV-HPE-DL360G11", "name": "ProLiant DL360 Gen11 1U 2x Xeon Gold 5420+ 256GB", "brand": "HPE", "category": "Server", "listPrice": 11400.00, "tier": "enterprise",
     "specs": {"formFactor": "1U rack", "cpuModel": "2x Intel Xeon Gold 5420+ (28 cores)", "cpuSockets": 2, "ramGb": 256, "ramKind": "DDR5-4800 ECC",
               "driveBays": 8, "driveBayType": "2.5in NVMe/SAS/SATA", "gpuSlots": 1, "psuWatts": 800, "redundantPsu": True, "warrantyYears": 3}},
    {"sku": "SRV-HPE-DL380G11", "name": "ProLiant DL380 Gen11 2U 2x Xeon Gold 6430 512GB", "brand": "HPE", "category": "Server", "listPrice": 15200.00, "tier": "enterprise",
     "specs": {"formFactor": "2U rack", "cpuModel": "2x Intel Xeon Gold 6430 (32 cores)", "cpuSockets": 2, "ramGb": 512, "ramKind": "DDR5-4800 ECC",
               "driveBays": 12, "driveBayType": "3.5in SAS/SATA", "gpuSlots": 4, "psuWatts": 1600, "redundantPsu": True, "warrantyYears": 3}},
    {"sku": "SRV-LEN-SR650V3", "name": "ThinkSystem SR650 V3 2U 2x Xeon Gold 5418Y 256GB", "brand": "Lenovo", "category": "Server", "listPrice": 12300.00, "tier": "enterprise",
     "specs": {"formFactor": "2U rack", "cpuModel": "2x Intel Xeon Gold 5418Y (24 cores)", "cpuSockets": 2, "ramGb": 256, "ramKind": "DDR5-4800 ECC",
               "driveBays": 12, "driveBayType": "3.5in SAS/SATA", "gpuSlots": 3, "psuWatts": 1100, "redundantPsu": True, "warrantyYears": 3}},
    {"sku": "SRV-SMC-421GE", "name": "SYS-421GE-TNRT 4U 8-GPU Server (barebone)", "brand": "Supermicro", "category": "Server", "listPrice": 9800.00, "tier": "enterprise",
     "specs": {"formFactor": "4U rack", "cpuModel": "2x Intel Xeon Scalable (not included)", "cpuSockets": 2, "ramGb": 0, "ramKind": "DDR5 ECC (not included)",
               "driveBays": 24, "driveBayType": "2.5in NVMe/SAS/SATA", "gpuSlots": 10, "psuWatts": 2000, "redundantPsu": True, "barebone": True, "warrantyYears": 3}},

    # --- Data center networking ---
    {"sku": "NET-CISCO-N93180", "name": "Nexus 93180YC-FX3 48x 10/25G + 6x 40/100G Leaf Switch", "brand": "Cisco", "category": "Networking", "listPrice": 17500.00, "tier": "enterprise",
     "specs": {"formFactor": "1U rack", "ports": "48x 10/25GbE SFP28 + 6x 40/100GbE QSFP28", "switchingCapacityGbps": 3600, "layer": "L3", "managed": True}},
    {"sku": "NET-CISCO-C9300-48P", "name": "Catalyst 9300-48P 48-Port PoE+ Access Switch", "brand": "Cisco", "category": "Networking", "listPrice": 6400.00, "tier": "enterprise",
     "specs": {"formFactor": "1U rack", "ports": "48x 1GbE PoE+ with uplink module slot", "poeBudgetWatts": 437, "switchingCapacityGbps": 208, "layer": "L3", "managed": True}},
    {"sku": "NET-CISCO-QSFP100", "name": "QSFP28 100GBASE-SR4 Optical Transceiver 100m", "brand": "Cisco", "category": "Networking", "listPrice": 420.00, "tier": "accessory",
     "specs": {"speed": "100GbE", "medium": "multimode fiber OM4", "reachMeters": 100}},
    {"sku": "NET-NVIDIA-CX6DX", "name": "ConnectX-6 Dx 100GbE Dual-Port QSFP56 NIC", "brand": "NVIDIA", "category": "Networking", "listPrice": 1090.00, "tier": "component",
     "specs": {"speed": "2x 100GbE", "hostInterface": "PCIe 4.0 x16", "formFactor": "PCIe add-in card"}},

    # --- Enterprise storage and server memory ---
    {"sku": "SSD-ENT-PM9A3-3T84", "name": "PM9A3 3.84TB U.2 NVMe Enterprise SSD", "brand": "Samsung", "category": "Storage", "listPrice": 579.00, "tier": "component",
     "specs": {"capacityGb": 3840, "interface": "U.2 NVMe PCIe 4.0", "formFactor": "2.5in U.2", "enduranceDwpd": 1.0}},
    {"sku": "SSD-ENT-DC600M-1T92", "name": "DC600M 1.92TB SATA Enterprise SSD", "brand": "Kingston", "category": "Storage", "listPrice": 289.00, "tier": "component",
     "specs": {"capacityGb": 1920, "interface": "SATA 6Gb/s", "formFactor": "2.5in", "enduranceDwpd": 1.3}},
    {"sku": "HDD-EXOS-X20", "name": "Exos X20 20TB 7200rpm SAS 3.5in", "brand": "Seagate", "category": "Storage", "listPrice": 389.00, "tier": "component",
     "specs": {"capacityGb": 20000, "interface": "SAS 12Gb/s", "formFactor": "3.5in", "rpm": 7200}},
    {"sku": "RAM-DDR5-32-ECC", "name": "Server Premier 32GB DDR5-4800 ECC RDIMM", "brand": "Kingston", "category": "RAM", "listPrice": 149.00, "tier": "component",
     "specs": {"capacityGb": 32, "ramKind": "DDR5-4800 ECC RDIMM"}},
    {"sku": "RAM-DDR5-64-ECC", "name": "Server Premier 64GB DDR5-4800 ECC RDIMM", "brand": "Kingston", "category": "RAM", "listPrice": 289.00, "tier": "component",
     "specs": {"capacityGb": 64, "ramKind": "DDR5-4800 ECC RDIMM"}},

    # --- Power supplies: server modules and workstation units ---
    {"sku": "PSU-CRPS-1600W", "name": "1600W 80+ Platinum Redundant CRPS Power Supply Module", "brand": "Supermicro", "category": "PSU", "listPrice": 289.00, "tier": "component",
     "specs": {"watts": 1600, "efficiencyRating": "80+ Platinum", "formFactor": "CRPS", "hotSwap": True}},
    {"sku": "PSU-SFX-750W", "name": "SF750 750W 80+ Platinum SFX", "brand": "Corsair", "category": "PSU", "listPrice": 169.00, "tier": "component",
     "specs": {"watts": 750, "efficiencyRating": "80+ Platinum", "formFactor": "SFX", "hotSwap": False}},
    {"sku": "PSU-1500W-PLAT", "name": "HX1500i 1500W 80+ Platinum ATX", "brand": "Corsair", "category": "PSU", "listPrice": 329.00, "tier": "component",
     "specs": {"watts": 1500, "efficiencyRating": "80+ Platinum", "formFactor": "ATX", "hotSwap": False}},

    # --- UPS: emergency power for desks, racks and server rooms ---
    {"sku": "UPS-APC-BR1500MS2", "name": "Back-UPS Pro BR1500MS2 1500VA Desktop", "brand": "APC", "category": "UPS", "listPrice": 229.00, "tier": "component",
     "specs": {"capacityVa": 1500, "capacityWatts": 900, "topology": "line-interactive", "formFactor": "desktop", "outlets": 10, "inputVoltage": "120V", "networkCard": False}},
    {"sku": "UPS-APC-SMT1500RM2UC", "name": "Smart-UPS 1500VA LCD RM 2U SMT1500RM2UC", "brand": "APC", "category": "UPS", "listPrice": 1049.00, "tier": "component",
     "specs": {"capacityVa": 1500, "capacityWatts": 1000, "topology": "line-interactive", "formFactor": "2U rack", "outlets": 6, "inputVoltage": "120V", "networkCard": True}},
    {"sku": "UPS-EATON-5PX1500RT", "name": "Eaton 5PX 1500VA RT2U Rack/Tower", "brand": "Eaton", "category": "UPS", "listPrice": 1129.00, "tier": "component",
     "specs": {"capacityVa": 1500, "capacityWatts": 1350, "topology": "line-interactive", "formFactor": "2U rack/tower", "outlets": 8, "inputVoltage": "120V", "networkCard": False}},
    {"sku": "UPS-APC-SRT3000RM", "name": "Smart-UPS SRT 3000VA RM 2U Online", "brand": "APC", "category": "UPS", "listPrice": 3299.00, "tier": "component",
     "specs": {"capacityVa": 3000, "capacityWatts": 2700, "topology": "online double-conversion", "formFactor": "2U rack", "outlets": 8, "inputVoltage": "120V", "networkCard": True}},
    {"sku": "UPS-VERTIV-GXT5-3000", "name": "Liebert GXT5 3000VA Online Rack/Tower", "brand": "Vertiv", "category": "UPS", "listPrice": 2799.00, "tier": "component",
     "specs": {"capacityVa": 3000, "capacityWatts": 2700, "topology": "online double-conversion", "formFactor": "2U rack/tower", "outlets": 8, "inputVoltage": "120V", "networkCard": True}},
    {"sku": "UPS-EATON-9PX6000", "name": "Eaton 9PX 6000VA Online Rack/Tower", "brand": "Eaton", "category": "UPS", "listPrice": 4899.00, "tier": "component",
     "specs": {"capacityVa": 6000, "capacityWatts": 5400, "topology": "online double-conversion", "formFactor": "6U rack/tower", "outlets": 4, "inputVoltage": "208/240V", "networkCard": True}},

    # --- Racks, power distribution and remote access ---
    {"sku": "RACK-APC-SX42U", "name": "NetShelter SX 42U 600mm x 1070mm Rack Enclosure", "brand": "APC", "category": "Rack", "listPrice": 1689.00, "tier": "component",
     "specs": {"kind": "enclosure", "heightU": 42, "widthMm": 600, "depthMm": 1070, "loadCapacityKg": 1360}},
    {"sku": "RACK-PDU-APC-M16", "name": "Metered Rack PDU 1U 120V 20A 16 Outlets", "brand": "APC", "category": "Rack", "listPrice": 329.00, "tier": "component",
     "specs": {"kind": "PDU", "capacityKw": 1.92, "outlets": 16, "metered": True, "switched": False}},
    {"sku": "RACK-PDU-EATON-G4", "name": "Eaton G4 Switched Rack PDU 208V 5.7kW 24 Outlets", "brand": "Eaton", "category": "Rack", "listPrice": 849.00, "tier": "component",
     "specs": {"kind": "PDU", "capacityKw": 5.7, "outlets": 24, "metered": True, "switched": True}},
    {"sku": "RACK-VERTIV-KVM8", "name": "Avocent 8-Port Digital KVM Switch over IP", "brand": "Vertiv", "category": "Rack", "listPrice": 899.00, "tier": "component",
     "specs": {"kind": "KVM", "ports": 8, "remoteAccess": "KVM over IP"}},

    # --- Monitors and laptop accessories ---
    {"sku": "MON-DELL-U2724D", "name": "UltraSharp U2724D 27\" QHD IPS Monitor", "brand": "Dell", "category": "Monitor", "listPrice": 389.00, "tier": "component",
     "specs": {"screenInches": 27.0, "resolution": "2560x1440", "panel": "IPS", "warrantyYears": 3}},
    {"sku": "MON-HP-E24G5", "name": "E24 G5 24\" FHD IPS Monitor", "brand": "HP", "category": "Monitor", "listPrice": 169.00, "tier": "component",
     "specs": {"screenInches": 24.0, "resolution": "1920x1080", "panel": "IPS", "warrantyYears": 3}},
    {"sku": "ACC-DOCK-DELL-WD22TB4", "name": "WD22TB4 Thunderbolt 4 Dock", "brand": "Dell", "category": "Accessory", "listPrice": 249.00, "tier": "accessory",
     "specs": {"kind": "docking station", "hostInterface": "Thunderbolt 4", "powerDeliveryWatts": 130}},
    {"sku": "ACC-CHARGER-USBC-100W", "name": "USB-C 100W GaN Laptop Charger", "brand": "Anker", "category": "Accessory", "listPrice": 44.00, "tier": "accessory",
     "specs": {"kind": "laptop power adapter", "wattage": 100, "connector": "USB-C"}},
    {"sku": "ACC-ADAPTER-LEN-135W", "name": "ThinkPad 135W Slim-tip AC Adapter", "brand": "Lenovo", "category": "Accessory", "listPrice": 54.00, "tier": "accessory",
     "specs": {"kind": "laptop power adapter", "wattage": 135, "connector": "slim-tip"}},
    {"sku": "ACC-FIBER-LC-OM4-3M", "name": "OM4 LC-LC Duplex Fiber Patch Cable 3m (10-pack)", "brand": "Cable Matters", "category": "Accessory", "listPrice": 52.00, "tier": "accessory",
     "specs": {"kind": "fiber patch cable", "medium": "multimode fiber OM4", "lengthMeters": 3, "packSize": 10}},
]

TIER_QTY_RANGE = {
    "accessory": (5, 150),
    "component": (2, 60),
    "gpu_consumer": (1, 30),
    "enterprise": (1, 15),
    "fleet": (5, 120),
}
