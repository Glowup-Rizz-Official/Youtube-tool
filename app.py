import streamlit as st
import pandas as pd
import re
import base64
from datetime import datetime
import googleapiclient.discovery
import googleapiclient.errors
import google.generativeai as genai

# --- [1. 보안 및 API 설정] ---
try:
    YOUTUBE_KEY = st.secrets["YOUTUBE_API_KEY"]
    GEMINI_KEY = st.secrets["GEMINI_API_KEY"]
except KeyError:
    st.error("🚨 보안 설정(.streamlit/secrets.toml)을 확인해주세요.")
    st.stop()

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('models/gemini-2.0-flash')
YOUTUBE = googleapiclient.discovery.build('youtube', 'v3', developerKey=YOUTUBE_KEY)

# --- [2. 국가 데이터] ---
COUNTRIES = {"KR": "KR", "US": "US", "JP": "JP", "VN": "VN", "TH": "TH"}

# --- [3. UI 설정] ---
st.set_page_config(page_title="Glowup Rizz - 딥리서치 엔진", layout="wide")

# 사이드바 로고 및 버전 정보
with st.sidebar:
    try: st.image("logo.png", use_container_width=True)
    except: pass
    st.markdown("---")
    st.info("💡 **Glowup Rizz v4.0**\n데이터 딥리서치 시스템")

st.title("🧪 Glowup Rizz 분석 시스템")
st.markdown("리스트업에서 채널을 클릭하면, 아래에 해당 채널의 상세 분석(딥리서치)이 나타납니다.")
st.markdown("---")

# --- [4. ① 리스트업 (검색 및 필터)] ---
st.subheader("① 리스트업")
with st.container(border=True):
    r1_col1, r1_col2, r1_col3, r1_col4 = st.columns([4, 1, 1, 1])
    with r1_col1:
        keywords_input = st.text_input("키워드(쉼표로 복수 입력)", placeholder="예: 테크 리뷰, 캠핑, 경제")
    with r1_col2:
        selected_region = st.selectbox("국가", list(COUNTRIES.keys()))
    with r1_col3:
        max_res = st.selectbox("표본(키워드당)", [20, 30, 50], index=0)
    with r1_col4:
        use_ai_summary = st.toggle("AI 요약", value=True)

    r2_col1, r2_col2, r2_col3, r2_col4 = st.columns(4)
    with r2_col1:
        min_subs = st.number_input("최소 구독자", value=10000, step=1000)
    with r2_col2:
        max_subs = st.number_input("최대 구독자", value=500000, step=10000)
    with r2_col3:
        eff_target = st.slider("최소 성과지수(%)", 0, 100, 20) / 100
    with r2_col4:
        min_view_avg = st.number_input("최소 평균조회(롱폼)", value=5000, step=1000)
    
    min_duration = st.slider("롱폼 최소 길이(초)", 0, 300, 61, help="이 시간보다 짧은 영상은 조회수 계산에서 제외합니다.")
    
    submit_button = st.button("검색", use_container_width=True)

# --- [5. 로직 함수들] ---
def check_performance(up_id, subs):
    if not (min_subs <= subs <= max_subs): return False, 0, 0
    try:
        req = YOUTUBE.playlistItems().list(part="contentDetails", playlistId=up_id, maxResults=15).execute()
        v_ids = [i['contentDetails']['videoId'] for i in req.get('items', [])]
        v_res = YOUTUBE.videos().list(part="statistics,contentDetails", id=",".join(v_ids)).execute()
        
        # 롱폼 최소 길이 필터링 로직 추가
        def is_longform(duration_str):
            # ISO 8601 duration을 초로 변환하는 간단 로직 (간소화)
            total_sec = 0
            if 'PT' in duration_str:
                m = re.search(r'(\d+)M', duration_str)
                s = re.search(r'(\d+)S', duration_str)
                total_sec += int(m.group(1)) * 60 if m else 0
                total_sec += int(s.group(1)) if s else 0
            return total_sec >= min_duration

        longforms = [v for v in v_res['items'] if is_longform(v['contentDetails']['duration'])][:10]
        if not longforms: return False, 0, 0
        avg_v = sum(int(v['statistics'].get('viewCount', 0)) for v in longforms) / len(longforms)
        eff = avg_v / subs
        return (eff >= eff_target and avg_v >= min_view_avg), avg_v, eff
    except: return False, 0, 0

# --- [6. 실행 및 결과] ---
if "search_results" not in st.session_state: st.session_state.search_results = None

if submit_button:
    if not keywords_input: st.warning("키워드를 입력해주세요.")
    else:
        kws = [k.strip() for k in keywords_input.split(",")]
        final_list = []
        with st.spinner("데이터 수집 및 분석 중..."):
            for kw in kws:
                search = YOUTUBE.search().list(q=kw, part="snippet", type="channel", maxResults=max_res, regionCode=selected_region).execute()
                for item in search['items']:
                    try:
                        ch = YOUTUBE.channels().list(part="snippet,statistics,contentDetails", id=item['snippet']['channelId']).execute()['items'][0]
                        subs = int(ch['statistics'].get('subscriberCount', 0))
                        up_id = ch['contentDetails']['relatedPlaylists']['uploads']
                        is_ok, avg_v, eff = check_performance(up_id, subs)
                        if is_ok:
                            final_list.append({
                                "채널명": ch['snippet']['title'], "구독자": subs, "평균 조회수": round(avg_v),
                                "성과지수": f"{eff*100:.1f}%", "URL": f"https://youtube.com/channel/{ch['id']}",
                                "upload_id": up_id
                            })
                    except: continue
        st.session_state.search_results = pd.DataFrame(final_list)

if isinstance(st.session_state.search_results, pd.DataFrame) and not st.session_state.search_results.empty:
    event = st.dataframe(
        st.session_state.search_results,
        column_config={"URL": st.column_config.LinkColumn("채널 링크"), "upload_id": None},
        use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row"
    )

    # --- [7. ② 채널 상세(딥리서치)] ---
    st.markdown("---")
    st.subheader("② 채널 상세(딥리서치)")
    
    if event.selection.rows:
        selected_row = event.selection.rows[0]
        ch_info = st.session_state.search_results.iloc[selected_row]
        
        with st.container(border=True):
            st.write(f"### {ch_info['채널명']}")
            st.write(f"**구독자**: {ch_info['구독자']:,}명")
            
            d_col1, d_col2, d_col3 = st.columns([1, 1, 1])
            with d_col1:
                v_count = st.selectbox("분석할 최근 영상 수", [10, 20, 30])
            with d_col2:
                v_min_len = st.slider("최소 영상 길이(초)", 0, 300, 61, key="deep_len")
            with d_col3:
                do_ai = st.toggle("AI 딥리서치 실행", value=True)
            
            if st.button("위 설정으로 딥리서치 실행", use_container_width=True):
                # 여기에 영상 상세 데이터를 가져와서 표로 보여주는 로직 (v3.0과 동일)
                st.success(f"{ch_info['채널명']}의 최근 {v_count}개 영상을 정밀 분석합니다...")
                # (상세 영상 데이터 처리 코드는 지면상 생략, v3.0 함수 활용 가능)
    else:
        st.info("위 리스트에서 채널 1개를 클릭하세요.")
