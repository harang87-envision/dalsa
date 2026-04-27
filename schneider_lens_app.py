#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime
from email.utils import parsedate_to_datetime
import time
import re
import io
import plotly.express as px
from xml.etree import ElementTree as ET

st.set_page_config(
    page_title="Schneider-Kreuznach Lens Document Tracker",
    page_icon=":telescope:",
    layout="wide",
    initial_sidebar_state="expanded",
)

BASE_URL = "https://schneiderkreuznach.com"
SITEMAP = BASE_URL + "/sitemap.xml"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}


def get_product_urls_from_sitemap(session):
    resp = session.get(SITEMAP, headers=HEADERS, timeout=15)
    root = ET.fromstring(resp.text)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    all_urls = [loc.text for loc in root.findall(".//sm:loc", ns)]
    product_urls = []
    for u in all_urls:
        if "/en/industrial-optics/lenses/" not in u:
            continue
        path = u.replace(BASE_URL, "")
        depth = len([p for p in path.split("/") if p])
        if depth >= 6:
            product_urls.append(u)
    return product_urls


def parse_product_page(html, url):
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    name = h1.get_text(strip=True) if h1 else ""
    if not name:
        name = url.rstrip("/").split("/")[-1].replace("-", " ").title()
    parts = url.replace(BASE_URL + "/en/industrial-optics/lenses/", "").split("/")
    category = parts[0].replace("-", " ").title() if len(parts) > 0 else ""
    family = parts[1].replace("-", " ").title() if len(parts) > 1 else ""
    datasheet_url = ""
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True).lower()
        href = a["href"]
        if text == "datasheet" and ("download_file" in href or href.endswith(".pdf")):
            datasheet_url = href if href.startswith("http") else BASE_URL + href
            break
    body_text = soup.get_text(" ", strip=True)
    focal = re.search(r'Focal length[:\s]+([0-9.,\s\-mmMM]+)', body_text)
    aper = re.search(r'Aperture[:\s]+(F[\d.,\-]+)', body_text)
    return {
        "Product Name": name,
        "Category": category,
        "Lens Family": family,
        "Focal Length": focal.group(1).strip() if focal else "",
        "Aperture": aper.group(1).strip() if aper else "",
        "Product URL": url,
        "Datasheet URL": datasheet_url,
    }


def get_datasheet_date(session, url):
    if not url:
        return "", None
    try:
        resp = session.get(url, headers=HEADERS, timeout=15, stream=True)
        resp.close()
        lm = resp.headers.get("Last-Modified", "")
        if lm:
            dt = parsedate_to_datetime(lm)
            return dt.strftime("%B %d, %Y"), dt.replace(tzinfo=None)
    except Exception:
        pass
    return "", None


