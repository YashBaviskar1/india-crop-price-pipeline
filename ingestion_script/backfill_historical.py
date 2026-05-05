"""
Historical backfill — ALL 389 commodities — one-time run
----------------------------------------------------------
Reads year-wise Parquet files (2001.parquet ... 2026.parquet),
validates, cleans, enriches with accurate categories, and uploads
to GCS partitioned by year/month.

Category map is built from actual EDA of commodity names — no guessing.

Outputs:
  GCS: mandi_prices/year=YYYY/month=MM/mandi_YYYYMM_partN.parquet
  GCS: metadata/commodity_index.parquet   ← powers dashboard dropdowns

Usage:
    python backfill_historical.py                    # full run (all years)
    python backfill_historical.py --year 2015        # single year
    python backfill_historical.py --dry-run          # validate + categorise, skip GCS
    python backfill_historical.py --inspect 2023     # schema + top commodities, then exit
"""

import pandas as pd
from google.cloud import storage
from pathlib import Path
import logging
import argparse
import os
import sys
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

LOCAL_PARQUET_DIR = Path(os.environ.get(
    "HISTORICAL_DATA_DIR",
    "/home/yashbaviskar/Desktop/Projects/india-crop-pipeline/dataset/Historical_Data/parquet"
))
GCS_BUCKET    = os.environ.get("GCS_RAW_BUCKET", "agmarknet-raw-bucket")
LOCAL_TMP     = Path("/tmp/agmarknet_backfill")
YEARS         = list(range(2001, 2027))
ROWS_PER_PART = 500_000

COLUMN_MAP = {
    "State": "state", "District": "district", "Market": "market",
    "Commodity": "commodity", "Variety": "variety", "Grade": "grade",
    "Arrival_Date": "arrival_date", "Min_Price": "min_price",
    "Max_Price": "max_price", "Modal_Price": "modal_price",
    "Commodity_Code": "commodity_code",
    # passthrough if already lowercase
    "min_price": "min_price", "max_price": "max_price",
    "modal_price": "modal_price", "arrival_date": "arrival_date",
    "commodity_code": "commodity_code",
}

