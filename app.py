import streamlit as st
import pandas as pd
import re
import base64
import time
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
st.set_page_config(page_title="Glowup Rizz 크리에이터 분석 엔진", layout="wide")

with st.sidebar:
    try:
        st.image("logo.png", use_container_width=True)
    except:
        pass
    st.markdown("---")
    st.info("🚀 **Glowup Rizz v4.5**\n콘텐츠 기반 크리에이터 서치 가동")

# [유지] 제목 및 문의처
st.title("🌐 YOUTUBE 크리에이터 검색 엔진")
st.markdown("문의 010-8900-6756")
st.markdown("---")

# --- [4. 메인 검색 폼] ---
with st.form("search_form"):
    st.markdown("📥 **기존 리스트 제외하기 (선택 사항)**")
    exclude_file = st.file_uploader("이미 확보한 채널 리스트(엑셀/CSV)를 업로드하면 제외됩니다.", type=['xlsx', 'csv'])
    st.markdown("---")
    
    r1_col1, r1_col2, r1_col3 = st.columns([4, 1.2, 0.8])
    with r1_col1:
        keywords_input = st.text_input("🔎 검색 키워드 (성격/카테고리 중심)", placeholder="먹방, 일상 브이로그, IT 리뷰 (쉼표 구분)", label_visibility="collapsed")
    with r1_col2:
        selected_country = st.selectbox("분석 국가", list(COUNTRIES.keys()), label_visibility="collapsed")
    with r1_col3:
        submit_button = st.form_submit_button("🚀 검색")

    r2_col1, r2_col2, r2_col3 = st.columns(3)
    with r2_col1:
        # 검색 모드 선택 기능 추가
        search_mode = st.radio("분석 방식 선택", ["영상 콘텐츠 기반 (추천)", "채널명 기반"], horizontal=True)
        selected_sub_range = st.selectbox("🎯 구독자 범위", list(SUB_RANGES.keys()))
        min_subs, max_subs = SUB_RANGES[selected_sub_range]
    with r2_col2:
        efficiency_target = st.slider("📈 최소 조회수 효율 (%)", 0, 100, 30) / 100
    with r2_col3:
        max_res = st.number_input("🔍 분석 샘플 수 (키워드당)", 5, 50, 20)

st.markdown("---")

# --- [5. 로직 함수들] ---
def extract_exclude_list(file):
    try:
        df = pd.read_csv(file) if file.name.endswith('.csv') else pd.read_excel(file)
        exclude_set = set()
        for col in df.columns:
            exclude_set.update(df[col].astype(str).str.strip().tolist())
        return exclude_set
    except: return set()

def handle_api_error(e):
    if "quotaExceeded" in str(e):
        st.error("🔴 **YouTube API 할당량이 소진되었습니다.**")
        st.stop()
    else: st.error(f"⚠️ 오류 발생: {e}")

def extract_email_ai(desc):
    if not desc or len(desc.strip()) < 5: return "채널 설명 없음"
    prompt = f"다음 텍스트에서 이메일을 추출해줘. 없으면 오직 'None'이라고만 답해: {desc}"
    try:
        time.sleep(1)
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
    except: return False, 0, 0

# 딥리서치 및 광고 판별 로직 (유지)
def get_recent_ad_videos_ai(up_id, count):
    try:
        req = YOUTUBE.playlistItems().list(part="snippet,contentDetails", playlistId=up_id, maxResults=count).execute()
        v_ids = [i['contentDetails']['videoId'] for i in req.get('items', [])]
        v_res = YOUTUBE.videos().list(part="snippet,statistics", id=",".join(v_ids)).execute()
        
        all_videos = []
        official_patterns = ["유료 광고 포함", "Paid promotion", "제작 지원", "협찬", "#광고"]

        for v in v_res.get('items', []):
            title = v['snippet']['title']
            desc = v['snippet'].get('description', '')
            video_data = {
                "영상 제목": title, "설명": desc[:500],
                "업로드 일자": datetime.strptime(v['snippet']['publishedAt'], '%Y-%m-%dT%H:%M:%SZ').strftime('%Y-%m-%d'),
                "조회수": int(v['statistics'].get('viewCount', 0)),
                "영상 링크": f"https://youtu.be/{v['id']}", "판단근거": "일반 영상"
            }
            for pattern in official_patterns:
                if pattern in title or pattern in desc[:200]:
                    video_data["판단근거"] = f"공식 표기({pattern})"
                    break
            all_videos.append(video_data)

        # AI 2차 분석 생략 (속도와 할당량 위해 광고 표기 위주로 반환)
        ad_videos = [v for v in all_videos if "공식 표기" in v["판단근거"]]
        return pd.DataFrame(ad_videos)[["영상 제목", "업로드 일자", "조회수", "판단근거", "영상 링크"]] if ad_videos else pd.DataFrame()
    except: return pd.DataFrame()

