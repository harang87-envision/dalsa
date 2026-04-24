#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime
import time
import re
import io
import plotly.express as px

# ─── 페이지 설정 ────────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Teledyne 문서 업데이트 확인",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── 상수 ──────────────────────────────────────────────────────────────────────────────────────────────────────────
BASE_URL = "https://www.teledynevisionsolutions.com"
DOC_URL  = BASE_URL + "/support/support-center/documentation/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

DOC_TYPES = [
    "전체",
    "Datasheet", "User Manual", "Quick Start Guide",
    "Certification", "Brochure", "Application Note",
    "Technical Reference", "Imaging Specification",
    "Drawing", "Product Change Notification",
    "Camera Reference", "Programmers Guide",
    "Configuration Guide", "Installation Guide",
    "Release Notes", "Flyer", "White Paper", "Tech Note",
]

def parse_english_date(date_str: str):
    date_str = date_str.strip()
    if not date_str:
        return None
    try:
        m = re.match(
            r"(January|February|March|April|May|June|July|August|"
            r"September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})",
            date_str, re.IGNORECASE
        )
        if m:
            return datetime.strptime(
                f"{m.group(1)} {m.group(2)} {m.group(3)}", "%B %d %Y"
            )
    except Exception:
        pass
    return None


def fetch_page(session, url, retries=3):
    for attempt in range(retries):
        try:
            resp = session.get(url, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                return resp.text
            elif resp.status_code == 403:
                raise Exception("403 Forbidden - 접근이 차단되었습니다.")
            else:
                time.sleep(1)
        except requests.RequestException as e:
            if attempt == retries - 1:
                raise Exception(f"요청 실패: {e}")
            time.sleep(2)
    return None


def parse_page_html(html):
    soup = BeautifulSoup(html, "html.parser")
    items = soup.select('[data-js="RowClick"]')
    records = []

    for item in items:
        title = item.get("data-gtm-title", "")
        if not title:
            title_el = item.select_one(".Download-title")
            title = title_el.get_text(strip=True) if title_el else ""

        doc_type = item.get("data-gtm-type", "")
        if not doc_type:
            for cls in item.get("class", []):
                m = re.match(r"FilterId-(.+)", cls)
                if m:
                    doc_type = m.group(1)
                    break

        date_span = item.select_one("span.rowClick")
        date_str = ""
        if date_span:
            raw = date_span.get_text(separator=" ", strip=True)
            date_str = raw.replace("Last Updated:", "").strip()

        date_obj = parse_english_date(date_str)

        dl_link = item.select_one(".Download a")
        dl_url = dl_link["href"] if dl_link and dl_link.get("href") else ""
        if dl_url.startswith("/"):
            dl_url = BASE_URL + dl_url

        records.append({
            "제목":          title,
            "문서 유형":     doc_type,
            "업데이트 날짜": date_str,
            "_date_obj":     date_obj,
            "다운로드 URL":  dl_url,
        })
    return records


def get_total_pages(html):
    soup = BeautifulSoup(html, "html.parser")
    max_page = 1
    for link in soup.select('a[href*="page="]'):
        m = re.search(r"page=(\d+)", link.get("href", ""))
        if m:
            n = int(m.group(1))
            if n > max_page:
                max_page = n
    return max_page


def get_total_results(html):
    m = re.search(r"([\d,]+)\s*(?:results?|개\s*결과)", html)
    return int(m.group(1).replace(",", "")) if m else 0


def scrape_all(max_pages, delay, status_box, progress_bar, log_box):
    all_records = []
    session = requests.Session()

    try:
        status_box.info("🔄 1페이지 로드 중...")
        html = fetch_page(session, DOC_URL)
        if not html:
            raise Exception("페이지 로드 실패")

        total_pages   = get_total_pages(html)
        total_results = get_total_results(html)

        if max_pages > 0:
            total_pages = min(total_pages, max_pages)

        records = parse_page_html(html)
        all_records.extend(records)
        progress_bar.progress(1 / max(total_pages, 1))
        log_box.text(
            f"페이지 1/{total_pages} 완료 ({len(records)}건) | "
            f"전체 {total_results:,}건"
        )

        for page in range(2, total_pages + 1):
            status_box.info(f"🔄 {page}/{total_pages} 페이지 수집 중...")
            url = f"{DOC_URL}?page={page}"
            try:
                time.sleep(delay)
                html = fetch_page(session, url)
                if not html:
                    log_box.text(f"⚠️ 페이지 {page} 로드 실패 - 건너맙")
                    continue
                records = parse_page_html(html)
                all_records.extend(records)
                log_box.text(
                    f"페이지 {page}/{total_pages} 완료 ({len(records)}건) | "
                    f"누적 {len(all_records):,}건"
                )
            except Exception as e:
                log_box.text(f"⚠️ 페이지 {page} 오류: {e} - 건너맙")

            progress_bar.progress(page / total_pages)

    finally:
        session.close()

    return all_records


def to_excel_bytes(df):
    out = io.BytesIO()
    export = df.drop(columns=["_date_obj"], errors="ignore").copy()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        export.to_excel(writer, index=False, sheet_name="문서목록")
    return out.getvalue()


def to_csv_bytes(df):
    export = df.drop(columns=["_date_obj"], errors="ignore")
    return export.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")


# ─── 사이드바 ──────────────────────────────────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 📄 Teledyne 문서 확인기")
    st.markdown("---")
    st.header("⚙️ 수집 설정")

    max_pages_opt = st.radio(
        "수집 범위",
        ["전체 (약 60페이지)", "일부만 수집"],
        index=0,
    )
    max_pages = 0
    if max_pages_opt == "일부만 수집":
        max_pages = st.slider("최대 페이지 수", 1, 60, 5)

    delay = st.slider(
        "페이지 로딩 대기 (초)", 0.5, 3.0, 1.0, step=0.5,
        help="페이지당 대기 시간. 너무 짧으면 차단될 수 있음"
    )

    st.markdown("---")
    st.header("🔍 필터")
    selected_type = st.selectbox("문서 유형", DOC_TYPES)
    keyword       = st.text_input("제목 키워드 검색", placeholder="예: Blackfly S")
    since_date    = st.date_input(
        "이 날짜 이후 업데이트", value=None,
        min_value=datetime(2010, 1, 1).date(),
        max_value=datetime.today().date(),
    )

    st.markdown("---")
    run_btn = st.button("🚀 수집 시작", use_container_width=True, type="primary")


# ─── 메인 영역 ──────────────────────────────────────────────────────────────────────────────────────────────────────────
st.title("📄 Teledyne Vision Solutions")
st.subheader("문서 업데이트 날짜 확인기")
st.caption("Documentation & Technical Drawings 페이지에서 모든 문서의 업데이트 날짜를 수집합니다.")

if "df_result" not in st.session_state:
    st.session_state["df_result"] = None

if run_btn:
    st.session_state["df_result"] = None
    status_box   = st.empty()
    progress_bar = st.progress(0)
    log_box      = st.empty()

    status_box.info("🔄 데이터 수집 시작...")

    try:
        records = scrape_all(max_pages, delay, status_box, progress_bar, log_box)
        if not records:
            status_box.error("❌ 수집된 데이터가 없습니다. 잠시 후 다시 시도해주세요.")
        else:
            df = pd.DataFrame(records)
            st.session_state["df_result"] = df
            status_box.success(f"✅ 수집 완료! 전 {len(df):,}건")
            progress_bar.progress(1.0)
    except Exception as e:
        status_box.error(f"❌ 오류 발생: {e}")


df = st.session_state.get("df_result")

if df is not None and not df.empty:
    filtered = df.copy()

    if selected_type != "전체":
        filtered = filtered[filtered["문서 유형"].str.lower() == selected_type.lower()]
    if keyword:
        filtered = filtered[filtered["제목"].str.contains(keyword, case=False, na=False)]
    if since_date:
        since_dt = datetime.combine(since_date, datetime.min.time())
        filtered = filtered[
            filtered["_date_obj"].notna() & (filtered["_date_obj"] >= since_dt)
        ]

    st.markdown("---")
    col1, col2, col3, col4 = st.columns(4)
    dated   = filtered[filtered["_date_obj"].notna()]
    no_date = filtered[filtered["_date_obj"].isna()]

    col1.metric("전체 문서 수",  f"{len(filtered):,}건")
    col2.metric("날짜 있음",   f"{len(dated):,}건")
    col3.metric("날짜 없음",   f"{len(no_date):,}건")
    if not dated.empty:
        col4.metric("가장 최근 업데이트",
                    dated.loc[dated["_date_obj"].idxmax(), "업데이트 날짜"])

    if not dated.empty:
        st.markdown("---")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### 🆕 가장 최근 업데이트 TOP 5")
            st.dataframe(
                dated.nlargest(5, "_date_obj")[
                    ["제목", "문서 유형", "업데이트 날짜", "다운로드 URL"]
                ].reset_index(drop=True),
                use_container_width=True, hide_index=True,
            )
        with c2:
            st.markdown("#### 📅 가장 오래된 업데이트 TOP 5")
            st.dataframe(
                dated.nsmallest(5, "_date_obj")[
                    ["제목", "문서 유형", "업데이트 날짜", "다운로드 URL"]
                ].reset_index(drop=True),
                use_container_width=True, hide_index=True,
            )

    st.markdown("---")
    st.markdown("#### 📊 통계 차트")
    ch1, ch2 = st.columns(2)

    with ch1:
        if not dated.empty:
            dc = dated.copy()
            dc["연도"] = dc["_date_obj"].dt.year.astype(str)
            yc = dc["연도"].value_counts().sort_index(ascending=False).reset_index()
            yc.columns = ["연도", "건수"]
            fig1 = px.bar(yc, x="연도", y="건수", title="연도별 업데이트 건수",
                          color="건수", color_continuous_scale="Blues", text="건수")
            fig1.update_traces(textposition="outside")
            fig1.update_layout(showlegend=False, coloraxis_showscale=False)
            st.plotly_chart(fig1, use_container_width=True)

    with ch2:
        tc = filtered["문서 유형"].value_counts().reset_index()
        tc.columns = ["문서 유형", "건수"]
        fig2 = px.pie(tc, names="문서 유형", values="건수",
                      title="문서 유형별 비율", hole=0.4)
        fig2.update_traces(textposition="inside", textinfo="label+percent")
        st.plotly_chart(fig2, use_container_width=True)

    st.markdown("---")
    st.markdown(f"#### 📋 전체 문서 목록 ({len(filtered):,}건)")
    st.dataframe(
        filtered[["제목", "문서 유형", "업데이트 날짜", "다운로드 URL"]].reset_index(drop=True),
        use_container_width=True, hide_index=True,
        column_config={
            "다운로드 URL": st.column_config.LinkColumn(
                "다운로드 URL", display_text="📳 다운로드"
            ),
        },
        height=450,
    )

    st.markdown("---")
    st.markdown("#### 💾 파일 저장")
    dl1, dl2, _ = st.columns([1, 1, 3])
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    with dl1:
        st.download_button(
            "📳 CSV 다운로드", data=to_csv_bytes(filtered),
            file_name=f"teledyne_docs_{ts}.csv", mime="text/csv",
            use_container_width=True,
        )
    with dl2:
        try:
            st.download_button(
                "📊 Excel 다운로드", data=to_excel_bytes(filtered),
                file_name=f"teledyne_docs_{ts}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        except Exception:
            st.caption("Excel 저장 실패: pip3 install openpyxl")

else:
    st.markdown("---")
    st.info("👈 왼쪽 사이드바에서 설정 후 수집 시작 버튼을 누르세요.")
    st.markdown("""
    ### 📖 사용 방법
    1. 수집 범위 선택 (전체 또는 일부 페이지)
    2. 필터 설정 (문서 유형 / 키워드 / 날짜)
    3. 수집 시작 클릭
    4. 결과 확인 후 CSV / Excel 다운로드
    """)

st.markdown("---")
st.caption("© Teledyne Vision Solutions | 이 앱은 공개된 웹페이지 데이터를 수집합니다.")