# ── Category map — built from actual EDA of your 389 commodities ──────────────
#
# Strategy: keyword (substring, case-insensitive) → category
# Order matters — first match wins. More specific keywords come first.
# "Other" is the fallback for anything unmatched.
#
# Categories:
#   Vegetables | Fruits | Cereals | Pulses | Oilseeds | Spices
#   Cash Crops | Flowers | Herbs & Medicinal | Animal Products
#   Processed Foods | Other
#
KEYWORD_CATEGORY = [
    # ── Vegetables ────────────────────────────────────────────────────────────
    ("Green Chilli",        "Vegetables"),
    ("Chili Red",           "Vegetables"),
    ("Leafy Vegetable",     "Vegetables"),
    ("Other green",         "Vegetables"),
    ("Bitter gourd",        "Vegetables"),
    ("Bottle gourd",        "Vegetables"),
    ("Snake Gourd",         "Vegetables"),
    ("Snakeguard",          "Vegetables"),
    ("Sponge Gourd",        "Vegetables"),
    ("Round gourd",         "Vegetables"),
    ("Little gourd",        "Vegetables"),
    ("Pointed gourd",       "Vegetables"),
    ("Squash",              "Vegetables"),
    ("Long Melon",          "Vegetables"),
    ("Kartali",             "Vegetables"),
    ("Tinda",               "Vegetables"),
    ("Chow Chow",           "Vegetables"),
    ("Ashgourd",            "Vegetables"),
    ("Thondekai",           "Vegetables"),
    ("Thogrikai",           "Vegetables"),
    ("Haralekai",           "Vegetables"),
    ("Seemebadnekai",       "Vegetables"),
    ("Balekai",             "Vegetables"),
    ("Alsandikai",          "Vegetables"),
    ("Onion",               "Vegetables"),
    ("Tomato",              "Vegetables"),
    ("Potato",              "Vegetables"),
    ("Sweet Potato",        "Vegetables"),
    ("Brinjal",             "Vegetables"),
    ("Cabbage",             "Vegetables"),
    ("Cauliflower",         "Vegetables"),
    ("Drumstick",           "Vegetables"),
    ("Ladies Finger",       "Vegetables"),
    ("Bhindi",              "Vegetables"),
    ("Pumpkin",             "Vegetables"),
    ("Radish",              "Vegetables"),
    ("Raddish",             "Vegetables"),
    ("Spinach",             "Vegetables"),
    ("Carrot",              "Vegetables"),
    ("Beetroot",            "Vegetables"),
    ("Capsicum",            "Vegetables"),
    ("Garlic",              "Vegetables"),
    ("Ginger",              "Vegetables"),
    ("Cucumbar",            "Vegetables"),
    ("Cucumber",            "Vegetables"),
    ("Ridgeguard",          "Vegetables"),
    ("Taro",                "Vegetables"),
    ("Colocasia",           "Vegetables"),
    ("Colacasia",           "Vegetables"),
    ("Elephant Yam",        "Vegetables"),
    ("Yam",                 "Vegetables"),
    ("Suram",               "Vegetables"),
    ("Suvarna Gadde",       "Vegetables"),
    ("Kacholam",            "Vegetables"),
    ("Amaranthus",          "Vegetables"),
    ("Amranthas",           "Vegetables"),
    ("Amphophalus",         "Vegetables"),
    ("Asparagus",           "Vegetables"),
    ("Tapioca",             "Vegetables"),
    ("Knol-Kohl",           "Vegetables"),
    ("Knool Khol",          "Vegetables"),
    ("Parwal",              "Vegetables"),
    ("Mushroom",            "Vegetables"),
    ("Mashrooms",           "Vegetables"),
    ("Cluster beans",       "Vegetables"),
    ("French Beans",        "Vegetables"),
    ("Sword Beans",         "Vegetables"),
    ("Bunch Beans",         "Vegetables"),
    ("Beans",               "Vegetables"),
    ("Turnip",              "Vegetables"),
    ("Kakada",              "Vegetables"),

    # ── Fruits ────────────────────────────────────────────────────────────────
    ("Custard Apple",       "Fruits"),
    ("Water Melon",         "Fruits"),
    ("Watermelon",          "Fruits"),
    ("Raw Banana",          "Fruits"),
    ("Banana",              "Fruits"),
    ("Apple",               "Fruits"),
    ("Mango",               "Fruits"),
    ("Guava",               "Fruits"),
    ("Papaya",              "Fruits"),
    ("Pomegranate",         "Fruits"),
    ("Grapes",              "Fruits"),
    ("Muskmelon",           "Fruits"),
    ("Pineapple",           "Fruits"),
    ("Sapota",              "Fruits"),
    ("Chikoos",             "Fruits"),
    ("Coconut Oil",         "Oilseeds"),    # Coconut OIL → Oilseeds, not Fruits
    ("Coconut Seed",        "Oilseeds"),
    ("Coconut",             "Fruits"),
    ("Lemon",               "Fruits"),
    ("Lime",                "Fruits"),
    ("Orange",              "Fruits"),
    ("Kinnow",              "Fruits"),
    ("Litchi",              "Fruits"),
    ("Plum",                "Fruits"),
    ("Peach",               "Fruits"),
    ("Pear",                "Fruits"),
    ("Cherry",              "Fruits"),
    ("Amla",                "Fruits"),
    ("Nelli Kai",           "Fruits"),
    ("Nearle Hannu",        "Fruits"),
    ("Bael",                "Fruits"),
    ("Fig",                 "Fruits"),
    ("Apricot",             "Fruits"),
    ("Walnut",              "Fruits"),
    ("Almond",              "Fruits"),
    ("Cashew",              "Fruits"),
    ("Jack Fruit",          "Fruits"),
    ("Jackfruit",           "Fruits"),
    ("Kiwi",                "Fruits"),
    ("Mulberry",            "Fruits"),
    ("Tamarind",            "Fruits"),
    ("Jamun",               "Fruits"),
    ("Ber ",                "Fruits"),
    ("Borehannu",           "Fruits"),
    ("Persimon",            "Fruits"),
    ("Chakotha",            "Fruits"),
    ("Seetapal",            "Fruits"),
    ("Marasebu",            "Fruits"),
    ("Marget",              "Fruits"),
    ("Jarbara",             "Fruits"),
    ("Myrobolan",           "Fruits"),

    # ── Cereals & Grains ──────────────────────────────────────────────────────
    ("Foxtail Millet",      "Cereals"),
    ("Kodo Millet",         "Cereals"),
    ("Thinai",              "Cereals"),
    ("Italian Millet",      "Cereals"),
    ("Hybrid Cumbu",        "Cereals"),
    ("T.V. Cumbu",          "Cereals"),
    ("Beaten Rice",         "Cereals"),
    ("Broken Rice",         "Cereals"),
    ("Paddy",               "Cereals"),
    ("Wheat",               "Cereals"),
    ("Rice",                "Cereals"),
    ("Maize",               "Cereals"),
    ("Jowar",               "Cereals"),
    ("Bajra",               "Cereals"),
    ("Ragi",                "Cereals"),
    ("Barley",              "Cereals"),
    ("Sorghum",             "Cereals"),
    ("Millets",             "Cereals"),
    ("Sajje",               "Cereals"),
    ("Same/Savi",           "Cereals"),
    ("Bran",                "Cereals"),
    ("Flour",               "Cereals"),
    ("Semolina",            "Cereals"),
    ("Maida",               "Cereals"),
    ("Soji",                "Cereals"),
    ("Sabu Dan",            "Cereals"),
    ("Sarasum",             "Cereals"),

    # ── Pulses ────────────────────────────────────────────────────────────────
    ("Other Pulses",        "Pulses"),
    ("Arhar",               "Pulses"),
    ("Tur",                 "Pulses"),
    ("Moong",               "Pulses"),
    ("Moath Dal",           "Pulses"),
    ("Urad",                "Pulses"),
    ("Masur",               "Pulses"),
    ("Bengal Gram",         "Pulses"),
    ("Chana",               "Pulses"),
    ("Lentil",              "Pulses"),
    ("Rajma",               "Pulses"),
    ("Horsegram",           "Pulses"),
    ("Cowpea",              "Pulses"),
    ("Karamani",            "Pulses"),
    ("Black Gram",          "Pulses"),
    ("Green Gram",          "Pulses"),
    ("Alasande",            "Pulses"),
    ("Avare",               "Pulses"),
    ("Field Bean",          "Pulses"),
    ("Field Pea",           "Pulses"),
    ("Moth",                "Pulses"),
    ("Mataki",              "Pulses"),
    ("Mash",                "Pulses"),
    ("Kharif Mash",         "Pulses"),
    ("Gram",                "Pulses"),
    ("Pea",                 "Pulses"),
    ("Lak ",                "Pulses"),
    ("Kulthi",              "Pulses"),
    ("Chennangi",           "Pulses"),
    ("Big Gram",            "Pulses"),
    ("Guar",                "Pulses"),
    ("Rajgir",              "Pulses"),
    ("Riccbcan",            "Pulses"),
    ("Delha",               "Pulses"),

    # ── Oilseeds ──────────────────────────────────────────────────────────────
    ("Ground Nut Oil",      "Oilseeds"),
    ("Ground Nut Seed",     "Oilseeds"),
    ("Groundnut pods",      "Oilseeds"),
    ("Groundnut (Split)",   "Oilseeds"),
    ("Groundnut",           "Oilseeds"),
    ("Cotton Seed",         "Oilseeds"),
    ("Castor Oil",          "Oilseeds"),
    ("Castor Seed",         "Oilseeds"),
    ("Castor",              "Oilseeds"),
    ("Mustard Oil",         "Oilseeds"),
    ("Mustard",             "Oilseeds"),
    ("Soyabean",            "Oilseeds"),
    ("Soybean",             "Oilseeds"),
    ("Sunflower",           "Oilseeds"),
    ("Sesame",              "Oilseeds"),
    ("Sesamum",             "Oilseeds"),
    ("Gingelly",            "Oilseeds"),
    ("Linseed",             "Oilseeds"),
    ("Rapeseed",            "Oilseeds"),
    ("Indian Colza",        "Oilseeds"),
    ("Sarson",              "Oilseeds"),
    ("Raya",                "Oilseeds"),
    ("Toria",               "Oilseeds"),
    ("Safflower",           "Oilseeds"),
    ("Kardi",               "Oilseeds"),
    ("Niger",               "Oilseeds"),
    ("Gurellu",             "Oilseeds"),
    ("Binoula",             "Oilseeds"),
    ("Taramira",            "Oilseeds"),
    ("Hippe Seed",          "Oilseeds"),
    ("Honge seed",          "Oilseeds"),
    ("Mahua Seed",          "Oilseeds"),
    ("Pundi Seed",          "Oilseeds"),
    ("Karanja seeds",       "Oilseeds"),
    ("Til ",                "Oilseeds"),
    ("Kusum",               "Oilseeds"),
    ("Copra",               "Oilseeds"),

    # ── Spices & Condiments ───────────────────────────────────────────────────
    ("Dry Chilli",          "Spices"),
    ("Dry Chillies",        "Spices"),
    ("Chilli",              "Spices"),
    ("Cummin Seed",         "Spices"),
    ("Cumin",               "Spices"),
    ("Corriander seed",     "Spices"),
    ("Coriander (Leaves)",  "Spices"),
    ("Coriander",           "Spices"),
    ("Turmeric",            "Spices"),
    ("Fenugreek",           "Spices"),
    ("Methi",               "Spices"),
    ("Cardamoms",           "Spices"),
    ("Cardamom",            "Spices"),
    ("Black pepper",        "Spices"),
    ("Pepper",              "Spices"),
    ("Cloves",              "Spices"),
    ("Clove",               "Spices"),
    ("Ajwan",               "Spices"),
    ("Anise",               "Spices"),
    ("Fennel",              "Spices"),
    ("Soanf",               "Spices"),
    ("Sompu",               "Spices"),
    ("Cinamon",             "Spices"),
    ("Nutmeg",              "Spices"),
    ("Mace",                "Spices"),
    ("Saffron",             "Spices"),
    ("Star Anise",          "Spices"),
    ("Bay leaf",            "Spices"),
    ("Mint",                "Spices"),
    ("basil",               "Spices"),
    ("Dill Seed",           "Spices"),
    ("Poppy",               "Spices"),
    ("nigella",             "Spices"),
    ("Isabgul",             "Spices"),
    ("Asalia",              "Spices"),

    # ── Cash Crops ────────────────────────────────────────────────────────────
    ("Cotton",              "Cash Crops"),
    ("Sugarcane",           "Cash Crops"),
    ("Jute Seed",           "Cash Crops"),
    ("Jute",                "Cash Crops"),
    ("Tobacco",             "Cash Crops"),
    ("Arecanut",            "Cash Crops"),
    ("Betelnuts",           "Cash Crops"),
    ("Betal Leaves",        "Cash Crops"),
    ("Coffee",              "Cash Crops"),
    ("Tea",                 "Cash Crops"),
    ("Cocoa",               "Cash Crops"),
    ("Rubber",              "Cash Crops"),
    ("Bamboo",              "Cash Crops"),
    ("Ambady",              "Cash Crops"),
    ("Ambada Seed",         "Cash Crops"),
    ("Dhaincha",            "Cash Crops"),
    ("Pundi",               "Cash Crops"),
    ("Sanay",               "Cash Crops"),
    ("Lint",                "Cash Crops"),

    # ── Processed & Value-added Foods ────────────────────────────────────────
    ("Jaggery",             "Processed Foods"),
    ("Gur ",                "Processed Foods"),
    ("Sugar",               "Processed Foods"),
    ("Ghee",                "Processed Foods"),
    ("Khoya",               "Processed Foods"),
    ("Butter",              "Processed Foods"),
    ("Dalda",               "Processed Foods"),
    ("Mahua",               "Processed Foods"),   # Mahua flowers/liquor
    ("BOP",                 "Processed Foods"),   # Black Oil Palm product

    # ── Flowers ───────────────────────────────────────────────────────────────
    ("Rose",                "Flowers"),
    ("Jasmine",             "Flowers"),
    ("Marigold",            "Flowers"),
    ("Anthorium",           "Flowers"),
    ("Calendula",           "Flowers"),
    ("Chrysanthemum",       "Flowers"),
    ("Gladiolus",           "Flowers"),
    ("Carnation",           "Flowers"),
    ("Orchid",              "Flowers"),
    ("Tulip",               "Flowers"),
    ("Lilly",               "Flowers"),
    ("Daila",               "Flowers"),
    ("Jaffri",              "Flowers"),
    ("Kankambra",           "Flowers"),
    ("Tube Flower",         "Flowers"),
    ("Palash flowers",      "Flowers"),
    ("dhawai flowers",      "Flowers"),
    ("Lotus",               "Flowers"),
    ("Broomstick",          "Flowers"),
    ("Flower Broom",        "Flowers"),

    # ── Herbs & Medicinal ─────────────────────────────────────────────────────
    ("Ashwagandha",         "Herbs & Medicinal"),
    ("Brahmi",              "Herbs & Medicinal"),
    ("Stevia",              "Herbs & Medicinal"),
    ("Absinthe",            "Herbs & Medicinal"),
    ("White Muesli",        "Herbs & Medicinal"),
    ("Spikenard",           "Herbs & Medicinal"),
    ("Kutki",               "Herbs & Medicinal"),
    ("Giloy",               "Herbs & Medicinal"),
    ("Gudmar",              "Herbs & Medicinal"),
    ("Kalmegh",             "Herbs & Medicinal"),
    ("Ratanjot",            "Herbs & Medicinal"),
    ("Muleti",              "Herbs & Medicinal"),
    ("Egypian Clover",      "Herbs & Medicinal"),
    ("Antawala",            "Herbs & Medicinal"),
    ("Soapnut",             "Herbs & Medicinal"),
    ("Bhui Amlaya",         "Herbs & Medicinal"),

    # ── Animal Products ───────────────────────────────────────────────────────
    ("Cow",                 "Animal Products"),
    ("Bull",                "Animal Products"),
    ("Calf",                "Animal Products"),
    ("Buffalo",             "Animal Products"),
    ("Goat",                "Animal Products"),
    ("Sheep",               "Animal Products"),
    ("Ram",                 "Animal Products"),
    ("Pig",                 "Animal Products"),
    ("Hen",                 "Animal Products"),
    ("Cock",                "Animal Products"),
    ("Duck",                "Animal Products"),
    ("Egg",                 "Animal Products"),
    ("Wool",                "Animal Products"),
    ("Skin And Hide",       "Animal Products"),

    # ── Forestry & Raw Materials ──────────────────────────────────────────────
    ("Wood",                "Forestry & Raw Materials"),
    ("Firewood",            "Forestry & Raw Materials"),
    ("Resinwood",           "Forestry & Raw Materials"),
    ("Torchwood",           "Forestry & Raw Materials"),
    ("Dry Fodder",          "Forestry & Raw Materials"),
    ("Green Fodder",        "Forestry & Raw Materials"),
    ("Cane",                "Forestry & Raw Materials"),
    ("Season Leaves",       "Forestry & Raw Materials"),
]