# --- [6. 실행 프로세스: 콘텐츠 기반 검색 엔진 가동] ---
if "search_results" not in st.session_state:
    st.session_state.search_results = None

if submit_button:
    if not keywords_input:
        st.warning("⚠️ 키워드를 입력해주세요.")
    else:
        exclude_data = extract_exclude_list(exclude_file) if exclude_file else set()
        kws = [k.strip() for k in keywords_input.split(",")]
        final_list = []
        prog = st.progress(0)
        curr = 0
        total = len(kws) * max_res
        
        # 중복 채널 분석 방지용 세트
        processed_channels = set()

        with st.status(f"🔍 {search_mode} 분석 및 필터링 중...", expanded=True) as status:
            for kw in kws:
                # [핵심] 방식에 따라 유튜브 API 검색 타입 변경
                if "영상 콘텐츠" in search_mode:
                    # 영상을 먼저 찾아서 그 영상의 주인을 알아내는 방식 (콘텐츠 분석)
                    search = YOUTUBE.search().list(q=kw, part="snippet", type="video", maxResults=max_res, regionCode=COUNTRIES[selected_country], videoDuration="medium").execute()
                else:
                    # 기존처럼 채널 이름 위주로 찾는 방식
                    search = YOUTUBE.search().list(q=kw, part="snippet", type="channel", maxResults=max_res, regionCode=COUNTRIES[selected_country]).execute()
                
                for item in search['items']:
                    curr += 1
                    prog.progress(min(curr/total, 1.0))
                    
                    ch_id = item['snippet']['channelId'] if "video" in search_mode else item['snippet']['channelId']
                    if ch_id in processed_channels: continue
                    processed_channels.add(ch_id)

                    try:
                        ch = YOUTUBE.channels().list(part="snippet,statistics,contentDetails", id=ch_id).execute()['items'][0]
                        title = ch['snippet']['title']
                        channel_url = f"https://youtube.com/channel/{ch_id}"
                        
                        if title.strip() in exclude_data or channel_url in exclude_data: continue

                        subs = int(ch['statistics'].get('subscriberCount', 0))
                        up_id = ch['contentDetails']['relatedPlaylists']['uploads']
                        is_ok, avg_v, eff = check_performance(up_id, subs)
                        
                        if is_ok:
                            final_list.append({
                                "채널명": title, "구독자": subs, "평균 조회수": round(avg_v),
                                "효율": f"{eff*100:.1f}%", "이메일": extract_email_ai(ch['snippet']['description']),
                                "URL": channel_url, "프로필": ch['snippet']['thumbnails']['default']['url'],
                                "upload_id": up_id
                            })
                    except: continue
            status.update(label="✅ 콘텐츠 분석 완료!", state="complete", expanded=False)
        st.session_state.search_results = pd.DataFrame(final_list)

# 결과 출력 및 딥리서치
if isinstance(st.session_state.search_results, pd.DataFrame) and not st.session_state.search_results.empty:
    st.subheader("📊 분석 결과")
    event = st.dataframe(
        st.session_state.search_results,
        column_config={"프로필": st.column_config.ImageColumn("프로필"), "URL": st.column_config.LinkColumn("링크"), "upload_id": None},
        use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row"
    )

    if event.selection.rows:
        selected_idx = event.selection.rows[0]
        ch_info = st.session_state.search_results.iloc[selected_idx]
        st.markdown("---")
        st.subheader(f"🔍 '{ch_info['채널명']}' 딥리서치 (광고 분석)")
        with st.spinner("최신 광고 협업 사례를 찾는 중..."):
            ad_df = get_recent_ad_videos_ai(ch_info['upload_id'], 20)
            
            if not ad_df.empty:
                st.success(f"🎯 총 {len(ad_df)}개의 최근 광고/협업 영상이 감지되었습니다.")
                st.dataframe(
                    ad_df,
                    column_config={
                        "영상 링크": st.column_config.LinkColumn(
                            "영상 링크", 
                            display_text="바로가기" 
                        ),
                        "조회수": st.column_config.NumberColumn(format="%d회")
                    },
                    use_container_width=True, 
                    hide_index=True
                )
            else:
                # 데이터가 없을 때 표시되는 안전장치 (유지)
                st.warning("🧐 해당 분석 범위 내에서 최근 광고 협업 영상이 감지되지 않았습니다.")
💡 왜 이렇게 수정하나요?
