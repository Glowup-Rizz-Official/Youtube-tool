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

# --- [2. 데이터 설정] ---
COUNTRIES = {
    "대한민국": "KR", "미국": "US", "일본": "JP", "영국": "GB", 
    "베트남": "VN", "태국": "TH", "인도네시아": "ID", "대만": "TW"
}

SUB_RANGES = {
    "전체": (0, 100000000),
    "1만 미만": (0, 10000),
    "1만 ~ 5만": (10000, 50000),
    "5만 ~ 10만": (50000, 100000),
    "10만 ~ 50만": (100000, 500000),
    "50만 ~ 100만": (500000, 1000000),
    "100만 이상": (1000000, 100000000)
}

# --- [3. UI 설정] ---
st.set_page_config(page_title="Glowup Rizz - YOUTUBE 검색 엔진", layout="wide")

with st.sidebar:
    try:
        st.image("logo.png", use_container_width=True)
    except:
        pass
    st.markdown("---")
    st.info("🚀 **Glowup Rizz v3.5**\n원클릭 딥리서치 분석 도구")

# 제목 및 문의처 (변경 금지 유지)
st.title("🌐 YOUTUBE 크리에이터 검색 엔진")
st.markdown("문의 010-8900-6756")
st.markdown("---")

# --- [4. 메인 검색 폼] ---
with st.form("search_form"):
    r1_col1, r1_col2, r1_col3 = st.columns([4, 1.2, 0.8])
    with r1_col1:
        keywords_input = st.text_input("🔎 검색 키워드", placeholder="애견 카페, 강아지 (쉼표 구분)", label_visibility="collapsed")
    with r1_col2:
        selected_country = st.selectbox("분석 국가", list(COUNTRIES.keys()), label_visibility="collapsed")
    with r1_col3:
        submit_button = st.form_submit_button("🚀 검색")

    r2_col1, r2_col2, r2_col3 = st.columns(3)
    with r2_col1:
        selected_sub_range = st.selectbox("🎯 구독자 범위 선택", list(SUB_RANGES.keys()))
        min_subs, max_subs = SUB_RANGES[selected_sub_range]
    with r2_col2:
        efficiency_target = st.slider("📈 최소 조회수 효율 (%)", 0, 100, 30) / 100
    with r2_col3:
        max_res = st.number_input("🔍 키워드당 분석 수", 5, 50, 20)

st.markdown("---")

# --- [5. 로직 함수들] ---
def handle_api_error(e):
    if "quotaExceeded" in str(e):
        st.error("🔴 **YouTube API 할당량이 소진되었습니다.** 내일 다시 시도해 주세요.")
        st.stop()
    else:
        st.error(f"⚠️ 오류 발생: {e}")

def extract_email_ai(desc):
    if not desc or len(desc.strip()) < 5: return "채널 설명 없음"
    prompt = f"다음 텍스트에서 이메일을 추출해줘. 없으면 오직 'None'이라고만 답해: {desc}"
    try:
        response = model.generate_content(prompt)
        res = response.text.strip()
        if "@" in res and len(res) < 50: return res
        return "AI 분석 어려움 (직접 확인 필요)"
    except: return "데이터 확인 필요"

def check_performance(up_id, subs):
    if not (min_subs <= subs <= max_subs): return False, 0, 0
    try:
        req = YOUTUBE.playlistItems().list(part="contentDetails", playlistId=up_id, maxResults=15).execute()
        v_ids = [i['contentDetails']['videoId'] for i in req.get('items', [])]
        v_res = YOUTUBE.videos().list(part="statistics,contentDetails", id=",".join(v_ids)).execute()
        longforms = [v for v in v_res['items'] if 'M' in v['contentDetails']['duration'] or 'H' in v['contentDetails']['duration']][:10]
        if not longforms: return False, 0, 0
        avg_v = sum(int(v['statistics'].get('viewCount', 0)) for v in longforms) / len(longforms)
        eff = avg_v / subs
        return (eff >= efficiency_target), avg_v, eff
    except Exception as e:
        if "quotaExceeded" in str(e): handle_api_error(e)
        return False, 0, 0