def assign_category(commodity: str) -> str:
    """
    First-match wins. Checks each keyword (case-insensitive substring)
    against the commodity name and returns the mapped category.
    Falls back to 'Other' for anything unrecognised.
    """
    c_lower = commodity.lower()
    for keyword, category in KEYWORD_CATEGORY:
        if keyword.lower() in c_lower:
            return category
    return "Other"


# ── Load ──────────────────────────────────────────────────────────────────────

def load_year(year: int) -> pd.DataFrame | None:
    for fname in [f"{year}.parquet", f"{year}.paraquet"]:
        path = LOCAL_PARQUET_DIR / fname
        if path.exists():
            log.info(f"Loading {path}")
            df = pd.read_parquet(path)
            log.info(f"  Raw: {len(df):,} rows × {len(df.columns)} cols")
            return df
    log.warning(f"No file for year {year} — skipping")
    return None


# ── Validate & clean ──────────────────────────────────────────────────────────

def validate_and_clean(df: pd.DataFrame, year: int) -> pd.DataFrame:
    df = df.rename(columns={k: v for k, v in COLUMN_MAP.items() if k in df.columns})

    missing = {"state", "commodity", "arrival_date", "modal_price"} - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {missing} | found: {df.columns.tolist()}")

    # Dates
    df["arrival_date"] = pd.to_datetime(df["arrival_date"], errors="coerce")
    bad_dates = df["arrival_date"].isna().sum()
    if bad_dates:
        log.warning(f"  Dropping {bad_dates:,} unparseable date rows")
        df = df.dropna(subset=["arrival_date"])

    # Prices
    for col in ["min_price", "max_price", "modal_price"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    before = len(df)
    df = df.dropna(subset=["modal_price"])
    df = df[df["modal_price"] >= 0]
    dropped = before - len(df)
    if dropped:
        log.warning(f"  Dropped {dropped:,} rows — null/negative modal_price")

    # Strip whitespace from string columns
    for col in ["state", "district", "market", "commodity", "variety", "grade"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()

    # Enrich: partition columns + category
    df["year"]               = df["arrival_date"].dt.year
    df["month"]              = df["arrival_date"].dt.month
    df["category"]           = df["commodity"].apply(assign_category)
    df["price_inconsistent"] = False
    if "min_price" in df.columns and "max_price" in df.columns:
        df["price_inconsistent"] = (df["min_price"] > df["max_price"]).astype(bool)

    # Summary
    cat_dist = df["category"].value_counts().to_dict()
    log.info(f"  Clean: {len(df):,} rows")
    log.info(f"  States: {df['state'].nunique()} | Commodities: {df['commodity'].nunique()}")
    log.info(f"  Category distribution: {cat_dist}")

    return df


# ── Save monthly partitions locally ──────────────────────────────────────────

def split_and_save(df: pd.DataFrame) -> list[tuple[int, int, Path]]:
    LOCAL_TMP.mkdir(parents=True, exist_ok=True)
    saved = []
    for (yr, mo), group in df.groupby(["year", "month"]):
        yr, mo = int(yr), int(mo)
        chunks = (
            [group] if len(group) <= ROWS_PER_PART
            else [group.iloc[i:i + ROWS_PER_PART] for i in range(0, len(group), ROWS_PER_PART)]
        )
        for i, chunk in enumerate(chunks):
            fname = f"mandi_{yr}{mo:02d}_part{i}.parquet"
            path  = LOCAL_TMP / fname
            chunk.to_parquet(path, index=False, engine="pyarrow")
            saved.append((yr, mo, path))
    log.info(f"  Saved {len(saved)} partition files locally")
    return saved


# ── Upload to GCS (idempotent) ────────────────────────────────────────────────

def upload_to_gcs(year: int, month: int, local_path: Path, bucket_name: str) -> str:
    gcs_path = f"mandi_prices/year={year}/month={month:02d}/{local_path.name}"
    client   = storage.Client()
    blob     = client.bucket(bucket_name).blob(gcs_path)
    if blob.exists():
        log.info(f"  Skip (exists): {gcs_path}")
        return f"gs://{bucket_name}/{gcs_path}"
    blob.upload_from_filename(str(local_path))
    log.info(f"  ↑ gs://{bucket_name}/{gcs_path}")
    return f"gs://{bucket_name}/{gcs_path}"


# ── Commodity index (powers dashboard dropdowns without scanning fact table) ──

def build_and_upload_commodity_index(meta_frames: list[pd.DataFrame], bucket_name: str):
    log.info("Building commodity index...")
    combined = pd.concat(meta_frames, ignore_index=True).drop_duplicates()
    index = (
        combined
        .groupby(["commodity", "category"])
        .agg(
            states_covered=("state",    "nunique"),
            year_min=      ("year",     "min"),
            year_max=      ("year",     "max"),
        )
        .reset_index()
        .sort_values(["category", "commodity"])
        .reset_index(drop=True)
    )
    log.info(f"  {len(index)} unique commodities | {index['category'].nunique()} categories")
    log.info(f"  Category breakdown:\n{index['category'].value_counts().to_string()}")

    LOCAL_TMP.mkdir(parents=True, exist_ok=True)
    local = LOCAL_TMP / "commodity_index.parquet"
    index.to_parquet(local, index=False)
    blob = storage.Client().bucket(bucket_name).blob("metadata/commodity_index.parquet")
    blob.upload_from_filename(str(local))
    log.info(f"  ↑ gs://{bucket_name}/metadata/commodity_index.parquet")


# ── Process one year ──────────────────────────────────────────────────────────

def process_year(year: int, dry_run: bool) -> tuple[dict, pd.DataFrame | None]:
    log.info(f"\n{'='*55}\n  YEAR {year}\n{'='*55}")
    result = {"year": year, "status": "skipped", "rows": 0}

    df_raw = load_year(year)
    if df_raw is None:
        return result, None

    try:
        df_clean = validate_and_clean(df_raw, year)
    except ValueError as e:
        log.error(f"Validation error: {e}")
        result["status"] = "error"
        return result, None

    if df_clean.empty:
        result["status"] = "empty"
        return result, None

    monthly_files = split_and_save(df_clean)

    if not dry_run:
        for yr, mo, path in monthly_files:
            upload_to_gcs(yr, mo, path, GCS_BUCKET)

    result.update({"status": "success", "rows": len(df_clean)})
    meta = df_clean[["commodity", "category", "state", "year"]].drop_duplicates()
    return result, meta


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--year",    type=int,  default=None, help="Single year to process")
    parser.add_argument("--dry-run", action="store_true",     help="Validate + categorise, skip GCS")
    parser.add_argument("--inspect", type=int,  default=None, help="Print schema + commodities for a year, then exit")
    args = parser.parse_args()

    # Inspect mode — useful for debugging a single year's schema
    if args.inspect:
        df = load_year(args.inspect)
        if df is not None:
            df = df.rename(columns={k: v for k, v in COLUMN_MAP.items() if k in df.columns})
            print(f"\nShape: {df.shape}")
            print(f"Columns:\n{df.dtypes}\n")
            col = "commodity" if "commodity" in df.columns else "Commodity"
            print(f"Top 40 commodities:\n{df[col].value_counts().head(40)}")

            # Show how categories would be assigned
            df["category"] = df[col].apply(assign_category)
            print(f"\nCategory distribution:\n{df['category'].value_counts()}")
        return

    if not LOCAL_PARQUET_DIR.exists():
        log.error(f"Data directory not found: {LOCAL_PARQUET_DIR}")
        log.error("Set HISTORICAL_DATA_DIR env var or update LOCAL_PARQUET_DIR in the script")
        sys.exit(1)

    years_to_run = [args.year] if args.year else YEARS
    log.info(f"Backfill: {years_to_run[0]}–{years_to_run[-1]} | dry_run={args.dry_run} | ALL 389 commodities")

    summary, meta_frames = [], []
    t0 = datetime.now()

    for year in years_to_run:
        res, meta = process_year(year, args.dry_run)
        summary.append(res)
        if meta is not None:
            meta_frames.append(meta)

    # Build commodity index from all processed years
    if meta_frames and not args.dry_run:
        build_and_upload_commodity_index(meta_frames, GCS_BUCKET)

    elapsed = (datetime.now() - t0).total_seconds() / 60
    total   = sum(r["rows"] for r in summary)
    ok      = sum(1 for r in summary if r["status"] == "success")
    log.info(f"\n{'='*55}")
    log.info(f"DONE — {elapsed:.1f} min | Years OK: {ok}/{len(years_to_run)} | Total rows: {total:,}")
    errs = [r["year"] for r in summary if r["status"] == "error"]
    if errs:
        log.warning(f"Errors in years: {errs}")


if __name__ == "__main__":
    main()