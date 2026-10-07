from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import pandas as pd

from bi_pipeline.agents.bi_analyst_agent import BIAnalystAgent
from bi_pipeline.agents.semantic_kpi_agent import BISemanticKPIAgent

logging.basicConfig(level=logging.WARNING)


def build_olist_mart(base_dir: Path, sample_limit: int = 15000) -> pd.DataFrame:
    orders_p = base_dir / "olist_orders_dataset.csv"
    items_p = base_dir / "olist_order_items_dataset.csv"
    products_p = base_dir / "olist_products_dataset.csv"
    trans_p = base_dir / "product_category_name_translation.csv"
    customers_p = base_dir / "olist_customers_dataset.csv"

    orders = pd.read_csv(orders_p, usecols=["order_id", "customer_id", "order_status", "order_purchase_timestamp"])
    orders = orders[orders["order_status"] == "delivered"].head(sample_limit)

    items = pd.read_csv(items_p, usecols=["order_id", "order_item_id", "product_id", "price", "freight_value"])
    products = pd.read_csv(products_p, usecols=["product_id", "product_category_name"])
    customers = pd.read_csv(customers_p, usecols=["customer_id", "customer_state", "customer_city"])

    df = items.merge(orders, on="order_id", how="inner")
    df = df.merge(products, on="product_id", how="left")
    df = df.merge(customers, on="customer_id", how="left")

    if trans_p.is_file():
        trans = pd.read_csv(trans_p)
        df = df.merge(trans, on="product_category_name", how="left")
        df["category"] = df["product_category_name_english"].fillna(df["product_category_name"]).fillna("other")
    else:
        df["category"] = df["product_category_name"].fillna("other")

    df = df.rename(columns={
        "price": "sales",
        "order_item_id": "quantity",
        "order_purchase_timestamp": "order_date",
        "customer_state": "region",
    })
    return df


def main():
    base_dir = Path(__file__).resolve().parents[1]
    print(f"Building analytical mart from Olist CSVs in: {base_dir}")

    t0 = time.perf_counter()
    mart = build_olist_mart(base_dir, sample_limit=25000)
    build_time = time.perf_counter() - t0
    print(f"Loaded mart with {len(mart):,} transaction item rows across {mart['order_id'].nunique():,} orders in {build_time:.2f}s")

    agent5 = BISemanticKPIAgent()
    sem_state = agent5.analyze(mart, dataset_name="Olist Brazilian E-Commerce", domain_hint="retail ecommerce orders")

    agent6 = BIAnalystAgent(z_threshold=2.0)
    analyst_state = agent6.analyze(sem_state)

    print("\n" + analyst_state.executive_narrative)


if __name__ == "__main__":
    main()