def get_recent_videos_detail(up_id, count=15):
    try:
        req = YOUTUBE.playlistItems().list(part="snippet,contentDetails", playlistId=up_id, maxResults=count).execute()
        v_ids = [i['contentDetails']['videoId'] for i in req.get('items', [])]
        v_res = YOUTUBE.videos().list(part="snippet,statistics", id=",".join(v_ids)).execute()
        
        video_details = []
        for v in v_res.get('items', []):
            pub_at = datetime.strptime(v['snippet']['publishedAt'], '%Y-%m-%dT%H:%M:%SZ').strftime('%Y-%m-%d')
            video_details.append({
                "영상 제목": v['snippet']['title'],
                "업로드 일자": pub_at,
                "조회수": int(v['statistics'].get('viewCount', 0)),
                "영상 링크": f"https://youtu.be/{v['id']}"
            })
        return pd.DataFrame(video_details)
    except: return pd.DataFrame()

# --- [6. 실행 프로세스] ---
if "search_results" not in st.session_state:
    st.session_state.search_results = None

if submit_button:
    if not keywords_input:
        st.warning("⚠️ 검색어를 입력해주세요.")
    else:
        kws = [k.strip() for k in keywords_input.split(",")]
        final_list = []
        prog = st.progress(0)
        curr = 0
        total = len(kws) * max_res

        with st.status("🔍 분석 중...", expanded=True) as status:
            for kw in kws:
                search = YOUTUBE.search().list(q=kw, part="snippet", type="channel", maxResults=max_res, regionCode=COUNTRIES[selected_country]).execute()
                for item in search['items']:
                    curr += 1
                    prog.progress(min(curr/total, 1.0))
                    try:
                        ch = YOUTUBE.channels().list(part="snippet,statistics,contentDetails", id=item['snippet']['channelId']).execute()['items'][0]
                        subs = int(ch['statistics'].get('subscriberCount', 0))
                        up_id = ch['contentDetails']['relatedPlaylists']['uploads']
                        is_ok, avg_v, eff = check_performance(up_id, subs)
                        if is_ok:
                            final_list.append({
                                "채널명": ch['snippet']['title'],
                                "구독자": subs,
                                "평균 조회수": round(avg_v),
                                "효율": f"{eff*100:.1f}%",
                                "이메일": extract_email_ai(ch['snippet']['description']),
                                "URL": f"https://youtube.com/channel/{ch['id']}",
                                "프로필": ch['snippet']['thumbnails']['default']['url'],
                                "upload_id": up_id
                            })
                    except: continue
            status.update(label="✅ 분석 완료!", state="complete", expanded=False)
        st.session_state.search_results = pd.DataFrame(final_list)

# 결과 출력 및 딥리서치 자동 연동
if isinstance(st.session_state.search_results, pd.DataFrame) and not st.session_state.search_results.empty:
    st.subheader("📊 분석 결과")
    st.caption("💡 채널을 클릭하면 하단에 최신 영상 상세 리스트가 즉시 나타납니다.")
    
    # 1단계 리스트업 표
    event = st.dataframe(
        st.session_state.search_results,
        column_config={
            "프로필": st.column_config.ImageColumn("프로필", width="small"),
            "URL": st.column_config.LinkColumn("채널 링크", display_text="바로가기"),
            "구독자": st.column_config.NumberColumn(format="%d명"),
            "평균 조회수": st.column_config.NumberColumn(format="%d회"),
            "upload_id": None # 숨김
        },
        use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row"
    )

    # 행 선택 시 즉시 '딥리서치' 섹션 표시
    if event.selection.rows:
        selected_idx = event.selection.rows[0]
        ch_info = st.session_state.search_results.iloc[selected_idx]
        
        st.markdown("---")
        st.subheader(f"🔍 '{ch_info['채널명']}' 딥리서치 (최근 15개 영상 성과)")
        
        with st.spinner("최신 영상 상세 데이터를 분석 중입니다..."):
            detail_df = get_recent_videos_detail(ch_info['upload_id'])
            
            if not detail_df.empty:
                st.dataframe(
                    detail_df,
                    column_config={
                        "영상 링크": st.column_config.LinkColumn("영상 보기", display_text="이동"),
                        "조회수": st.column_config.NumberColumn(format="%d회")
                    },
                    use_container_width=True, hide_index=True
                )
                
                # CSV 다운로드 버튼 제공
                csv = detail_df.to_csv(index=False).encode('utf-8-sig')
                st.download_button(f"📥 {ch_info['채널명']} 상세 데이터 다운로드", data=csv, file_name=f"DeepResearch_{ch_info['채널명']}.csv")
            else:
                st.warning("영상 데이터를 불러오지 못했습니다.")