def fetch_page(session, url, retries=3):
    for attempt in range(retries):
        try:
            resp = session.get(url, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                return resp.text
            time.sleep(1)
        except requests.RequestException:
            if attempt == retries - 1:
                return None
            time.sleep(2)
    return None


def scrape_all(delay, status_box, progress_bar, log_box):
    session = requests.Session()
    all_records = []
    try:
        status_box.info("Collecting product URLs from sitemap...")
        product_urls = get_product_urls_from_sitemap(session)
        total = len(product_urls)
        log_box.text(f"Found {total} product pages")
        for i, url in enumerate(product_urls):
            status_box.info(f"[{i+1}/{total}] Collecting product page...")
            try:
                html = fetch_page(session, url)
                if not html:
                    continue
                record = parse_product_page(html, url)
                if record["Datasheet URL"]:
                    date_str, date_obj = get_datasheet_date(session, record["Datasheet URL"])
                    record["Update Date"] = date_str
                    record["_date_obj"] = date_obj
                else:
                    record["Update Date"] = ""
                    record["_date_obj"] = None
                all_records.append(record)
                log_box.text(
                    f"[{i+1}/{total}] {record['Product Name'][:40]} "
                    f"| {record['Update Date'] or 'No date'}"
                )
            except Exception as e:
                log_box.text(f"[{i+1}] Error: {e} - skipped")
            progress_bar.progress((i + 1) / total)
            time.sleep(delay)
    finally:
        session.close()
    return all_records


def to_excel_bytes(df):
    out = io.BytesIO()
    export = df.drop(columns=["_date_obj"], errors="ignore").copy()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        export.to_excel(writer, index=False, sheet_name="Lens List")
    return out.getvalue()


def to_csv_bytes(df):
    export = df.drop(columns=["_date_obj"], errors="ignore")
    return export.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")


with st.sidebar:
    st.markdown("## Schneider-Kreuznach")
    st.markdown("### Lens Document Tracker")
    st.markdown("---")
    st.header("Settings")
    delay = st.slider(
        "Request interval (sec)",
        0.3, 2.0, 0.5, step=0.1,
        help='Too short may cause server blocking'
    )
    st.markdown("---")
    st.header("Filters")
    categories = [
        "All",
        "C Mount Lenses",
        "Fast Lenses",
        "Telecentric Lenses",
        "Swir Lenses",
        "Large Format Lenses",
        "Liquid Lenses",
        "Line Scan Lenses",
        "V Mount Lenses",
    ]
    selected_cat = st.selectbox("Category", categories)
    keyword = st.text_input("Product name search", placeholder="e.g. Citrine, Aquamarine")
    since_date = st.date_input(
        "Updated after",
        value=None,
        min_value=datetime(2010, 1, 1).date(),
        max_value=datetime.today().date(),
    )
    st.markdown("---")
    run_btn = st.button("Start Collection", use_container_width=True, type="primary")
    comp_btn = st.button(
        "New Product Check",
        use_container_width=True,
        help='Compare with previous collection to find new products'
    )

st.title("Schneider-Kreuznach")
st.subheader("Lens Datasheet Update & New Product Tracker")
st.caption("sitemap -> product pages -> Datasheet Last-Modified header")

if "df_result" not in st.session_state:
    st.session_state["df_result"] = None
if "df_prev" not in st.session_state:
    st.session_state["df_prev"] = None
if "last_run" not in st.session_state:
    st.session_state["last_run"] = None

if run_btn:
    if st.session_state["df_result"] is not None:
        st.session_state["df_prev"] = st.session_state["df_result"].copy()
    st.session_state["df_result"] = None
    status_box = st.empty()
    progress_bar = st.progress(0)
    log_box = st.empty()
    status_box.info("Starting collection... (~5-10 min)")
    try:
        records = scrape_all(delay, status_box, progress_bar, log_box)
        if not records:
            status_box.error("No data collected.")
        else:
            df = pd.DataFrame(records)
            st.session_state["df_result"] = df
            st.session_state["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            status_box.success(f"Collection complete! Total {len(df):,} items")
            progress_bar.progress(1.0)
    except Exception as e:
        status_box.error(f"Error: {e}")

df = st.session_state.get("df_result")
if df is not None and not df.empty:
    filtered = df.copy()
    if selected_cat != "All":
        filtered = filtered[filtered["Category"].str.lower() == selected_cat.lower()]
    if keyword:
        mask = (
            filtered["Product Name"].str.contains(keyword, case=False, na=False)
            | filtered["Lens Family"].str.contains(keyword, case=False, na=False)
        )
        filtered = filtered[mask]
    if since_date:
        since_dt = datetime.combine(since_date, datetime.min.time())
        filtered = filtered[
            filtered["_date_obj"].notna() & (filtered["_date_obj"] >= since_dt)
        ]

    dated = filtered[filtered["_date_obj"].notna()]
    no_date = filtered[filtered["_date_obj"].isna()]

    if comp_btn and st.session_state["df_prev"] is not None:
        prev_urls = set(st.session_state["df_prev"]["Product URL"].tolist())
        curr_urls = set(df["Product URL"].tolist())
        new_urls = curr_urls - prev_urls
        st.markdown("---")
        if new_urls:
            st.markdown(f"### New Products Found! ({len(new_urls)} items)")
            new_df = df[df["Product URL"].isin(new_urls)][
                ["Product Name", "Category", "Lens Family", "Update Date", "Datasheet URL", "Product URL"]
            ].reset_index(drop=True)
            st.dataframe(
                new_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Product URL": st.column_config.LinkColumn("Product URL"),
                    "Datasheet URL": st.column_config.LinkColumn("Datasheet"),
                },
            )
        else:
            st.success("No new products compared to previous collection")

    st.markdown("---")
    if st.session_state["last_run"]:
        st.caption(f"Last collected: {st.session_state['last_run']}")

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Total Products", f"{len(df):,}")
    col2.metric("Filtered Results", f"{len(filtered):,}")
    col3.metric("With Date", f"{len(dated):,}")
    col4.metric("No Date", f"{len(no_date):,}")
    if not dated.empty:
        col5.metric("Most Recent", dated.loc[dated["_date_obj"].idxmax(), "Update Date"])

    if not dated.empty:
        st.markdown("---")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### Top 5 Most Recently Updated")
            top5 = (
                dated.nlargest(5, "_date_obj")[
                    ["Product Name", "Category", "Update Date", "Datasheet URL"]
                ].reset_index(drop=True)
            )
            st.dataframe(
                top5,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Datasheet URL": st.column_config.LinkColumn("Datasheet"),
                },
            )
        with c2:
            st.markdown("#### Updates by Month")
            dated2 = dated.copy()
            dated2["Month"] = dated2["_date_obj"].dt.to_period("M").astype(str)
            monthly = dated2.groupby("Month").size().reset_index(name="Count")
            monthly = monthly.sort_values("Month")
            fig = px.bar(monthly, x="Month", y="Count", title="Monthly Document Updates")
            st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")
    st.markdown("#### Product List")
    display_cols = ["Product Name", "Category", "Lens Family", "Focal Length", "Aperture", "Update Date", "Datasheet URL", "Product URL"]
    show_df = filtered[display_cols].reset_index(drop=True)
    st.dataframe(
        show_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Product URL": st.column_config.LinkColumn("Product URL"),
            "Datasheet URL": st.column_config.LinkColumn("Datasheet"),
        },
    )

    st.markdown("---")
    dl1, dl2 = st.columns(2)
    with dl1:
        st.download_button(
            "Download CSV",
            data=to_csv_bytes(filtered),
            file_name="schneider_lens_docs.csv",
            mime="text/csv",
        )
    with dl2:
        st.download_button(
            "Download Excel",
            data=to_excel_bytes(filtered),
            file_name="schneider_lens_docs.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
else:
    st.info("Press [Start Collection] in the sidebar to begin.")
    st.markdown("""
    ### How it works
    1. Reads product URLs from Schneider-Kreuznach sitemap
    2. Visits each product page (name, category, family, datasheet link)
    3. GET request to datasheet PDF to read Last-Modified header
    4. Displays results with filters and download options

    **New Product Check**: Run twice then press [New Product Check] to compare.
    """)
