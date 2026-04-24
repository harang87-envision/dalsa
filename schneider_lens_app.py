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
    page_title="Schneider-Kreuznach \ub80c\uc988 \ubb38\uc11c \ud655\uc778\uae30",
    page_icon="\ud83d\udd2d",
    layout="wide",
    initial_sidebar_state="expanded",
)

BASE_URL = "https://schneiderkreuznach.com"
SITEMAP  = BASE_URL + "/sitemap.xml"

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
    family   = parts[1].replace("-", " ").title() if len(parts) > 1 else ""

    datasheet_url = ""
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True).lower()
        href = a["href"]
        if text == "datasheet" and ("download_file" in href or href.endswith(".pdf")):
            datasheet_url = href if href.startswith("http") else BASE_URL + href
            break

    body_text = soup.get_text(" ", strip=True)
    focal = re.search(r"Focal length[:\s]+([0-9.,\s\-mmMM]+)", body_text)
    aper  = re.search(r"Aperture[:\s]+(F[\d.,\-]+)", body_text)

    return {
        "\uc81c\ud488\uba85":       name,
        "\uce74\ud14c\uace0\ub9ac":     category,
        "\ub80c\uc988 \ud328\ubc00\ub9ac":  family,
        "\ucd08\uc810\uac70\ub9ac":     focal.group(1).strip() if focal else "",
        "\uc870\ub9ac\uac1c":       aper.group(1).strip() if aper else "",
        "\uc81c\ud488 URL":     url,
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
        status_box.info("\ud83d\udd04 sitemap\uc5d0\uc11c \uc81c\ud488 URL \uc218\uc9d1 \uc911...")
        product_urls = get_product_urls_from_sitemap(session)
        total = len(product_urls)
        log_box.text(f"\ucd1d {total}\uac1c \uc81c\ud488 \ud398\uc774\uc9c0 \ubc1c\uacac")

        for i, url in enumerate(product_urls):
            status_box.info(f"\ud83d\udd04 [{i+1}/{total}] \uc81c\ud488 \ud398\uc774\uc9c0 \uc218\uc9d1 \uc911...")
            try:
                html = fetch_page(session, url)
                if not html:
                    continue
                record = parse_product_page(html, url)

                if record["Datasheet URL"]:
                    date_str, date_obj = get_datasheet_date(session, record["Datasheet URL"])
                    record["\uc5c5\ub370\uc774\ud2b8 \ub0a0\uc9dc"] = date_str
                    record["_date_obj"]    = date_obj
                else:
                    record["\uc5c5\ub370\uc774\ud2b8 \ub0a0\uc9dc"] = ""
                    record["_date_obj"]    = None

                all_records.append(record)
                log_box.text(
                    f"[{i+1}/{total}] {record['\uc81c\ud488\uba85'][:40]} "
                    f"| {record['\uc5c5\ub370\uc774\ud2b8 \ub0a0\uc9dc'] or '\ub0a0\uc9dc \uc5c6\uc74c'}"
                )
            except Exception as e:
                log_box.text(f"\u26a0\ufe0f [{i+1}] \uc624\ub958: {e} - \uac74\ub108\ub9c4")

            progress_bar.progress((i + 1) / total)
            time.sleep(delay)
    finally:
        session.close()
    return all_records


def to_excel_bytes(df):
    out = io.BytesIO()
    export = df.drop(columns=["_date_obj"], errors="ignore").copy()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        export.to_excel(writer, index=False, sheet_name="\ub80c\uc988\ubaa9\ub85d")
    return out.getvalue()


def to_csv_bytes(df):
    export = df.drop(columns=["_date_obj"], errors="ignore")
    return export.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")


with st.sidebar:
    st.markdown("## \ud83d\udd2d Schneider-Kreuznach")
    st.markdown("### \ub80c\uc988 \ubb38\uc11c \ud655\uc778\uae30")
    st.markdown("---")
    st.header("\u2699\ufe0f \uc218\uc9d1 \uc124\uc815")

    delay = st.slider(
        "\uc694\uccad \uac04\uaca9 (\ucd08)", 0.3, 2.0, 0.5, step=0.1,
        help="\ub108\ubb34 \uc9e7\uc73c\uba74 \uc11c\ubc84\uc5d0\uc11c \ucc28\ub2e8\ub420 \uc218 \uc788\uc74c"
    )

    st.markdown("---")
    st.header("\ud83d\udd0d \ud544\ud130")

    categories = [
        "\uc804\uccb4", "C Mount Lenses", "Fast Lenses", "Telecentric Lenses",
        "Swir Lenses", "Large Format Lenses", "Liquid Lenses",
        "Line Scan Lenses", "V Mount Lenses"
    ]
    selected_cat = st.selectbox("\uce74\ud14c\uace0\ub9ac", categories)
    keyword      = st.text_input("\uc81c\ud488\uba85 \uac80\uc0c9", placeholder="\uc608: Citrine, Aquamarine")
    since_date   = st.date_input(
        "\uc774 \ub0a0\uc9dc \uc774\ud6c4 \uc5c5\ub370\uc774\ud2b8", value=None,
        min_value=datetime(2010, 1, 1).date(),
        max_value=datetime.today().date(),
    )

    st.markdown("---")
    run_btn  = st.button("\ud83d\ude80 \uc218\uc9d1 \uc2dc\uc791", use_container_width=True, type="primary")
    comp_btn = st.button("\ud83c\udd95 \uc2e0\uc81c\ud488 \ube44\uad50", use_container_width=True,
                         help="\uc774\uc804 \uc218\uc9d1 \uacb0\uacfc\uc640 \ube44\uad50\ud574\uc11c \uc0c8 \uc81c\ud488 \ud655\uc778")


st.title("\ud83d\udd2d Schneider-Kreuznach")
st.subheader("\ub80c\uc988 Datasheet \uc5c5\ub370\uc774\ud2b8 & \uc2e0\uc81c\ud488 \ud655\uc778\uae30")
st.caption("sitemap \u2192 \uac1c\ubcc4 \uc81c\ud488 \ud398\uc774\uc9c0 \u2192 Datasheet Last-Modified \ud5e4\ub354 \ubc29\uc2dd\uc73c\ub85c \ub0a0\uc9dc \uc218\uc9d1")

if "df_result" not in st.session_state: st.session_state["df_result"] = None
if "df_prev"   not in st.session_state: st.session_state["df_prev"]   = None
if "last_run"  not in st.session_state: st.session_state["last_run"]  = None

if run_btn:
    if st.session_state["df_result"] is not None:
        st.session_state["df_prev"] = st.session_state["df_result"].copy()
    st.session_state["df_result"] = None
    status_box   = st.empty()
    progress_bar = st.progress(0)
    log_box      = st.empty()
    status_box.info("\ud83d\udd04 \uc218\uc9d1 \uc2dc\uc791... (261\uac1c \uc81c\ud488 \xd7 \uc694\uccad 2\ud68c = \uc57d 5~10\ubd84 \uc18c\uc694)")
    try:
        records = scrape_all(delay, status_box, progress_bar, log_box)
        if not records:
            status_box.error("\u274c \uc218\uc9d1\ub41c \ub370\uc774\ud130\uac00 \uc5c6\uc2b5\ub2c8\ub2e4.")
        else:
            df = pd.DataFrame(records)
            st.session_state["df_result"] = df
            st.session_state["last_run"]  = datetime.now().strftime("%Y-%m-%d %H:%M")
            status_box.success(f"\u2705 \uc218\uc9d1 \uc644\ub8cc! \uc804 {len(df):,}\uac74")
            progress_bar.progress(1.0)
    except Exception as e:
        status_box.error(f"\u274c \uc624\ub958: {e}")


df = st.session_state.get("df_result")

if df is not None and not df.empty:
    filtered = df.copy()
    if selected_cat != "\uc804\uccb4":
        filtered = filtered[filtered["\uce74\ud14c\uace0\ub9ac"].str.lower() == selected_cat.lower()]
    if keyword:
        mask = (
            filtered["\uc81c\ud488\uba85"].str.contains(keyword, case=False, na=False) |
            filtered["\ub80c\uc988 \ud328\ubc00\ub9ac"].str.contains(keyword, case=False, na=False)
        )
        filtered = filtered[mask]
    if since_date:
        since_dt = datetime.combine(since_date, datetime.min.time())
        filtered = filtered[filtered["_date_obj"].notna() & (filtered["_date_obj"] >= since_dt)]

    dated   = filtered[filtered["_date_obj"].notna()]
    no_date = filtered[filtered["_date_obj"].isna()]

    if comp_btn and st.session_state["df_prev"] is not None:
        prev_urls = set(st.session_state["df_prev"]["\uc81c\ud488 URL"].tolist())
        curr_urls = set(df["\uc81c\ud488 URL"].tolist())
        new_urls  = curr_urls - prev_urls
        st.markdown("---")
        if new_urls:
            st.markdown(f"### \ud83c\udd95 \uc2e0\uc81c\ud488 \ubc1c\uacac! ({len(new_urls)}\uac1c)")
            new_df = df[df["\uc81c\ud488 URL"].isin(new_urls)][
                ["\uc81c\ud488\uba85", "\uce74\ud14c\uace0\ub9ac", "\ub80c\uc988 \ud328\ubc00\ub9ac", "\uc5c5\ub370\uc774\ud2b8 \ub0a0\uc9dc", "Datasheet URL", "\uc81c\ud488 URL"]
            ].reset_index(drop=True)
            st.dataframe(new_df, use_container_width=True, hide_index=True,
                         column_config={
                             "\uc81c\ud488 URL": st.column_config.LinkColumn("\uc81c\ud488 URL"),
                             "Datasheet URL": st.column_config.LinkColumn("Datasheet"),
                         })
        else:
            st.success("\u2705 \uc774\uc804 \uc218\uc9d1 \ub300\ube44 \uc2e0\uc81c\ud488 \uc5c6\uc74c")

    st.markdown("---")
    if st.session_state["last_run"]:
        st.caption(f"\ub9c8\uc9c0\ub9c9 \uc218\uc9d1: {st.session_state['last_run']}")

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("\uc804\uccb4 \uc81c\ud488",   f"{len(df):,}\uac1c")
    col2.metric("\ud544\ud130 \uacb0\uacfc",  f"{len(filtered):,}\uac1c")
    col3.metric("\ub0a0\uc9dc \uc788\uc74c",  f"{len(dated):,}\uac1c")
    col4.metric("\ub0a0\uc9dc \uc5c6\uc74c",  f"{len(no_date):,}\uac1c")
    if not dated.empty:
        col5.metric("\uac00\uc7a5 \ucd5c\uadfc", dated.loc[dated["_date_obj"].idxmax(), "\uc5c5\ub370\uc774\ud2b8 \ub0a0\uc9dc"])

    if not dated.empty:
        st.markdown("---")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### \ud83c\udd95 \uac00\uc7a5 \ucd5c\uadfc \uc5c5\ub370\uc774\ud2b8 TOP 5")
            st.dataframe(
                dated.nlargest(5, "_date_obj")[["\uc81c\ud488\uba85", "\uce74\ud14c\uace0\ub9ac", "\ub80c\uc988 \ud328\ubc00\ub9ac", "\uc5c5\ub370\uc774\ud2b8 \ub0a0\uc9dc"]].reset_index(drop=True),
                use_container_width=True, hide_index=True,
            )
        with c2:
            st.markdown("#### \ud83d\udcc5 \uac00\uc7a5 \uc624\ub798\ub41c \uc5c5\ub370\uc774\ud2b8 TOP 5")
            st.dataframe(
                dated.nsmallest(5, "_date_obj")[["\uc81c\ud488\uba85", "\uce74\ud14c\uace0\ub9ac", "\ub80c\uc988 \ud328\ubc00\ub9ac", "\uc5c5\ub370\uc774\ud2b8 \ub0a0\uc9dc"]].reset_index(drop=True),
                use_container_width=True, hide_index=True,
            )

    st.markdown("---")
    st.markdown("#### \ud83d\udcca \ud1b5\uacc4 \ucc28\ud2b8")
    ch1, ch2 = st.columns(2)
    with ch1:
        if not dated.empty:
            dc = dated.copy()
            dc["\uc5f0\ub3c4"] = dc["_date_obj"].dt.year.astype(str)
            yc = dc["\uc5f0\ub3c4"].value_counts().sort_index(ascending=False).reset_index()
            yc.columns = ["\uc5f0\ub3c4", "\uac74\uc218"]
            fig1 = px.bar(yc, x="\uc5f0\ub3c4", y="\uac74\uc218", title="\uc5f0\ub3c4\ubcc4 \uc5c5\ub370\uc774\ud2b8 \uac74\uc218",
                          color="\uac74\uc218", color_continuous_scale="Blues", text="\uac74\uc218")
            fig1.update_traces(textposition="outside")
            fig1.update_layout(showlegend=False, coloraxis_showscale=False)
            st.plotly_chart(fig1, use_container_width=True)
    with ch2:
        cc = filtered["\uce74\ud14c\uace0\ub9ac"].value_counts().reset_index()
        cc.columns = ["\uce74\ud14c\uace0\ub9ac", "\uac74\uc218"]
        fig2 = px.pie(cc, names="\uce74\ud14c\uace0\ub9ac", values="\uac74\uc218",
                      title="\uce74\ud14c\uace0\ub9ac\ubcc4 \uc81c\ud488 \ube44\uc728", hole=0.4)
        fig2.update_traces(textposition="inside", textinfo="label+percent")
        st.plotly_chart(fig2, use_container_width=True)

    st.markdown("---")
    st.markdown(f"#### \ud83d\udccb \uc804\uccb4 \ub80c\uc988 \ubaa9\ub85d ({len(filtered):,}\uac1c)")
    show_cols = ["\uc81c\ud488\uba85", "\uce74\ud14c\uace0\ub9ac", "\ub80c\uc988 \ud328\ubc00\ub9ac", "\ucd08\uc810\uac70\ub9ac", "\uc870\ub9ac\uac1c", "\uc5c5\ub370\uc774\ud2b8 \ub0a0\uc9dc", "Datasheet URL", "\uc81c\ud488 URL"]
    st.dataframe(
        filtered[show_cols].reset_index(drop=True),
        use_container_width=True, hide_index=True,
        column_config={
            "Datasheet URL": st.column_config.LinkColumn("Datasheet", display_text="\ud83d\udcf3"),
            "\uc81c\ud488 URL": st.column_config.LinkColumn("\uc81c\ud488 \ud398\uc774\uc9c0", display_text="\ud83d\udd17"),
        },
        height=500,
    )

    st.markdown("---")
    st.markdown("#### \ud83d\udcbe \ud30c\uc77c \uc800\uc7a5")
    dl1, dl2, _ = st.columns([1, 1, 3])
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    with dl1:
        st.download_button(
            "\ud83d\udcf3 CSV", data=to_csv_bytes(filtered),
            file_name=f"schneider_lenses_{ts}.csv", mime="text/csv",
            use_container_width=True,
        )
    with dl2:
        try:
            st.download_button(
                "\ud83d\udcca Excel", data=to_excel_bytes(filtered),
                file_name=f"schneider_lenses_{ts}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        except Exception:
            st.caption("pip3 install openpyxl")

else:
    st.markdown("---")
    st.info("\ud83d\udc48 \uc67c\ucabd \uc0ac\uc774\ub4dc\ubc14\uc5d0\uc11c \uc218\uc9d1 \uc2dc\uc791 \ubc84\ud2bc\uc744 \ub204\ub974\uc138\uc694.")
    st.markdown("""
    ### \ud83d\udcd6 \uc0ac\uc6a9 \ubc29\ubc95
    1. **\uc218\uc9d1 \uc2dc\uc791** \u2192 sitemap\uc5d0\uc11c 261\uac1c \uc81c\ud488 \ud398\uc774\uc9c0 \uc790\ub3d9 \uc218\uc9d1
    2. \uac01 \uc81c\ud488 Datasheet\uc758 Last-Modified \ub0a0\uc9dc \ud655\uc778
    3. **\uc2e0\uc81c\ud488 \ube44\uad50** \u2192 \uc774\uc804 \uc218\uc9d1\uacfc \ube44\uad50\ud574\uc11c \uc0c8\ub85c \ucd94\uac00\ub41c \uc81c\ud488 \ud655\uc778
    4. \ud544\ud130/\uac80\uc0c9 \ud6c4 CSV/Excel \ub2e4\uc6b4\ub85c\ub4dc

    ### \u23f1\ufe0f \uc18c\uc694 \uc2dc\uac04
    - \uc804\uccb4 \uc218\uc9d1: \uc57d 5~10\ubd84 (261\uac1c \xd7 \uc694\uccad 2\ud68c)
    - \uc694\uccad \uac04\uaca9\uc744 \ub298\ub9ac\uba74 \uc548\uc815\uc801\uc774\uc9c0\ub9cc \ub354 \uc624\ub798 \uac78\ub9bc
    """)

st.markdown("---")
st.caption("\u00a9 Schneider-Kreuznach | \uacf5\uac1c\ub41c \uc6f9\ud398\uc774\uc9c0 \ub370\uc774\ud130\ub97c \uc218\uc9d1\ud569\ub2c8\ub2e4.")
